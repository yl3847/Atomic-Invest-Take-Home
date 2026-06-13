"""Entry point for the prospectus-fetch CLI command."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from prospectus_fetcher.download import (
    build_manifest_entry,
    save_document,
    upsert_manifest,
)
from prospectus_fetcher.edgar import EdgarClient
from prospectus_fetcher.errors import (
    DownloadError,
    NoProspectusFound,
    ProspectusFetcherError,
    TickerNotFound,
)
from prospectus_fetcher.filings import DEFAULT_FORMS, locate_document, select_filing
from prospectus_fetcher.models import FetchResult, FundIdentity, Status
from prospectus_fetcher.report import render_summary
from prospectus_fetcher.resolver import resolve

app = typer.Typer(
    name="prospectus-fetch",
    help="Retrieve the latest SEC fund prospectus for one or more tickers.",
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def fetch(
    tickers: Annotated[list[str], typer.Argument(help="One or more fund tickers")],
    out: Annotated[Path, typer.Option("--out", "-o", help="Output directory")] = Path("output"),
    forms: Annotated[
        str,
        typer.Option("--forms", help="Comma-separated form priority (e.g. 485BPOS,497K)"),
    ] = ",".join(DEFAULT_FORMS),
    force: Annotated[bool, typer.Option("--force", "-f", help="Re-download if already exists")] = False,
    user_agent: Annotated[
        str | None,
        typer.Option("--user-agent", help='SEC User-Agent header: "Name email@example.com"'),
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable DEBUG logging")] = False,
) -> None:
    """Fetch the latest prospectus for each TICKER and save to OUT."""
    _configure_logging(verbose)

    ua = user_agent or os.environ.get("SEC_USER_AGENT") or os.environ.get("EDGAR_UA")
    if not ua:
        err_console.print(
            "[red]Error:[/red] SEC requires a User-Agent header identifying you.\n"
            "Supply it via [bold]--user-agent 'Name email@example.com'[/bold] "
            "or set the [bold]SEC_USER_AGENT[/bold] environment variable."
        )
        raise typer.Exit(code=2)

    forms_priority = [f.strip() for f in forms.split(",") if f.strip()]
    client = EdgarClient(user_agent=ua)
    out.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    for raw_ticker in tickers:
        result = _process_ticker(raw_ticker, client, forms_priority, out, force)
        results.append(result)
        _print_result_line(result)

    render_summary(results, console)

    failed = [r for r in results if r.status not in (Status.OK, Status.SKIPPED_EXISTING)]
    if failed:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Per-ticker orchestration
# ---------------------------------------------------------------------------

def _process_ticker(
    raw_ticker: str,
    client: EdgarClient,
    forms_priority: list[str],
    out: Path,
    force: bool,
) -> FetchResult:
    ticker = raw_ticker.strip().upper()
    log = logging.getLogger(__name__)

    # 1. Resolve ticker → FundIdentity
    try:
        identity = resolve(ticker, client)
    except TickerNotFound as exc:
        log.warning("Ticker not found: %s", exc)
        return FetchResult(
            ticker=ticker,
            status=Status.TICKER_NOT_FOUND,
            error=str(exc),
        )
    except ProspectusFetcherError as exc:
        return FetchResult(ticker=ticker, status=Status.TICKER_NOT_FOUND, error=str(exc))

    # 2. Select best filing
    try:
        filing = select_filing(identity, client, forms_priority)
    except NoProspectusFound as exc:
        log.warning("No prospectus found: %s", exc)
        return FetchResult(
            ticker=ticker,
            status=Status.NO_PROSPECTUS_FOUND,
            identity=identity,
            error=str(exc),
        )

    # 3. Locate the document URL
    try:
        source_url = locate_document(filing, identity, client)
    except (DownloadError, ProspectusFetcherError) as exc:
        return FetchResult(
            ticker=ticker,
            status=Status.DOWNLOAD_ERROR,
            identity=identity,
            filing=filing,
            error=str(exc),
        )

    # 4. Download and save
    try:
        saved_path, sha256, status = save_document(
            identity, filing, source_url, client, out, force=force
        )
    except DownloadError as exc:
        return FetchResult(
            ticker=ticker,
            status=Status.DOWNLOAD_ERROR,
            identity=identity,
            filing=filing,
            error=str(exc),
        )

    # 5. Upsert manifest
    entry = build_manifest_entry(identity, filing, saved_path, sha256, source_url)
    try:
        upsert_manifest(out, entry)
    except OSError as exc:
        log.warning("Manifest write failed: %s", exc)

    return FetchResult(
        ticker=ticker,
        status=status,
        identity=identity,
        filing=filing,
        saved_path=saved_path,
        sha256=sha256,
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_result_line(result: FetchResult) -> None:
    status_styles = {
        Status.OK: "[green]OK[/green]",
        Status.SKIPPED_EXISTING: "[dim green]SKIPPED[/dim green]",
        Status.TICKER_NOT_FOUND: "[red]NOT FOUND[/red]",
        Status.NO_PROSPECTUS_FOUND: "[red]NO PROSPECTUS[/red]",
        Status.DOWNLOAD_ERROR: "[red]DOWNLOAD ERROR[/red]",
        Status.VALIDATION_FAILED: "[yellow]VALIDATION FAILED[/yellow]",
    }
    styled = status_styles.get(result.status, result.status.value)

    if result.status in (Status.OK, Status.SKIPPED_EXISTING):
        console.print(
            f"{result.ticker:<12} {styled}  "
            f"{result.filing.filing_date if result.filing else ''}  "
            f"{result.filing.form if result.filing else ''}  "
            f"{result.saved_path or ''}"
        )
    else:
        console.print(f"{result.ticker:<12} {styled}  {result.error or ''}")


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        stream=sys.stderr,
    )
