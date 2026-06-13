"""Low-level EDGAR HTTP helpers.

All requests must include the User-Agent header per SEC fair-access policy.
Rate limit: stay under 10 requests/second (enforced by tenacity + sleep).

Endpoints used (from RECON.md):
  - https://www.sec.gov/files/company_tickers_mf.json
  - https://www.sec.gov/files/company_tickers.json
  - https://data.sec.gov/submissions/CIK{padded10}.json
  - https://efts.sec.gov/LATEST/search-index?q="{ticker}"&forms=485BPOS
  - https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/index.json
  - https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}
"""

from __future__ import annotations

import time
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

_DEFAULT_USER_AGENT = "YizeLu yl3847@cornell.edu"
_RATE_LIMIT_DELAY = 0.11  # ~9 req/s to stay under 10/s


def _make_session(user_agent: str = _DEFAULT_USER_AGENT) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return session


# TODO: implement get_mf_ticker_map(session) -> list[list]
#   GET company_tickers_mf.json; return data["data"]
#   fields order confirmed: ["cik", "seriesId", "classId", "symbol"]
def get_mf_ticker_map(session: requests.Session) -> list[list[Any]]:
    # TODO: implement
    raise NotImplementedError


# TODO: implement get_ticker_map(session) -> dict[str, dict]
#   GET company_tickers.json; return the raw dict keyed by sequential int string
#   each value: {cik_str: int, ticker: str, title: str}
def get_ticker_map(session: requests.Session) -> dict[str, Any]:
    # TODO: implement
    raise NotImplementedError


# TODO: implement get_submissions(cik_int, session) -> dict
#   GET data.sec.gov/submissions/CIK{cik:010d}.json
#   Returns full submissions payload; caller accesses ["filings"]["recent"]
def get_submissions(cik: int, session: requests.Session) -> dict[str, Any]:
    # TODO: implement
    raise NotImplementedError


# TODO: implement get_filing_index(cik_int, accession, session) -> list[dict]
#   accession: dashed form (e.g. "0001193125-25-325143")
#   URL: /Archives/edgar/data/{cik}/{accession_no_dashes}/index.json
#   Returns directory["item"] list; each item has "name", "type", "size"
#   NOTE: index.json has NO primary-document marker — use primaryDocument from submissions
def get_filing_index(cik: int, accession: str, session: requests.Session) -> list[dict[str, Any]]:
    # TODO: implement
    raise NotImplementedError


# TODO: implement full_text_search(ticker, session, form="485BPOS") -> list[dict]
#   GET efts.sec.gov/LATEST/search-index?q="{ticker}"&forms={form}
#   Returns hits["hits"] list sorted by relevance (NOT date — sort by _source.file_date yourself)
#   Each hit: {"_source": {"adsh": ..., "ciks": [...], "form": ..., "file_date": ...}}
#   NOTE: results span multiple CIKs — caller must filter by known CIK
def full_text_search(
    ticker: str, session: requests.Session, form: str = "485BPOS"
) -> list[dict[str, Any]]:
    # TODO: implement
    raise NotImplementedError


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_json(url: str, session: requests.Session) -> Any:
    time.sleep(_RATE_LIMIT_DELAY)
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get_bytes(url: str, session: requests.Session) -> bytes:
    time.sleep(_RATE_LIMIT_DELAY)
    resp = session.get(url, timeout=60, stream=True)
    resp.raise_for_status()
    return resp.content
