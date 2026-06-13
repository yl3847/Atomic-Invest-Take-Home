"""Live smoke tests — skipped unless -m network is passed.

Run with:
    SEC_USER_AGENT="Your Name your@email.com" pytest -m network
"""

from __future__ import annotations

import os

import pytest

from prospectus_fetcher.edgar import EdgarClient
from prospectus_fetcher.filings import locate_document, select_filing
from prospectus_fetcher.resolver import resolve


@pytest.fixture()
def client() -> EdgarClient:
    ua = os.environ.get("SEC_USER_AGENT", "Test User test@example.com")
    return EdgarClient(user_agent=ua)


@pytest.mark.network
def test_vusxx_resolves_live(client: EdgarClient) -> None:
    identity = resolve("VUSXX", client)
    assert identity.cik == 891190
    assert identity.series_id is not None
    assert identity.series_id.startswith("S")


@pytest.mark.network
def test_vusxx_select_filing_live(client: EdgarClient) -> None:
    identity = resolve("VUSXX", client)
    filing = select_filing(identity, client)
    assert filing.form in ("485BPOS", "497K")
    assert filing.accession


@pytest.mark.network
def test_vusxx_locate_document_live(client: EdgarClient) -> None:
    identity = resolve("VUSXX", client)
    filing = select_filing(identity, client)
    url = locate_document(filing, identity, client)
    assert url.startswith("https://www.sec.gov/Archives/")
    assert url.endswith(".htm") or url.endswith(".html")
