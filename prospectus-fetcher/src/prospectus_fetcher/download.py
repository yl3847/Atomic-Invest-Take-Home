"""Download a prospectus document and compute its SHA-256 hash.

URL construction (from RECON.md):
  https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_document}
  - cik:              UNPADDED integer (e.g. 891190, not 0000891190)
  - accession_no_dashes: strip dashes from accession (e.g. 000119312525325143)
  - primary_document: taken directly from Filing.primary_document
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from prospectus_fetcher.errors import DownloadError
from prospectus_fetcher.models import Filing, FundIdentity

_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


def _accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def prospectus_url(identity: FundIdentity, filing: Filing) -> str:
    if not filing.primary_document:
        raise DownloadError("", "Filing has no primary_document")
    acc = _accession_no_dashes(filing.accession)
    return f"{_EDGAR_ARCHIVES}/{identity.cik}/{acc}/{filing.primary_document}"


# TODO: implement save_prospectus(identity, filing, output_dir, session, force) -> tuple[str, str]
#   Returns (saved_path, sha256_hex)
#   1. Build output filename: {ticker}_{filing_date}_{accession_no_dashes}.htm
#   2. If file exists and not force: return (path, existing_sha256) without re-downloading
#      (caller sets status=SKIPPED_EXISTING)
#   3. Call edgar._get_bytes(url, session) with retry
#   4. Write bytes to output_dir / filename
#   5. Compute and return sha256 of the bytes
def save_prospectus(
    identity: FundIdentity,
    filing: Filing,
    output_dir: Path,
    force: bool = False,
) -> tuple[str, str]:
    # TODO: implement
    raise NotImplementedError
