"""Select the best prospectus filing for a resolved FundIdentity.

Selection strategy
------------------
Series-aware path (identity.series_id is not None):
  1. Fetch the browse-edgar Atom feed with type=485 to get 485BPOS/485APOS
     candidates, then a second feed with type=497 to capture 497K.
  2. The Atom feed is keyed by the registrant CIK — RECON.md §3 confirmed that
     CIK=<seriesId> still resolves to the registrant, not the series. However,
     each Atom entry's <file-number> links to the series registration statement
     (e.g. 033-49023 / 811-07043) so ALL entries already belong to the same
     trust. That is sufficient scoping for multi-fund trusts like Vanguard
     Admiral Funds, where the 485BPOS is a single multi-fund document filed
     under the trust's CIK. We accept the full-trust filing and mark
     series_scoped=True because we reached it via the series browse URL.
  3. If the series feed yields no candidate, fall back to scanning
     filings.recent from the submissions API.

Fallback path (identity.series_id is None — SPY, QQQ, FTS hits):
  Scan filings.recent parallel arrays from the submissions API.

Form priority / exclusions
--------------------------
  Default priority : ["485BPOS", "497K"]
  EXCLUDE set      : {"497", "497J"}   — supplements/stickers, not prospectuses
  Also drop        : "485APOS"          — not-yet-effective amendments
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

from prospectus_fetcher.edgar import EdgarClient, archive_index_url, series_browse_url
from prospectus_fetcher.errors import DownloadError, NoProspectusFound
from prospectus_fetcher.models import Filing, FundIdentity

log = logging.getLogger(__name__)

DEFAULT_FORMS: list[str] = ["485BPOS", "497K"]
_EXCLUDE: frozenset[str] = frozenset({"497", "497J"})
_NEVER_EFFECTIVE: frozenset[str] = frozenset({"485APOS"})

# Atom namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def select_filing(
    identity: FundIdentity,
    client: EdgarClient,
    forms_priority: list[str] | None = None,
) -> Filing:
    """Return the best Filing for *identity* according to *forms_priority*.

    Parameters
    ----------
    identity:
        Resolved fund identity (must have .cik; .series_id may be None).
    client:
        Configured EdgarClient for all HTTP calls.
    forms_priority:
        Ordered list of acceptable form types; first form with matches wins.
        Defaults to DEFAULT_FORMS = ["485BPOS", "497K"].
    """
    priority = forms_priority if forms_priority is not None else DEFAULT_FORMS
    forms_tried: list[str] = []

    if identity.series_id:
        candidates = _candidates_from_atom(identity, client)
        if not candidates:
            log.info(
                "Atom feed yielded no candidates for %s; falling back to submissions",
                identity.ticker,
            )
            candidates = _candidates_from_submissions(identity, client)
        source_label = f"series {identity.series_id}"
        series_scoped = True
    else:
        candidates = _candidates_from_submissions(identity, client)
        source_label = "submissions (no series mapping)"
        series_scoped = False

    return _pick_best(
        candidates,
        priority,
        identity.ticker,
        source_label,
        series_scoped,
        forms_tried,
    )


# ---------------------------------------------------------------------------
# Atom feed path
# ---------------------------------------------------------------------------

def _candidates_from_atom(
    identity: FundIdentity, client: EdgarClient
) -> list[dict[str, Any]]:
    """Fetch browse-edgar Atom feeds and return raw candidate dicts.

    Two queries are needed:
      type=485  → catches 485BPOS (and 485APOS which we later drop)
      type=497  → catches 497K (EDGAR prefix-matches, so "497" also surfaces
                  plain 497 / 497J which we drop in _pick_best)
    """
    assert identity.series_id is not None
    candidates: list[dict[str, Any]] = []

    for type_prefix in ("485", "497"):
        url = series_browse_url(identity.series_id, type_prefix=type_prefix)
        try:
            xml_text = client.get_text(url)
        except Exception as exc:
            log.warning("Atom feed fetch failed (%s): %s", type_prefix, exc)
            continue
        candidates.extend(_parse_atom(xml_text))

    log.debug("Atom feeds yielded %d raw candidates for %s", len(candidates), identity.ticker)
    return candidates


def _parse_atom(xml_text: str) -> list[dict[str, Any]]:
    """Parse a browse-edgar Atom feed into a list of candidate dicts.

    Each entry appears twice (Act 33 + Act 40) — deduplicate by accession.
    XML structure (RECON.md §3):
      <entry>
        <content type="text/xml">
          <filing-type>485BPOS</filing-type>
          <filing-date>2025-12-19</filing-date>
          <accession-number>0001193125-25-325143</accession-number>
        </content>
      </entry>
    The <content> children have NO namespace.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        log.warning("Failed to parse Atom XML: %s", exc)
        return []

    seen: set[str] = set()
    results: list[dict[str, Any]] = []

    for entry in root.findall(f"{{{_ATOM_NS}}}entry"):
        content = entry.find(f"{{{_ATOM_NS}}}content")
        if content is None:
            continue

        def _text(tag: str) -> str:
            # Content children carry the Atom namespace in the live feed
            # (RECON.md §3 noted "no namespace" but live inspection shows
            # they inherit {http://www.w3.org/2005/Atom}). Try namespaced
            # first, fall back to unqualified. Use `is not None` because an
            # Element with no children is falsy in Python's xml.etree.
            el = content.find(f"{{{_ATOM_NS}}}{tag}")
            if el is None:
                el = content.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        accession = _text("accession-number")
        form = _text("filing-type")
        filing_date_str = _text("filing-date")

        if not accession or accession in seen:
            continue
        seen.add(accession)

        try:
            filing_date = date.fromisoformat(filing_date_str)
        except ValueError:
            log.debug("Unparseable date %r in Atom entry, skipping", filing_date_str)
            continue

        results.append(
            {
                "form": form,
                "filing_date": filing_date,
                "accession": accession,
                # Atom feed has no primaryDocument field; locate_document will
                # resolve it via index.json if needed.
                "primary_document": None,
            }
        )

    return results


