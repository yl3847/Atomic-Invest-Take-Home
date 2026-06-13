"""Tests for validate.py: content signal detection."""

from __future__ import annotations

import tempfile
from pathlib import Path

from prospectus_fetcher.models import FundIdentity
from prospectus_fetcher.validate import validate_document


def _identity(
    ticker: str = "VUSXX",
    series_id: str | None = "S000002852",
    class_id: str | None = "C000007924",
) -> FundIdentity:
    return FundIdentity(
        ticker=ticker,
        cik=891190,
        series_id=series_id,
        class_id=class_id,
        name="Vanguard Federal Money Market Fund",
        source="mf_map",
    )


def _write_htm(content: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=".htm")
    Path(path).write_text(content, encoding="utf-8")
    return Path(path)


class TestStrongSignal:
    def test_series_id_found_passes(self) -> None:
        path = _write_htm("<html>contextRef='S000002852' class='fund'</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert any("series_id" in s for s in result.signals_found)
        assert "series/class ID match" in result.note
        path.unlink()

    def test_class_id_found_passes(self) -> None:
        path = _write_htm("<html>some text C000007924 more text</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert any("class_id" in s for s in result.signals_found)
        path.unlink()

    def test_both_ids_found(self) -> None:
        path = _write_htm("<html>S000002852 and C000007924</html>")
        result = validate_document(path, _identity())
        assert result.passed
        assert len([s for s in result.signals_found if "series_id" in s or "class_id" in s]) == 2
        path.unlink()


class TestWeakSignal:
    def test_ticker_found_without_ids_passes(self) -> None:
        # No series_id or class_id in document, but ticker present
        path = _write_htm("<html><p>Vanguard VUSXX Money Market</p></html>")
        result = validate_document(path, _identity(series_id=None, class_id=None))
        assert result.passed
        assert any("ticker" in s for s in result.signals_found)
        assert "weaker signal" in result.note
        path.unlink()

    def test_ticker_whole_word_match(self) -> None:
        # "SPYDER" should not match "SPY"
        path = _write_htm("<html>SPYDER ETF prospectus</html>")
        result = validate_document(path, FundIdentity(
            ticker="SPY", cik=884394, series_id=None, class_id=None,
            name="SPDR S&P 500 ETF Trust", source="company_map",
        ))
        # "SPY" as whole word is NOT in "SPYDER" — expect failure
        assert not result.passed
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


class TestNoneIds:
    def test_no_series_or_class_falls_through_to_ticker(self) -> None:
        path = _write_htm("<html>VUSXX fund prospectus 2025</html>")
        result = validate_document(path, _identity(series_id=None, class_id=None))
        assert result.passed
        path.unlink()
