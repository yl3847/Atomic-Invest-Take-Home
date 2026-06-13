from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Status(str, Enum):
    OK = "OK"
    TICKER_NOT_FOUND = "TICKER_NOT_FOUND"
    NO_PROSPECTUS_FOUND = "NO_PROSPECTUS_FOUND"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    DOWNLOAD_ERROR = "DOWNLOAD_ERROR"
    SKIPPED_EXISTING = "SKIPPED_EXISTING"


@dataclass
class FundIdentity:
    ticker: str
    cik: int
    series_id: str | None
    class_id: str | None
    name: str
    # One of: "mf_map", "company_map", "full_text_search"
    source: str


@dataclass
class Filing:
    form: str
    filing_date: date
    accession: str
    primary_document: str | None
    series_scoped: bool
    selection_reason: str


@dataclass
class ValidationResult:
    passed: bool
    signals_found: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class FetchResult:
    ticker: str
    status: Status
    identity: FundIdentity | None = None
    filing: Filing | None = None
    saved_path: str | None = None
    sha256: str | None = None
    validation: ValidationResult | None = None
    error: str | None = None
