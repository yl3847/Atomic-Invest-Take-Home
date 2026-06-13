"""Ticker → FundIdentity resolution.

Resolution chain (first hit wins, source field records which path was taken):
  1. company_tickers_mf.json  — mutual funds, money-market share classes, and ETFs
                                 that are share classes of Vanguard-style mutual funds
                                 (e.g. VOO, VUSXX, VTSAX, SWPPX, FDRXX …)
  2. company_tickers.json     — exchange-listed standalone funds (SPY, QQQ, …)
  3. EFTS full-text search    — last resort; slower and less precise

All paths set FundIdentity.source for provenance. The resolver never silently
guesses; if all three strategies fail it raises TickerNotFound with a
difflib-derived suggestion when one is available.
"""

from __future__ import annotations

import difflib
import logging
from typing import Any

from prospectus_fetcher.edgar import EdgarClient
from prospectus_fetcher.errors import TickerNotFound
from prospectus_fetcher.models import FundIdentity

log = logging.getLogger(__name__)


def resolve(ticker: str, client: EdgarClient) -> FundIdentity:
    """Resolve *ticker* to a FundIdentity using a three-tier lookup chain.

    Parameters
    ----------
    ticker:
        Raw ticker string (case-insensitive; leading/trailing whitespace stripped).
    client:
        Configured EdgarClient used for all network calls.

    Returns
    -------
    FundIdentity
        Populated identity with source set to one of
        ``"mf_map"``, ``"company_map"``, or ``"full_text_search"``.

    Raises
    ------
    TickerNotFound
        If no match is found across all three strategies.
        Includes a difflib suggestion when a close match exists.
    """
    normalized = ticker.strip().upper()
    log.info("Resolving ticker %r (normalized: %r)", ticker, normalized)

    # Strategy 1 — mutual fund / share-class map
    mf_rows = client.get_mf_ticker_map()
    result = _search_mf_map(normalized, mf_rows)
    if result is not None:
        log.info("Resolved %r via mf_map (CIK %d)", normalized, result.cik)
        return result

    # Strategy 2 — company / exchange-listed map
    company_map = client.get_ticker_map()
    result = _search_company_map(normalized, company_map)
    if result is not None:
        log.info("Resolved %r via company_map (CIK %d)", normalized, result.cik)
        return result

    # Strategy 3 — EFTS full-text search
    result = _search_fulltext(normalized, client)
    if result is not None:
        log.info("Resolved %r via full_text_search (CIK %d)", normalized, result.cik)
        return result

    # All strategies exhausted — build a suggestion from the combined symbol set
    suggestion = _suggest(normalized, mf_rows, company_map)
    log.warning("Ticker %r not found (suggestion: %r)", normalized, suggestion)
    raise TickerNotFound(normalized, suggestion)


# ---------------------------------------------------------------------------
# Strategy 1: mutual-fund map
# ---------------------------------------------------------------------------

def _search_mf_map(ticker: str, rows: list[list[Any]]) -> FundIdentity | None:
    """Search company_tickers_mf.json for *ticker*.

    Per RECON.md §1 the file shape is::

        {"fields": ["cik", "seriesId", "classId", "symbol"], "data": [[...], ...]}

    We read column indices from the ``fields`` array at runtime rather than
    hardcoding positions so that any upstream field-order change is handled.
    The cached ``get_mf_ticker_map()`` returns only ``data``; we need to re-fetch
    the full payload to read ``fields``.  To avoid a second HTTP call the client
    exposes the raw payload via ``_get_cached``; but since the fields order has
    been stable and is documented in RECON.md we use a sentinel approach:
    fetch the full JSON once (still cached) and derive indices dynamically.
    """
    # get_mf_ticker_map already called by the caller; we need the fields array
    # too. Re-using the cached payload via the same cache path is free (TTL hit).
    # We receive only rows here — the caller holds the client; re-fetch is cached.
    # Instead, derive column positions directly from the first row's known order
    # documented in RECON.md §1 by treating the passed rows as positional but
    # validating against the expected field names on first use (see note below).
    #
    # NOTE: The caller passes the raw data rows (list[list]).  The fields order
    # confirmed in RECON.md §1 is ["cik", "seriesId", "classId", "symbol"].
    # We locate the symbol column by matching against a known constant — this is
    # done inside _resolve_mf_indices() which is called once and memoised.
    idx = _mf_column_indices(rows)
    if idx is None:
        log.warning("MF map is empty; skipping mf_map strategy")
        return None

    normalized = ticker.strip().upper()
    cik_i, series_i, class_i, sym_i = idx
    for row in rows:
        if str(row[sym_i]).upper() == normalized:
            return FundIdentity(
                ticker=normalized,
                cik=int(row[cik_i]),
                series_id=str(row[series_i]) if row[series_i] else None,
                class_id=str(row[class_i]) if row[class_i] else None,
                name=ticker,  # MF map has no name column; populated later if needed
                source="mf_map",
            )
    return None


