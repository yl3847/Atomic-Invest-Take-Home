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
from prospectus_fetcher.models import FetchResult, Status
from prospectus_fetcher.report import render_summary, results_to_json, write_summary_files
from prospectus_fetcher.resolver import resolve
from prospectus_fetcher.validate import validate_document

app = typer.Typer(
    name="prospectus-fetch",
    help="Retrieve the latest SEC fund prospectus for one or more tickers.",
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


@app.command()
def fetch(
    tickers: Annotated[
        list[str] | None,
        typer.Argument(help="One or more fund tickers"),
    ] = None,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output directory"),
    ] = Path("output"),
    forms: Annotated[
        str,
        typer.Option("--forms", help="Comma-separated form priority (e.g. 485BPOS,497K)"),
    ] = ",".join(DEFAULT_FORMS),
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-download even if file already exists"),
    ] = False,
    user_agent: Annotated[
        str | None,
        typer.Option("--user-agent", help='SEC User-Agent: "Name email@example.com"'),
    ] = None,
    from_file: Annotated[
        Path | None,
        typer.Option("--from-file", help="Text file with one ticker per line"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging"),
    ] = False,
    print_json: Annotated[
        bool,
        typer.Option("--json", help="Print structured JSON results to stdout"),
    ] = False,
) -> None:
    """Fetch the latest prospectus for each TICKER and save to OUT.

    Tickers may be supplied as positional arguments, via --from-file, or both.
    Duplicates are silently de-duplicated. A failure on one ticker never aborts
    the rest of the batch.
    """
    _configure_logging(verbose)

    ua = user_agent or os.environ.get("SEC_USER_AGENT") or os.environ.get("EDGAR_UA")
    if not ua:
        err_console.print(
            "[red]Error:[/red] SEC requires a User-Agent header identifying you.\n"
            "Supply it via [bold]--user-agent 'Name email@example.com'[/bold] "
            "or set the [bold]SEC_USER_AGENT[/bold] environment variable."
        )
        raise typer.Exit(code=2)

    raw_tickers: list[str] = list(tickers or [])
    if from_file is not None:
        raw_tickers.extend(_read_ticker_file(from_file))

    if not raw_tickers:
        err_console.print("[red]Error:[/red] No tickers supplied. Pass tickers as arguments or use --from-file.")
        raise typer.Exit(code=2)

    # Normalize (strip + uppercase) and de-duplicate while preserving order
    seen: set[str] = set()
    normalized: list[str] = []
    for t in raw_tickers:
        clean = t.strip().upper()
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)

    forms_priority = [f.strip() for f in forms.split(",") if f.strip()]
    client = EdgarClient(user_agent=ua)
    out.mkdir(parents=True, exist_ok=True)

    results: list[FetchResult] = []
    for ticker in normalized:
        result = _process_ticker(ticker, client, forms_priority, out, force)
        results.append(result)
        _print_result_line(result)

    # Summary table + counts to stdout
    if not print_json:
        render_summary(results, console)

    # Machine-readable summaries
    write_summary_files(results, out)

    # JSON to stdout (instead of / in addition to table per --json flag)
    if print_json:
        print(results_to_json(results))

    # CI-friendly exit: non-zero if any ticker failed (VALIDATION_FAILED counts
    # as a warning but not a failure for exit-code purposes)
    failures = [
        r for r in results
        if r.status not in (Status.OK, Status.SKIPPED_EXISTING, Status.VALIDATION_FAILED)
    ]
    if failures:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Per-ticker orchestration — each step catches its own error class so a
# failure on one ticker never propagates to the next.
# ---------------------------------------------------------------------------

def _process_ticker(
    ticker: str,
    client: EdgarClient,
    forms_priority: list[str],
    out: Path,
    force: bool,
) -> FetchResult:
    log = logging.getLogger(__name__)

    # 1. Resolve ticker → FundIdentity
    try:
        identity = resolve(ticker, client)
    except TickerNotFound as exc:
        log.warning("Ticker not found: %s", exc)
        return FetchResult(ticker=ticker, status=Status.TICKER_NOT_FOUND, error=str(exc))
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

    # 3. Locate document URL
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

    # 5. Validate (sanity check — never aborts; demotes status on failure)
    validation = validate_document(saved_path, identity)
    if not validation.passed:
        log.warning("Validation failed for %s: %s", ticker, validation.note)
        status = Status.VALIDATION_FAILED

    # 6. Upsert per-ticker manifest entry
    entry = build_manifest_entry(
        identity, filing, saved_path, sha256, source_url, validation=validation
    )
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
        validation=validation,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_ticker_file(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        err_console.print(f"[red]Cannot read --from-file {path}: {exc}[/red]")
        raise typer.Exit(code=2) from exc
    # Skip blank lines and comments (#)
    return [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]


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

    if result.status in (Status.OK, Status.SKIPPED_EXISTING, Status.VALIDATION_FAILED):
        val_note = ""
        if result.validation and not result.validation.passed:
            val_note = f"  [yellow]⚠ {result.validation.note}[/yellow]"
        console.print(
            f"{result.ticker:<12} {styled}  "
            f"{result.filing.filing_date if result.filing else ''}  "
            f"{result.filing.form if result.filing else ''}  "
            f"{result.saved_path or ''}"
            f"{val_note}"
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
