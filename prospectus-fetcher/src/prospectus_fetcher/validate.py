"""Post-download content validation.

This is a sanity assertion, not a hard gate. Series-scoped selection already
filters to the correct fund before downloading. validate_document() runs after
the file is saved and records what it found — the result is stored in the
manifest and in FetchResult.validation for auditability.

Failure does NOT delete the file. The pipeline sets status=VALIDATION_FAILED
and continues; the file is kept for manual inspection.

Signal tiers
------------
STRONG  — series_id (S......) or class_id (C......) found in document.
          These are machine-assigned EDGAR identifiers that are unique to one
          fund share class; their presence is conclusive.
WEAK    — ticker symbol found anywhere in the document text.
          A large multi-fund filing will mention all its tickers, so this
          confirms the file is at least fund-family-relevant but not that it
          is specifically about THIS share class.

passed  = at least one STRONG signal OR the ticker (WEAK) is present.
note    distinguishes the tier so readers can judge confidence.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from prospectus_fetcher.models import FundIdentity, ValidationResult

log = logging.getLogger(__name__)

# How many bytes to scan from the HEAD of the file.
# Vanguard-style iXBRL filings embed series/class IDs in the hidden <ix:header>
# near the top. Schwab-style filings (e.g. SWPPX, 6.9 MB) place them at ~18%
# into the document (~1.2 MB). 2 MB comfortably covers both patterns.
_SCAN_HEAD_BYTES = 2 * 1024 * 1024

# Also scan the last 256 KB as a tail safety-net for any filing that buries
# its XBRL metadata at the very end (some older SEC filers do this).
_SCAN_TAIL_BYTES = 256 * 1024

# Simple tag stripper: replace any <...> sequence with a space.
_TAG_RE = re.compile(r"<[^>]+>")


def validate_document(
    saved_path: str | Path,
    identity: FundIdentity,
) -> ValidationResult:
    """Scan the saved HTML for signals that it covers *identity*'s fund.

    Returns a ValidationResult; never raises.
    """
    path = Path(saved_path)
    signals_found: list[str] = []

    try:
        raw = _read_scan_window(path)
    except OSError as exc:
        log.warning("Validation: could not read %s: %s", path, exc)
        return ValidationResult(
            passed=False,
            signals_found=[],
            note=f"Could not read file: {exc}",
        )

    # Work on a lower-cased, tag-stripped view for text searches.
    # Keep the raw bytes for pattern searches that are case-sensitive (IDs).
    text = _TAG_RE.sub(" ", raw.decode("utf-8", errors="replace")).lower()
    raw_str = raw.decode("utf-8", errors="replace")

    strong = False

    # --- STRONG signals (unique EDGAR identifiers) ---
    # Series IDs appear verbatim in inline XBRL contextRef attributes and
    # in the visible text of fund-family prospectuses.
    if identity.series_id and identity.series_id in raw_str:
        signals_found.append(f"series_id:{identity.series_id}")
        strong = True
        log.debug("Validation STRONG: series_id %s found", identity.series_id)

    if identity.class_id and identity.class_id in raw_str:
            signals_found.append(f"class_id:{identity.class_id}")
            strong = True
            log.debug("Validation STRONG: class_id %s found", identity.class_id)

    # --- WEAK signal (ticker) ---
    ticker_lower = identity.ticker.lower()
    # Match the ticker as a whole word to avoid "SPY" matching "SPYDER"
    ticker_pattern = re.compile(r"\b" + re.escape(ticker_lower) + r"\b")
    if ticker_pattern.search(text):
        signals_found.append(f"ticker:{identity.ticker}")
        log.debug("Validation WEAK: ticker %s found", identity.ticker)

    passed = bool(signals_found)

    if strong:
        note = "covers this fund (series/class ID match)"
    elif signals_found:
        note = "ticker mentioned (weaker signal; multi-fund document likely)"
    else:
        note = (
            f"no signals found for ticker={identity.ticker} "
            f"series_id={identity.series_id} class_id={identity.class_id}"
        )

    log.info(
        "Validation %s for %s: signals=%s note=%r",
        "PASSED" if passed else "FAILED",
        identity.ticker,
        signals_found,
        note,
    )
    return ValidationResult(passed=passed, signals_found=signals_found, note=note)


def _read_scan_window(path: Path) -> bytes:
    """Read head + tail of file as a single bytes object for scanning.

    Reads up to _SCAN_HEAD_BYTES from the start, then up to _SCAN_TAIL_BYTES
    from the end (if the file is large enough that they don't overlap).
    Concatenating them with a separator that cannot match any signal pattern
    avoids accidentally joining two halves into a false positive.
    """
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(_SCAN_HEAD_BYTES)
        if size > _SCAN_HEAD_BYTES + _SCAN_TAIL_BYTES:
            fh.seek(-_SCAN_TAIL_BYTES, 2)
            tail = fh.read(_SCAN_TAIL_BYTES)
            return head + b"\x00" + tail
        return head
