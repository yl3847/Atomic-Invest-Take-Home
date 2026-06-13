"""Unit tests for edgar.py URL builder functions (no network needed)."""

from __future__ import annotations

from prospectus_fetcher.edgar import (
    archive_doc_url,
    archive_index_url,
    fulltext_search_url,
    series_browse_url,
    submissions_url,
)


def test_submissions_url_zero_pads_to_10() -> None:
    assert submissions_url(891190) == "https://data.sec.gov/submissions/CIK0000891190.json"


def test_submissions_url_already_long_cik() -> None:
    assert submissions_url(1234567890) == "https://data.sec.gov/submissions/CIK1234567890.json"


def test_archive_index_url_strips_dashes() -> None:
    url = archive_index_url(891190, "0001193125-25-325143")
    assert url == "https://www.sec.gov/Archives/edgar/data/891190/000119312525325143/index.json"
    assert "-" not in url.split("/")[-1]


def test_archive_index_url_unpadded_cik() -> None:
    # CIK must NOT be zero-padded in archive URLs
    url = archive_index_url(891190, "0001193125-25-325143")
    assert "/edgar/data/891190/" in url


def test_archive_doc_url() -> None:
    url = archive_doc_url(891190, "0001193125-25-325143", "f43635d1.htm")
    assert url == (
        "https://www.sec.gov/Archives/edgar/data/891190/"
        "000119312525325143/f43635d1.htm"
    )


def test_series_browse_url_default_prefix() -> None:
    url = series_browse_url("S000002852")
    assert "CIK=S000002852" in url
    assert "type=485" in url
    assert "output=atom" in url
    assert url.startswith("https://www.sec.gov/cgi-bin/browse-edgar?")


def test_series_browse_url_custom_prefix() -> None:
    url = series_browse_url("S000002852", type_prefix="497")
    assert "type=497" in url


def test_fulltext_search_url_wraps_query_in_quotes() -> None:
    url = fulltext_search_url("VUSXX", "485BPOS,497K")
    assert "%22VUSXX%22" in url or '"VUSXX"' in url
    assert "forms=485BPOS%2C497K" in url or "forms=485BPOS,497K" in url
