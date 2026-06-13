"""Ticker → FundIdentity resolution.

Resolution order (from RECON.md):
  1. company_tickers_mf.json  (mutual funds / money-market share classes)
  2. company_tickers.json     (exchange-listed funds: ETFs, CEFs)
  3. EFTS full-text search    (fallback; slower, broader)
"""

from __future__ import annotations

from prospectus_fetcher.errors import TickerNotFound
from prospectus_fetcher.models import FundIdentity


# TODO: implement resolve_ticker(ticker, session) -> FundIdentity
#   1. Fetch https://www.sec.gov/files/company_tickers_mf.json via edgar.get_mf_ticker_map()
#      Fields order: ["cik", "seriesId", "classId", "symbol"]
#      cik is an int — zero-pad to 10 digits only when building URLs
#   2. If not found, fetch https://www.sec.gov/files/company_tickers.json via edgar.get_ticker_map()
#      Shape: object-of-objects keyed by sequential int string; values have cik_str (int!), ticker, title
#      series_id and class_id will be None for exchange-listed funds
#   3. If still not found, call edgar.full_text_search(ticker, form="485BPOS")
#      Filter _source.ciks to pick the right registrant; series_id/class_id remain None
#   4. Raise TickerNotFound(ticker) if all three fail
def resolve_ticker(ticker: str) -> FundIdentity:
    # TODO: implement
    raise TickerNotFound(ticker)
