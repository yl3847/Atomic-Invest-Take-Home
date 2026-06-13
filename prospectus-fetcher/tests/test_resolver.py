"""Tests for resolver.py: ticker → FundIdentity chain."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from prospectus_fetcher.errors import TickerNotFound
from prospectus_fetcher.models import FundIdentity
from prospectus_fetcher.resolver import resolve

FIXTURES = Path(__file__).parent / "fixtures"


def _load_mf_rows() -> list[list[object]]:
    data = json.loads((FIXTURES / "company_tickers_mf.json").read_text())
    return data["data"]  # type: ignore[no-any-return]


def _load_company_map() -> dict[str, object]:
    return json.loads((FIXTURES / "company_tickers.json").read_text())  # type: ignore[no-any-return]


def _make_client(mf_rows: list[list[object]], company_map: dict[str, object]) -> MagicMock:
    client = MagicMock()
    client.get_mf_ticker_map.return_value = mf_rows
    client.get_ticker_map.return_value = company_map
    client.get_fulltext_search.return_value = []
    return client


class TestMfMapHit:
    def test_vusxx_resolves_via_mf_map(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        identity = resolve("VUSXX", client)

        assert identity.ticker == "VUSXX"
        assert identity.cik == 891190
        assert identity.series_id == "S000002852"
        assert identity.class_id == "C000007924"
        assert identity.source == "mf_map"

    def test_mf_map_hit_skips_company_map(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        resolve("VUSXX", client)
        client.get_ticker_map.assert_not_called()

    def test_lowercase_ticker_normalised(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        identity = resolve("vusxx", client)
        assert identity.ticker == "VUSXX"

    def test_whitespace_stripped(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        identity = resolve("  VUSXX  ", client)
        assert identity.ticker == "VUSXX"


class TestCompanyMapHit:
    def test_spy_resolves_via_company_map(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        identity = resolve("SPY", client)

        assert identity.ticker == "SPY"
        assert identity.cik == 884394
        assert identity.series_id is None
        assert identity.class_id is None
        assert identity.source == "company_map"

    def test_returns_fund_identity(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        identity = resolve("QQQ", client)
        assert isinstance(identity, FundIdentity)
        assert identity.cik == 1067839


class TestFullTextFallback:
    def test_falls_back_to_fulltext_when_not_in_maps(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        # Make EDGAR full-text search return a hit for an unknown ticker
        client.get_fulltext_search.return_value = [
            {
                "_source": {
                    "ciks": ["0000999999"],
                    "display_names": ["SOME FUND (CIK 0000999999)"],
                    "file_date": "2025-01-01",
                    "form": "485BPOS",
                }
            }
        ]
        identity = resolve("FAKEX", client)
        assert identity.cik == 999999
        assert identity.source == "full_text_search"


class TestTickerNotFound:
    def test_raises_ticker_not_found_for_unknown(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        client.get_fulltext_search.return_value = []

        with pytest.raises(TickerNotFound):
            resolve("ZZZZZ", client)

    def test_suggestion_offered_for_close_match(self) -> None:
        client = _make_client(_load_mf_rows(), _load_company_map())
        client.get_fulltext_search.return_value = []

        with pytest.raises(TickerNotFound):
            resolve("VUSXY", client)
