"""Tests for validate.py: content signal detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from prospectus_fetcher.models import FundIdentity
from prospectus_fetcher.validate import validate_document


def _identity(
    ticker: str = "VUSXX",
    series_id: str | None = "S000002233",
    class_id: str | None = "C000005732",
) -> FundIdentity:
    return FundIdentity(
        ticker=ticker,
        cik=891190,
        series_id=series_id,
        class_id=class_id,
        name="Vanguard Treasury Money Market Fund",
        source="mf_map",
    )


def _write_htm(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".htm")
    Path(path).write_text(content, encoding="utf-8")
    return Path(path)


class TestStrongSignal:
    def test_series_id_found_passes(self) -> None:
        path = _write_htm("<html>contextRef='S000002233' class='fund'</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert any("series_id" in s for s in result.signals_found)
        assert "series/class ID match" in result.note
        path.unlink()

    def test_class_id_found_passes(self) -> None:
        path = _write_htm("<html>some text C000005732 more text</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert any("class_id" in s for s in result.signals_found)
        path.unlink()

    def test_both_ids_found(self) -> None:
        path = _write_htm("<html>S000002233 and C000005732</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert len([s for s in result.signals_found if "series_id" in s or "class_id" in s]) == 2
        path.unlink()


class TestWeakSignal:
    def test_ticker_only_without_ids_does_not_pass(self) -> None:
        # Ticker present but no series/class ID → WEAK; passed=False
        # Rationale: a combined statutory prospectus mentions all covered tickers,
        # so a ticker match alone cannot confirm THIS fund's content is present.
        path = _write_htm("<html><p>Vanguard VUSXX Money Market</p></html>")
        result = validate_document(path, _identity(series_id=None, class_id=None))
        assert not result.passed
        assert any("ticker" in s for s in result.signals_found)
        assert "weak signal only" in result.note
        path.unlink()

    def test_ticker_only_when_ids_present_but_missing_does_not_pass(self) -> None:
        # Document mentions ticker but NOT the series/class IDs → WEAK only
        path = _write_htm("<html><p>VUSXX is a money market fund.</p></html>")
        result = validate_document(path, _identity())
        assert not result.passed
        assert any("ticker" in s for s in result.signals_found)
        assert "weak signal only" in result.note
        path.unlink()

    def test_ticker_whole_word_match(self) -> None:
        # "SPYDER" should not match "SPY"
        path = _write_htm("<html>SPYDER ETF prospectus</html>")
        result = validate_document(path, FundIdentity(
            ticker="SPY", cik=884394, series_id=None, class_id=None,
            name="SPDR S&P 500 ETF Trust", source="company_map",
        ))
        assert not result.passed
        path.unlink()


class TestCrossFundIsolation:
    """Critical: a document containing fund A's IDs must not pass for fund B."""

    def test_combined_book_wrong_fund_fails(self) -> None:
        # Simulate a combined statutory prospectus that contains VOO's IDs
        # but NOT VTSAX's — validating against VTSAX must fail.
        voo_series = "S000002839"
        voo_class = "C000092055"
        vtsax_series = "S000002848"
        vtsax_class = "C000007806"

        # Document has VOO's IDs but not VTSAX's
        htm = f"<html>{voo_series} {voo_class} Vanguard 500 Index Fund VTSAX</html>"
        path = _write_htm(htm)

        vtsax_identity = FundIdentity(
            ticker="VTSAX",
            cik=36405,
            series_id=vtsax_series,
            class_id=vtsax_class,
            name="Vanguard Total Stock Market Index Fund",
            source="mf_map",
        )
        result = validate_document(path, vtsax_identity)
        # VTSAX's series/class IDs are not in the document → must fail
        assert not result.passed
        assert not any("series_id" in s for s in result.signals_found)
        assert not any("class_id" in s for s in result.signals_found)
        path.unlink()

    def test_combined_book_correct_fund_passes(self) -> None:
        # Same document but validated against VOO → must pass (its IDs are present)
        voo_series = "S000002839"
        voo_class = "C000092055"

        htm = f"<html>{voo_series} {voo_class} Vanguard 500 Index Fund</html>"
        path = _write_htm(htm)

        voo_identity = FundIdentity(
            ticker="VOO",
            cik=36405,
            series_id=voo_series,
            class_id=voo_class,
            name="Vanguard 500 Index Fund",
            source="mf_map",
        )
        result = validate_document(path, voo_identity)
        assert result.passed
        assert any("series_id" in s for s in result.signals_found)
        path.unlink()

    def test_combined_book_both_funds_present_both_pass(self) -> None:
        # A genuine combined document containing both funds' IDs passes for each.
        voo_series = "S000002839"
        voo_class = "C000092055"
        vtsax_series = "S000002848"
        vtsax_class = "C000007806"

        htm = f"<html>{voo_series} {voo_class} {vtsax_series} {vtsax_class}</html>"
        path = _write_htm(htm)

        for ticker, sid, cid, name in [
            ("VOO",   voo_series,   voo_class,   "Vanguard 500 Index Fund"),
            ("VTSAX", vtsax_series, vtsax_class, "Vanguard Total Stock Market Index Fund"),
        ]:
            identity = FundIdentity(
                ticker=ticker, cik=36405, series_id=sid, class_id=cid,
                name=name, source="mf_map",
            )
            result = validate_document(path, identity)
            assert result.passed, f"{ticker} should pass in combined document"
        path.unlink()


class TestNoSignal:
    def test_no_signals_fails(self) -> None:
        path = _write_htm("<html><p>This is a completely unrelated document.</p></html>")
        result = validate_document(path, _identity())
        assert not result.passed
        assert result.signals_found == []
        assert "no signals found" in result.note
        path.unlink()

    def test_missing_file_returns_failed(self) -> None:
        result = validate_document("/nonexistent/path/file.htm", _identity())
        assert not result.passed
        assert "Could not read file" in result.note


class TestNoIds:
    def test_no_series_or_class_ticker_only_does_not_pass(self) -> None:
        # When the identity has no series/class IDs (e.g. company_map resolution),
        # a ticker match alone is not sufficient for passed=True.
        path = _write_htm("<html>VUSXX fund prospectus 2025</html>")
        result = validate_document(path, _identity(series_id=None, class_id=None))
        assert not result.passed
        assert any("ticker" in s for s in result.signals_found)
        path.unlink()