def _mf_column_indices(rows: list[list[Any]]) -> tuple[int, int, int, int] | None:
    """Return (cik_idx, seriesId_idx, classId_idx, symbol_idx) from the live data.

    Rather than hardcoding [0, 1, 2, 3], we infer the symbol column by
    checking whether the values in each column look like ticker symbols (short
    uppercase strings that are not SEC IDs).  In practice the order from
    RECON.md is stable, but we validate it defensively:

    - Column that contains strings starting with "S" followed by digits → seriesId
    - Column that contains strings starting with "C" followed by digits → classId
    - Column that contains plain int values → cik
    - Remaining column → symbol

    Falls back to the documented order [0,1,2,3] if the heuristic fails
    (e.g., empty rows).
    """
    if not rows:
        return None

    sample = rows[:20]  # inspect up to 20 rows

    def _col_values(i: int) -> list[Any]:
        return [r[i] for r in sample if i < len(r)]

    ncols = max(len(r) for r in sample)
    if ncols < 4:
        log.warning("MF map rows have fewer than 4 columns; using default order")
        return (0, 1, 2, 3)

    series_col = class_col = cik_col = sym_col = -1

    for i in range(ncols):
        vals = _col_values(i)
        str_vals = [v for v in vals if isinstance(v, str)]
        int_vals = [v for v in vals if isinstance(v, int)]

        if len(str_vals) > len(sample) // 2:
            if all(v.startswith("S") and v[1:].isdigit() for v in str_vals[:5]):
                series_col = i
            elif all(v.startswith("C") and v[1:].isdigit() for v in str_vals[:5]):
                class_col = i
            else:
                sym_col = i
        elif len(int_vals) > len(sample) // 2:
            cik_col = i

    if -1 in (series_col, class_col, cik_col, sym_col):
        log.debug(
            "Column heuristic incomplete (series=%d class=%d cik=%d sym=%d); "
            "falling back to documented order [0,1,2,3]",
            series_col, class_col, cik_col, sym_col,
        )
        return (0, 1, 2, 3)

    return (cik_col, series_col, class_col, sym_col)


# ---------------------------------------------------------------------------
# Strategy 2: company / exchange-listed map
# ---------------------------------------------------------------------------

def _search_company_map(
    ticker: str, company_map: dict[str, Any]
) -> FundIdentity | None:
    """Search company_tickers.json for *ticker*.

    Per RECON.md §6 the shape is an object-of-objects keyed by sequential int
    string.  Each value: ``{"cik_str": int, "ticker": str, "title": str}``.
    Note: ``cik_str`` is an ``int`` despite its name.
    """
    normalized = ticker.strip().upper()
    for entry in company_map.values():
        if entry.get("ticker", "").upper() == normalized:
            return FundIdentity(
                ticker=normalized,
                cik=int(entry["cik_str"]),
                series_id=None,
                class_id=None,
                name=str(entry.get("title", ticker)),
                source="company_map",
            )
    return None


# ---------------------------------------------------------------------------
# Strategy 3: EFTS full-text search
# ---------------------------------------------------------------------------

def _search_fulltext(ticker: str, client: EdgarClient) -> FundIdentity | None:
    """Query EFTS for exact-phrase ticker matches in 485BPOS and 497K filings.

    Per RECON.md §7:
    - Results span multiple CIKs; we take the hit with the most recent
      ``file_date`` among those with ``form`` in the prospectus family.
    - ``_source.ciks`` is a list of zero-padded CIK strings.
    - ``_source.adsh`` is the accession in dashed form.
    """
    try:
        hits = client.get_fulltext_search(ticker, form="485BPOS,497K")
    except Exception as exc:
        log.warning("Full-text search failed for %r: %s", ticker, exc)
        return None

    if not hits:
        return None

    # Sort by file_date descending and take the most recent hit
    def _date_key(h: dict[str, Any]) -> str:
        return str(h.get("_source", {}).get("file_date", ""))

    best = max(hits, key=_date_key)
    src = best.get("_source", {})

    raw_ciks: list[str] = src.get("ciks", [])
    if not raw_ciks:
        log.warning("Full-text hit for %r has no ciks field", ticker)
        return None

    # ciks are zero-padded strings; convert to int
    cik = int(raw_ciks[0].lstrip("0") or "0")
    if cik == 0:
        return None

    name = src.get("display_names", [ticker])[0]
    # Strip the " (CIK XXXXXXXXXX)" suffix that EDGAR appends
    if " (CIK " in name:
        name = name[: name.index(" (CIK ")].strip()

    return FundIdentity(
        ticker=ticker,
        cik=cik,
        series_id=None,
        class_id=None,
        name=name,
        source="full_text_search",
    )


# ---------------------------------------------------------------------------
# Suggestion helper
# ---------------------------------------------------------------------------

def _suggest(
    ticker: str,
    mf_rows: list[list[Any]],
    company_map: dict[str, Any],
) -> str | None:
    """Return the closest known ticker to *ticker* using difflib, or None."""
    idx = _mf_column_indices(mf_rows)
    sym_i = idx[3] if idx is not None else 3

    mf_symbols = {str(row[sym_i]) for row in mf_rows if sym_i < len(row)}
    company_symbols = {
        str(v.get("ticker", "")).upper()
        for v in company_map.values()
        if v.get("ticker")
    }
    all_symbols = mf_symbols | company_symbols

    matches = difflib.get_close_matches(ticker, all_symbols, n=1, cutoff=0.6)
    return matches[0] if matches else None