# ---------------------------------------------------------------------------
# Submissions fallback path
# ---------------------------------------------------------------------------

def _candidates_from_submissions(
    identity: FundIdentity, client: EdgarClient
) -> list[dict[str, Any]]:
    """Scan filings.recent from the submissions API for prospectus forms.

    Returns candidates as dicts with keys matching the Atom path output so
    _pick_best can treat both paths uniformly.

    Per RECON.md §2: filings.recent holds up to 1000 entries in parallel
    arrays. 485BPOS may appear at index 52+ for multi-fund registrants.
    """
    try:
        payload = client.get_submissions(identity.cik)
    except Exception as exc:
        log.warning("Submissions fetch failed for CIK %d: %s", identity.cik, exc)
        return []

    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])

    candidates: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        try:
            filing_date = date.fromisoformat(dates[i])
        except (ValueError, IndexError):
            continue
        candidates.append(
            {
                "form": form,
                "filing_date": filing_date,
                "accession": accessions[i] if i < len(accessions) else "",
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            }
        )

    log.debug(
        "Submissions yielded %d total filings for CIK %d", len(candidates), identity.cik
    )
    return candidates


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def _pick_best(
    candidates: list[dict[str, Any]],
    priority: list[str],
    ticker: str,
    source_label: str,
    series_scoped: bool,
    forms_tried: list[str],
) -> Filing:
    """Walk priority list; return the most recent Filing for the first form that has matches."""
    # Filter out excluded and never-effective forms up front
    eligible = [
        c for c in candidates
        if c["form"] not in _EXCLUDE and c["form"] not in _NEVER_EFFECTIVE
    ]

    for form in priority:
        forms_tried.append(form)
        matches = [c for c in eligible if c["form"] == form]
        if not matches:
            continue

        # Most recent by filing_date; use accession as lexicographic tie-break
        best = max(matches, key=lambda c: (c["filing_date"], c["accession"]))
        reason = f"latest {form} covering {source_label}"
        log.info("Selected %s filed %s for %s", form, best["filing_date"], ticker)

        return Filing(
            form=best["form"],
            filing_date=best["filing_date"],
            accession=best["accession"],
            primary_document=best["primary_document"],
            series_scoped=series_scoped,
            selection_reason=reason,
        )

    raise NoProspectusFound(ticker, forms_tried)


# ---------------------------------------------------------------------------
# Document location
# ---------------------------------------------------------------------------

def locate_document(
    filing: Filing,
    identity: FundIdentity,
    client: EdgarClient,
) -> str:
    """Return the full URL to the primary prospectus document.

    If filing.primary_document is already set (submissions path), build the
    archive URL directly.

    If it is None (Atom path), fetch index.json and pick the best .htm:
    the largest .htm/.html that is not a cover page or known exhibit file.
    Heuristic: exclude files whose names suggest they are not the main body
    (e.g. contain "cover", "ex-", "exhibit"), then take the largest by size.
    For Vanguard-style mega-filings the primary doc is ~5× larger than any
    other .htm, so size is a reliable signal (RECON.md §4/§5).
    """
    from prospectus_fetcher.edgar import archive_doc_url

    if filing.primary_document:
        return archive_doc_url(identity.cik, filing.accession, filing.primary_document)

    # Atom path: resolve via index.json
    items = client.get_filing_index(identity.cik, filing.accession)
    htm_items = [
        item for item in items
        if item["name"].lower().endswith((".htm", ".html"))
        and not _is_exhibit_or_cover(item["name"])
    ]

    if not htm_items:
        raise DownloadError(
            archive_index_url(identity.cik, filing.accession),
            "No .htm files found in filing index",
        )

    def _size(item: dict[str, Any]) -> int:
        try:
            return int(item.get("size", 0))
        except (ValueError, TypeError):
            return 0

    # Largest .htm is the main prospectus body (RECON.md §4: f43635d1.htm is
    # 5.8 MB vs 1.5 MB for the next-largest file in the same filing).
    best_item = max(htm_items, key=_size)
    doc_name = best_item["name"]
    log.info("Located primary document via index: %s", doc_name)

    # Cache the resolved name back onto the Filing object for the manifest
    filing.primary_document = doc_name
    return archive_doc_url(identity.cik, filing.accession, doc_name)


def _is_exhibit_or_cover(name: str) -> bool:
    """Return True if the filename looks like a cover page or exhibit, not a prospectus body."""
    lower = name.lower()
    # Typical exhibit/cover patterns in EDGAR filings
    skip_fragments = ("cover", "ex-", "exhibit", "xbrl", "r1.", "r2.", "r3.")
    return any(frag in lower for frag in skip_fragments)
