"""Tests for filings.py: form selection, exclusions, Atom parsing."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from prospectus_fetcher.errors import NoProspectusFound
from prospectus_fetcher.filings import _parse_atom, _pick_best, select_filing
from prospectus_fetcher.models import FundIdentity

FIXTURES = Path(__file__).parent / "fixtures"


def _identity(series_id: str | None = "S000002852", cik: int = 891190) -> FundIdentity:
    return FundIdentity(
        ticker="VUSXX",
        cik=cik,
        series_id=series_id,
        class_id="C000007924",
        name="Vanguard Federal Money Market Fund",
        source="mf_map",
    )


def _submissions_payload(
    forms: list[str],
    dates: list[str],
    accessions: list[str],
    primary_docs: list[str],
) -> dict[str, object]:
    return {
        "filings": {
            "recent": {
                "form": forms,
                "filingDate": dates,
                "accessionNumber": accessions,
                "primaryDocument": primary_docs,
            }
        }
    }


class TestPickBest:
    def _candidates(self) -> list[dict[str, object]]:
        return [
            {"form": "485BPOS", "filing_date": date(2025, 12, 19), "accession": "ACC-NEW", "primary_document": "new.htm"},
            {"form": "485BPOS", "filing_date": date(2024, 12, 20), "accession": "ACC-OLD", "primary_document": "old.htm"},
            {"form": "497K",    "filing_date": date(2025, 10, 1),  "accession": "ACC-497K", "primary_document": "k.htm"},
        ]

    def test_selects_most_recent_by_date(self) -> None:
        filing = _pick_best(self._candidates(), ["485BPOS"], "VUSXX", "series", True, [])
        assert filing.accession == "ACC-NEW"
        assert filing.filing_date == date(2025, 12, 19)

    def test_first_form_in_priority_wins(self) -> None:
        filing = _pick_best(self._candidates(), ["485BPOS", "497K"], "VUSXX", "series", True, [])
        assert filing.form == "485BPOS"

    def test_falls_back_to_second_priority_form(self) -> None:
        candidates = [c for c in self._candidates() if c["form"] != "485BPOS"]
        filing = _pick_best(candidates, ["485BPOS", "497K"], "VUSXX", "series", True, [])
        assert filing.form == "497K"

    def test_excludes_497_supplement(self) -> None:
        candidates = [
            {"form": "497", "filing_date": date(2025, 11, 1), "accession": "ACC-497", "primary_document": None},
            {"form": "485BPOS", "filing_date": date(2024, 12, 20), "accession": "ACC-B", "primary_document": "b.htm"},
        ]
        filing = _pick_best(candidates, ["485BPOS", "497K", "497"], "VUSXX", "series", True, [])
        assert filing.form == "485BPOS"

    def test_excludes_497j(self) -> None:
        candidates = [
            {"form": "497J", "filing_date": date(2025, 11, 1), "accession": "ACC-J", "primary_document": None},
        ]
        with pytest.raises(NoProspectusFound):
            _pick_best(candidates, ["497J"], "VUSXX", "series", True, [])

    def test_excludes_485apos(self) -> None:
        candidates = [
            {"form": "485APOS", "filing_date": date(2025, 3, 1), "accession": "ACC-A", "primary_document": None},
        ]
        with pytest.raises(NoProspectusFound):
            _pick_best(candidates, ["485BPOS", "485APOS"], "VUSXX", "series", True, [])

    def test_raises_no_prospectus_when_no_matches(self) -> None:
        with pytest.raises(NoProspectusFound) as exc_info:
            _pick_best([], ["485BPOS", "497K"], "VUSXX", "series", True, [])
        assert "VUSXX" in str(exc_info.value)

    def test_accession_tiebreak(self) -> None:
        candidates = [
            {"form": "485BPOS", "filing_date": date(2025, 12, 19), "accession": "B", "primary_document": None},
            {"form": "485BPOS", "filing_date": date(2025, 12, 19), "accession": "A", "primary_document": None},
        ]
        filing = _pick_best(candidates, ["485BPOS"], "VUSXX", "series", True, [])
        assert filing.accession == "B"


class TestParseAtom:
    def test_parses_fixture_feed(self) -> None:
        xml = (FIXTURES / "atom_series_S000002852.xml").read_text()
        results = _parse_atom(xml)
        # 3 entries but accession is duplicated → should deduplicate to 2
        assert len(results) == 2

    def test_deduplicates_by_accession(self) -> None:
        xml = (FIXTURES / "atom_series_S000002852.xml").read_text()
        results = _parse_atom(xml)
        accessions = [r["accession"] for r in results]
        assert len(accessions) == len(set(accessions))

    def test_parsed_filing_date_is_date(self) -> None:
        xml = (FIXTURES / "atom_series_S000002852.xml").read_text()
        results = _parse_atom(xml)
        for r in results:
            assert isinstance(r["filing_date"], date)

    def test_primary_document_is_none(self) -> None:
        xml = (FIXTURES / "atom_series_S000002852.xml").read_text()
        results = _parse_atom(xml)
        for r in results:
            assert r["primary_document"] is None

    def test_returns_empty_on_bad_xml(self) -> None:
        results = _parse_atom("<not valid xml><<<")
        assert results == []


class TestSelectFiling:
    def test_submissions_path_when_no_series_id(self) -> None:
        identity = _identity(series_id=None, cik=884394)
        client = MagicMock()
        client.get_submissions.return_value = _submissions_payload(
            ["485BPOS"], ["2025-06-01"], ["0000884394-25-000001"], ["spy.htm"]
        )
        filing = select_filing(identity, client)
        assert filing.form == "485BPOS"
        assert not filing.series_scoped

    def test_atom_path_used_when_series_id_present(self) -> None:
        identity = _identity(series_id="S000002852", cik=891190)
        client = MagicMock()
        atom_xml = (FIXTURES / "atom_series_S000002852.xml").read_text()
        client.get_text.return_value = atom_xml
        client.get_submissions.return_value = _submissions_payload([], [], [], [])

        filing = select_filing(identity, client, forms_priority=["485BPOS"])
        assert filing.form == "485BPOS"
        assert filing.series_scoped is True
        # Submissions should NOT have been called because Atom succeeded
        client.get_submissions.assert_not_called()

    def test_falls_back_to_submissions_when_atom_empty(self) -> None:
        identity = _identity(series_id="S000002852")
        client = MagicMock()
        # Atom feeds return empty XML
        client.get_text.return_value = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        client.get_submissions.return_value = _submissions_payload(
            ["485BPOS"], ["2025-12-19"], ["0001193125-25-325143"], ["f43635d1.htm"]
        )

        filing = select_filing(identity, client, forms_priority=["485BPOS"])
        assert filing.form == "485BPOS"
        client.get_submissions.assert_called_once()
