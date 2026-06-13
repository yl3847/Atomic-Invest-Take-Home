"""Rich summary table, summary.json, and summary.csv."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from prospectus_fetcher.models import FetchResult, Status

log = logging.getLogger(__name__)

_STATUS_STYLE: dict[Status, str] = {
    Status.OK: "green",
    Status.SKIPPED_EXISTING: "dim green",
    Status.TICKER_NOT_FOUND: "red",
    Status.NO_PROSPECTUS_FOUND: "red",
    Status.VALIDATION_FAILED: "yellow",
    Status.DOWNLOAD_ERROR: "red",
}

_STATUS_GLYPH: dict[Status, str] = {
    Status.OK: "✓",
    Status.SKIPPED_EXISTING: "✓",
    Status.TICKER_NOT_FOUND: "✗",
    Status.NO_PROSPECTUS_FOUND: "✗",
    Status.VALIDATION_FAILED: "⚠",
    Status.DOWNLOAD_ERROR: "✗",
}

_CSV_FIELDS = [
    "ticker",
    "status",
    "form",
    "filing_date",
    "accession",
    "saved_path",
    "sha256",
    "validation_passed",
    "error",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_summary(results: list[FetchResult], console: Console | None = None) -> None:
    """Print the Rich summary table and count line to *console*."""
    con = console or Console()
    con.print(_build_table(results))
    con.print(_count_line(results))


def write_summary_files(results: list[FetchResult], output_dir: Path) -> None:
    """Write output/summary.json and output/summary.csv atomically."""
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(results, output_dir / "summary.json")
    _write_csv(results, output_dir / "summary.csv")


def results_to_json(results: list[FetchResult]) -> str:
    """Return a JSON string of the full result set (for --json stdout)."""
    return json.dumps([_result_to_dict(r) for r in results], indent=2, default=str)


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

def _build_table(results: list[FetchResult]) -> Table:
    table = Table(title="Prospectus Fetch Summary", show_lines=False)
    table.add_column("", width=2, no_wrap=True)          # glyph
    table.add_column("Ticker", style="bold", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Form", no_wrap=True)
    table.add_column("Filed", no_wrap=True)
    table.add_column("Saved To / Error")

    for r in results:
        style = _STATUS_STYLE.get(r.status, "")
        glyph = _STATUS_GLYPH.get(r.status, "?")
        filed = str(r.filing.filing_date) if r.filing else ""
        form = r.filing.form if r.filing else ""
        dest = r.saved_path or r.error or ""
        table.add_row(glyph, r.ticker, r.status.value, form, filed, dest, style=style)

    return table


def _count_line(results: list[FetchResult]) -> str:
    ok = sum(1 for r in results if r.status in (Status.OK, Status.SKIPPED_EXISTING))
    failed = sum(1 for r in results if r.status not in (
        Status.OK, Status.SKIPPED_EXISTING, Status.VALIDATION_FAILED
    ))
    warned = sum(1 for r in results if r.status == Status.VALIDATION_FAILED)
    skipped = sum(1 for r in results if r.status == Status.SKIPPED_EXISTING)
    parts = [f"[green]{ok} succeeded[/green]"]
    if skipped:
        parts.append(f"[dim]{skipped} skipped (already exists)[/dim]")
    if warned:
        parts.append(f"[yellow]{warned} validation warning(s)[/yellow]")
    if failed:
        parts.append(f"[red]{failed} failed[/red]")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# summary.json
# ---------------------------------------------------------------------------

def _write_json(results: list[FetchResult], path: Path) -> None:
    payload: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "succeeded": sum(1 for r in results if r.status in (Status.OK, Status.SKIPPED_EXISTING)),
        "failed": sum(1 for r in results if r.status not in (
            Status.OK, Status.SKIPPED_EXISTING
        )),
        "results": [_result_to_dict(r) for r in results],
    }
    _atomic_write_text(path, json.dumps(payload, indent=2, default=str))
    log.debug("Wrote %s", path)


def _result_to_dict(r: FetchResult) -> dict[str, Any]:
    d: dict[str, Any] = {
        "ticker": r.ticker,
        "status": r.status.value,
        "form": r.filing.form if r.filing else None,
        "filing_date": str(r.filing.filing_date) if r.filing else None,
        "accession": r.filing.accession if r.filing else None,
        "saved_path": r.saved_path,
        "sha256": r.sha256,
        "error": r.error,
    }
    if r.identity:
        d["cik"] = r.identity.cik
        d["series_id"] = r.identity.series_id
        d["class_id"] = r.identity.class_id
        d["source"] = r.identity.source
    if r.validation:
        d["validation"] = {
            "passed": r.validation.passed,
            "signals_found": r.validation.signals_found,
            "note": r.validation.note,
        }
    return d


# ---------------------------------------------------------------------------
# summary.csv
# ---------------------------------------------------------------------------

def _write_csv(results: list[FetchResult], path: Path) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for r in results:
        writer.writerow({
            "ticker": r.ticker,
            "status": r.status.value,   # verbatim enum value per spec
            "form": r.filing.form if r.filing else "",
            "filing_date": str(r.filing.filing_date) if r.filing else "",
            "accession": r.filing.accession if r.filing else "",
            "saved_path": r.saved_path or "",
            "sha256": r.sha256 or "",
            "validation_passed": (
                str(r.validation.passed) if r.validation is not None else ""
            ),
            "error": r.error or "",
        })
    _atomic_write_text(path, buf.getvalue())
    log.debug("Wrote %s", path)


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------

def _atomic_write_text(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".tmp_report_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, dest)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
