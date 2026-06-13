"""EDGAR HTTP client.

All network access goes through EdgarClient. Key design decisions:

- Rate limiting: minimum-interval token bucket (thread-safe via threading.Lock).
  Default 5 req/s; SEC policy ceiling is 10 req/s.
- Retries: tenacity with exponential backoff on 429, 5xx, and transient 403.
  Respects Retry-After header when present. Cap: 4 attempts, max 60s total wait.
- Caching: company_tickers_mf.json and company_tickers.json are written to
  cache_dir as JSON files with a 24-hour TTL to avoid hammering static endpoints.
- Logging: every request is logged at DEBUG; retries and cache hits at INFO.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

import requests
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SEC_BASE = "https://www.sec.gov"
_DATA_BASE = "https://data.sec.gov"
_EFTS_BASE = "https://efts.sec.gov"

_MF_TICKERS_URL = f"{_SEC_BASE}/files/company_tickers_mf.json"
_TICKERS_URL = f"{_SEC_BASE}/files/company_tickers.json"

_CACHE_TTL_SECONDS = 86_400  # 24 hours


# ---------------------------------------------------------------------------
# URL builders (pure functions — easy to unit-test without a live client)
# ---------------------------------------------------------------------------

def submissions_url(cik: int) -> str:
    """Return the submissions JSON URL for a CIK, zero-padded to 10 digits."""
    return f"{_DATA_BASE}/submissions/CIK{cik:010d}.json"


def archive_index_url(cik: int, accession: str) -> str:
    """Return the filing index.json URL.

    cik is UNPADDED; accession has dashes stripped per RECON.md §4.
    """
    acc_nodash = accession.replace("-", "")
    return f"{_SEC_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/index.json"


def archive_doc_url(cik: int, accession: str, document: str) -> str:
    """Return the URL for a specific document inside a filing."""
    acc_nodash = accession.replace("-", "")
    return f"{_SEC_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/{document}"


def series_browse_url(series_id: str, type_prefix: str = "485") -> str:
    """Return the browse-edgar Atom feed URL for a series ID.

    NOTE (RECON.md §3): CIK=<seriesId> resolves to the registrant CIK and is
    NOT series-scoped. The feed returns all filings of the given type for the
    whole registrant fund family. Callers must filter by series/class after fetch.
    """
    params = {
        "action": "getcompany",
        "CIK": series_id,
        "type": type_prefix,
        "output": "atom",
    }
    return f"{_SEC_BASE}/cgi-bin/browse-edgar?{urlencode(params)}"


def fulltext_search_url(query: str, forms: str = "485BPOS") -> str:
    """Return the EFTS full-text search URL.

    query is placed inside double-quotes for exact-phrase matching.
    """
    params = {"q": f'"{query}"', "forms": forms}
    return f"{_EFTS_BASE}/LATEST/search-index?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Retry helpers
# ---------------------------------------------------------------------------

def _is_retryable(exc: BaseException) -> bool:
    """Retry on 429, 5xx, and transient 403 (SEC rate-limit enforcement)."""
    if isinstance(exc, requests.HTTPError):
        code = exc.response.status_code if exc.response is not None else 0
        return code in (403, 429) or code >= 500
    # Retry on connection/timeout errors too
    return isinstance(exc, (requests.ConnectionError, requests.Timeout))


def _after_retry_log(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    log.info(
        "Retrying request (attempt %d) after: %s",
        retry_state.attempt_number,
        exc,
    )


def _retry_wait(retry_state: RetryCallState) -> float:
    """Respect Retry-After header when present; otherwise exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and "Retry-After" in exc.response.headers
    ):
        try:
            return float(exc.response.headers["Retry-After"])
        except ValueError:
            pass
    # Exponential: 2, 4, 8 … capped at 60s
    return min(2.0 ** retry_state.attempt_number, 60.0)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Thread-safe minimum-interval rate limiter.

    Enforces at most `rate` calls per second by sleeping until the next
    permitted call time. Simpler than a full token bucket but sufficient for
    a single-threaded CLI; the lock makes it safe if threads are added later.
    """

    def __init__(self, rate: float) -> None:
        self._min_interval = 1.0 / rate
        self._next_allowed: float = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                time.sleep(wait)
            self._next_allowed = time.monotonic() + self._min_interval


# ---------------------------------------------------------------------------
# EdgarClient
# ---------------------------------------------------------------------------

class EdgarClient:
    """Single point of entry for all EDGAR HTTP calls.

    Parameters
    ----------
    user_agent:
        Required by SEC fair-access policy. Format: "Name email@example.com".
    cache_dir:
        Directory for caching static mapping files (ticker maps). Defaults to
        a ``edgar_cache`` subdirectory next to the Python file if not supplied.
    rate:
        Maximum requests per second. Default 5; SEC ceiling is 10.
    timeout:
        Per-request timeout in seconds (applied to both connect and read).
    """

    def __init__(
        self,
        user_agent: str,
        cache_dir: Path | None = None,
        rate: float = 5.0,
        timeout: int = 30,
    ) -> None:
        self._user_agent = user_agent
        self._cache_dir = cache_dir or Path(__file__).parent / "edgar_cache"
        self._timeout = timeout
        self._limiter = _TokenBucket(rate)

        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/html, */*",
            }
        )

    # ------------------------------------------------------------------
    # Core request methods
    # ------------------------------------------------------------------

    def get_json(self, url: str) -> dict[str, Any]:
        """Fetch a URL and parse the response as JSON."""
        return cast(dict[str, Any], self._request(url).json())

    def get_text(self, url: str) -> str:
        """Fetch a URL and return the response body as text."""
        return self._request(url).text

    def get_bytes(self, url: str) -> bytes:
        """Fetch a URL and return the raw response bytes."""
        return self._request(url, stream=True).content

    # ------------------------------------------------------------------
    # Cached mapping fetches
    # ------------------------------------------------------------------

    def get_mf_ticker_map(self) -> list[list[Any]]:
        """Return the mutual-fund ticker map rows.

        Cached to disk for 24 h. Shape per RECON.md §1:
          fields: ["cik", "seriesId", "classId", "symbol"]  (index 0-3)
          data:   [[cik_int, "S...", "C...", "TICKER"], ...]
        """
        payload = self._get_cached(_MF_TICKERS_URL, "company_tickers_mf.json")
        rows: list[list[Any]] = payload["data"]
        return rows

    def get_ticker_map(self) -> dict[str, Any]:
        """Return the exchange-listed ticker map.

        Cached to disk for 24 h. Shape per RECON.md §6:
          {"0": {"cik_str": int, "ticker": str, "title": str}, ...}
        Note: cik_str is an int despite the name; VUSXX is absent.
        """
        return self._get_cached(_TICKERS_URL, "company_tickers.json")

    # ------------------------------------------------------------------
    # High-level named fetches (thin wrappers around URL builders)
    # ------------------------------------------------------------------

    def get_submissions(self, cik: int) -> dict[str, Any]:
        """Fetch the submissions JSON for a CIK.

        Returns the full payload; callers access ["filings"]["recent"].
        Recent parallel arrays include: form, filingDate, accessionNumber,
        primaryDocument, primaryDocDescription (up to 1000 entries).
        """
        url = submissions_url(cik)
        log.debug("Fetching submissions for CIK %d", cik)
        return self.get_json(url)

    def get_filing_index(self, cik: int, accession: str) -> list[dict[str, Any]]:
        """Fetch the filing directory listing for an accession.

        Returns directory["item"] list. Per RECON.md §4: items have only
        "name", "type" (icon gif), "size" — NO primary-document marker.
        Use primaryDocument from submissions instead.
        """
        url = archive_index_url(cik, accession)
        log.debug("Fetching filing index for %s", accession)
        data = self.get_json(url)
        items: list[dict[str, Any]] = data["directory"]["item"]
        return items

    def get_fulltext_search(
        self, query: str, form: str = "485BPOS"
    ) -> list[dict[str, Any]]:
        """Search EDGAR full-text index and return hits.

        Per RECON.md §7: returns up to 60 hits for a ticker query; results
        span multiple CIKs — callers must filter. Key fields per hit:
          _source.adsh        accession (dashed)
          _source.ciks        list of zero-padded CIK strings
          _source.form        form type
          _source.file_date   "YYYY-MM-DD"
        """
        url = fulltext_search_url(query, form)
        log.debug("Full-text search: q=%r forms=%s", query, form)
        data = self.get_json(url)
        hits: list[dict[str, Any]] = data["hits"]["hits"]
        return hits

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(self, url: str, *, stream: bool = False) -> requests.Response:
        """Rate-limited, retried HTTP GET."""
        # Build a retried callable each time so tenacity state is fresh per call.
        @retry(
            retry=retry_if_exception(_is_retryable),
            wait=wait_exponential(multiplier=1, min=2, max=60),
            stop=stop_after_attempt(4),
            before_sleep=before_sleep_log(log, logging.INFO),
            reraise=True,
        )
        def _do_get() -> requests.Response:
            self._limiter.acquire()
            log.debug("GET %s", url)
            resp = self._session.get(url, timeout=self._timeout, stream=stream)
            resp.raise_for_status()
            return resp

        return _do_get()

    def _get_cached(self, url: str, filename: str) -> dict[str, Any]:
        """Fetch a JSON URL, caching the result to disk for _CACHE_TTL_SECONDS."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / filename

        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < _CACHE_TTL_SECONDS:
                log.info("Cache hit for %s (age %.0fs)", filename, age)
                return cast(dict[str, Any], json.loads(cache_file.read_text(encoding="utf-8")))
            log.info("Cache expired for %s (age %.0fs), re-fetching", filename, age)
        else:
            log.info("Cache miss for %s, fetching", filename)

        data = self.get_json(url)
        cache_file.write_text(json.dumps(data), encoding="utf-8")
        return data
