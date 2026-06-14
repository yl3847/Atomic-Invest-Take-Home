"""Download a prospectus document and maintain the manifest.

File layout
-----------
  output/{TICKER}/{filing_date}_{form}_{accession_no_dashes}/prospectus.htm

Atomic write
------------
Bytes are streamed to a .tmp sibling in the same directory, sha256 computed
during streaming, then os.replace() to the final name. This prevents a partial
file from being mistaken for a complete one if the process is interrupted.

Manifest
--------
output/manifest.json is a JSON array of entries, upserted by accession on
each successful save and written atomically (temp-file + os.replace()).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prospectus_fetcher.edgar import EdgarClient
from prospectus_fetcher.errors import DownloadError
from prospectus_fetcher.models import Filing, FundIdentity, Status, ValidationResult

log = logging.getLogger(__name__)

_MANIFEST_NAME = "manifest.json"
_DOC_NAME = "prospectus.htm"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_document(
    identity: FundIdentity,
    filing: Filing,
    source_url: str,
    client: EdgarClient,
    output_dir: Path,
    force: bool = False,
) -> tuple[str, str, Status]:
    """Download the prospectus and return (saved_path, sha256, status).

    Status is SKIPPED_EXISTING when the file is already present and force=False.
    """
    dest_dir = _filing_dir(output_dir, identity.ticker, filing)
    dest_file = dest_dir / _DOC_NAME

    if dest_file.exists() and not force:
        log.info("Skipping existing file: %s", dest_file)
        sha = _sha256_file(dest_file)
        return str(dest_file), sha, Status.SKIPPED_EXISTING

    dest_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %s → %s", source_url, dest_file)

    try:
        raw = client.get_bytes(source_url)
    except Exception as exc:
        raise DownloadError(source_url, str(exc)) from exc

    sha = hashlib.sha256(raw).hexdigest()
    _atomic_write(dest_file, raw)

    log.info("Saved %d bytes, sha256=%s…", len(raw), sha[:12])
    return str(dest_file), sha, Status.OK


def upsert_manifest(
    output_dir: Path,
    entry: dict[str, Any],
) -> None:
    """Upsert *entry* into manifest.json, keyed by accession. Atomic write."""
    manifest_path = output_dir / _MANIFEST_NAME
    entries: list[dict[str, Any]] = []

    if manifest_path.exists():
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Could not read existing manifest; starting fresh")
            entries = []

    # Upsert: replace existing entry with same accession, else append
    accession = entry.get("accession", "")
    entries = [e for e in entries if e.get("accession") != accession]
    entries.append(entry)

    _atomic_write_text(manifest_path, json.dumps(entries, indent=2, default=str))
    log.debug("Manifest updated: %s entries", len(entries))


def build_manifest_entry(
    identity: FundIdentity,
    filing: Filing,
    saved_path: str,
    sha256: str,
    source_url: str,
    validation: ValidationResult | None = None,
    extraction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "ticker": identity.ticker,
        "fund_name": identity.name,
        "cik": identity.cik,
        "series_id": identity.series_id,
        "class_id": identity.class_id,
        "form": filing.form,
        "filing_date": str(filing.filing_date),
        "accession": filing.accession,
        "source": identity.source,
        "source_url": source_url,
        "saved_path": saved_path,
        "sha256": sha256,
        "selection_reason": filing.selection_reason,
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    if validation is not None:
        entry["validation"] = {
            "passed": validation.passed,
            "signals_found": validation.signals_found,
            "note": validation.note,
        }
    if extraction is not None:
        entry["extraction"] = extraction
    return entry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filing_dir(output_dir: Path, ticker: str, filing: Filing) -> Path:
    acc_nodash = filing.accession.replace("-", "")
    folder = f"{filing.filing_date}_{filing.form}_{acc_nodash}"
    return output_dir / ticker / folder


def _atomic_write(dest: Path, data: bytes) -> None:
    fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_path, dest)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _atomic_write_text(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=dest.parent, prefix=".tmp_manifest_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp_path, dest)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
