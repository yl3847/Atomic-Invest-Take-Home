"""Rich-formatted summary table and per-ticker result output."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from prospectus_fetcher.models import FetchResult, Status

_STATUS_STYLE: dict[Status, str] = {
    Status.OK: "green",
    Status.SKIPPED_EXISTING: "dim green",
    Status.TICKER_NOT_FOUND: "red",
    Status.NO_PROSPECTUS_FOUND: "red",
    Status.VALIDATION_FAILED: "yellow",
    Status.DOWNLOAD_ERROR: "red",
}


# TODO: implement render_summary(results, console) -> None
#   Print a Rich Table with columns:
#     Ticker | Status | Filing Date | Accession | File | SHA-256 (first 12) | Note
#   Color-code status using _STATUS_STYLE
#   Print a final count line: "X succeeded, Y failed, Z skipped"
def render_summary(results: list[FetchResult], console: Console | None = None) -> None:
    # TODO: implement
    con = console or Console()
    table = Table(title="Prospectus Fetch Summary")
    table.add_column("Ticker")
    table.add_column("Status")
    table.add_column("Note")
    for r in results:
        style = _STATUS_STYLE.get(r.status, "")
        table.add_row(r.ticker, r.status.value, r.error or "", style=style)
    con.print(table)
