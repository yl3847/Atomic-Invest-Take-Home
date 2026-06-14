"""Entry point for the prospectus-fetch CLI command."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

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


# ---------------------------------------------------------------------------
# fetch command
# ---------------------------------------------------------------------------

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
    do_extract: Annotated[
        bool,
        typer.Option(
            "--extract",
            help=(
                "After download, run LLM extraction to emit structured JSON "
                "(investment_objective, expense_ratio, minimum_investment, principal_risks). "
                "Requires ANTHROPIC_API_KEY env var and 'pip install prospectus-fetcher[extract]'. "
                "No-op with a clear message if the key is absent; retrieval always runs."
            ),
        ),
    ] = False,
) -> None:
    """Fetch the latest prospectus for each TICKER and save to OUT.

    Tickers may be supplied as positional arguments, via --from-file, or both.
    Duplicates are silently de-duplicated. A failure on one ticker never aborts
    the rest of the batch.
    """
    _configure_logging(verbose)

    ua = _require_ua(user_agent)
    normalized = _normalize_tickers(list(tickers or []), from_file)
    forms_priority = [f.strip() for f in forms.split(",") if f.strip()]

    client = EdgarClient(user_agent=ua)
    out.mkdir(parents=True, exist_ok=True)

    # Accession-level dedup cache: accession → (saved_path, sha256)
    # Populated on first download; subsequent tickers with the same accession
    # reuse the path instead of re-fetching the (often multi-MB) document.
    accession_cache: dict[str, tuple[str, str]] = {}

    results: list[FetchResult] = []
    for ticker in normalized:
        result = _process_ticker(
            ticker, client, forms_priority, out, force, accession_cache,
            run_extract=do_extract,
        )
        results.append(result)
        _print_result_line(result)

    if not print_json:
        render_summary(results, console)

    write_summary_files(results, out)

    if print_json:
        print(results_to_json(results))

    failures = [
        r for r in results
        if r.status not in (Status.OK, Status.SKIPPED_EXISTING, Status.VALIDATION_FAILED)
    ]
    if failures:
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# inspect subcommand
# ---------------------------------------------------------------------------

@app.command()
def inspect(
    tickers: Annotated[list[str], typer.Argument(help="Tickers to inspect")],
    forms: Annotated[
        str,
        typer.Option("--forms", help="Comma-separated form priority"),
    ] = ",".join(DEFAULT_FORMS),
    user_agent: Annotated[
        str | None,
        typer.Option("--user-agent", help='SEC User-Agent: "Name email@example.com"'),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable DEBUG logging"),
    ] = False,
) -> None:
    """Dry-run: resolve and select a filing but do NOT download.

    Prints resolved CIK, series/class IDs, resolution source, chosen form,
    filing date, accession, selection reason, and the document URL that would
    be fetched.
    """
    _configure_logging(verbose)
    ua = _require_ua(user_agent)
    normalized = _normalize_tickers(list(tickers), from_file=None)
    forms_priority = [f.strip() for f in forms.split(",") if f.strip()]
    client = EdgarClient(user_agent=ua)

    table = Table(title="Inspect (dry-run — no download)", show_lines=True)
    table.add_column("Ticker", style="bold", no_wrap=True)
    table.add_column("CIK", no_wrap=True)
    table.add_column("Series ID", no_wrap=True)
    table.add_column("Class ID", no_wrap=True)
    table.add_column("Source", no_wrap=True)
    table.add_column("Form", no_wrap=True)
    table.add_column("Filed", no_wrap=True)
    table.add_column("Accession", no_wrap=True)
    table.add_column("Selection Reason")
    table.add_column("Document URL")

    for ticker in normalized:
        try:
            identity = resolve(ticker, client)
        except TickerNotFound as exc:
            table.add_row(ticker, "—", "—", "—", "—", "—", "—", "—", str(exc), "—", style="red")
            continue
        except ProspectusFetcherError as exc:
            table.add_row(ticker, "—", "—", "—", "—", "—", "—", "—", str(exc), "—", style="red")
            continue

        try:
            filing = select_filing(identity, client, forms_priority)
        except NoProspectusFound as exc:
            table.add_row(
                ticker, str(identity.cik),
                identity.series_id or "—", identity.class_id or "—",
                identity.source, "—", "—", "—", str(exc), "—", style="yellow",
            )
            continue

        try:
            doc_url = locate_document(filing, identity, client)
        except (DownloadError, ProspectusFetcherError) as exc:
            doc_url = f"[error: {exc}]"

        table.add_row(
            ticker,
            str(identity.cik),
            identity.series_id or "—",
            identity.class_id or "—",
            identity.source,
            filing.form,
            str(filing.filing_date),
            filing.accession,
            filing.selection_reason,
            doc_url,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# Per-ticker orchestration
# ---------------------------------------------------------------------------

def _process_ticker(
    ticker: str,
    client: EdgarClient,
    forms_priority: list[str],
    out: Path,
    force: bool,
    accession_cache: dict[str, tuple[str, str]],
    *,
    run_extract: bool = False,
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
        log.warning("No prospectus: %s", exc)
        return FetchResult(
            ticker=ticker, status=Status.NO_PROSPECTUS_FOUND,
            identity=identity, error=str(exc),
        )

    # 3. Locate document URL
    try:
        source_url = locate_document(filing, identity, client)
    except (DownloadError, ProspectusFetcherError) as exc:
        return FetchResult(
            ticker=ticker, status=Status.DOWNLOAD_ERROR,
            identity=identity, filing=filing, error=str(exc),
        )

    # 4. Accession-level dedup: if another ticker in this run already downloaded
    #    the exact same accession, reuse the saved bytes instead of re-fetching.
    #    We still write a separate manifest entry per ticker.
    if filing.accession in accession_cache and not force:
        saved_path, sha256 = accession_cache[filing.accession]
        status = Status.SKIPPED_EXISTING
        log.info(
            "Accession %s already downloaded this run; reusing %s for %s",
            filing.accession, saved_path, ticker,
        )
    else:
        # 4b. Download
        try:
            saved_path, sha256, status = save_document(
                identity, filing, source_url, client, out, force=force
            )
        except DownloadError as exc:
            return FetchResult(
                ticker=ticker, status=Status.DOWNLOAD_ERROR,
                identity=identity, filing=filing, error=str(exc),
            )
        accession_cache[filing.accession] = (saved_path, sha256)

    # 5. Validate
    validation = validate_document(saved_path, identity)
    if not validation.passed and status == Status.OK:
        log.warning("Validation failed for %s: %s", ticker, validation.note)
        status = Status.VALIDATION_FAILED

    # 6. Optional LLM enrichment — runs only when --extract is set and
    #    ANTHROPIC_API_KEY is present; otherwise returns None silently.
    extraction: dict[str, object] | None = None
    if run_extract:
        from prospectus_fetcher.extract import extract as run_extraction
        extraction = run_extraction(saved_path, ticker)
        if extraction is not None:
            log.info("Extraction complete for %s", ticker)

    # 7. Manifest
    entry = build_manifest_entry(
        identity, filing, saved_path, sha256, source_url,
        validation=validation, extraction=extraction,
    )
    try:
        upsert_manifest(out, entry)
    except OSError as exc:
        log.warning("Manifest write failed: %s", exc)

    return FetchResult(
        ticker=ticker, status=status, identity=identity,
        filing=filing, saved_path=saved_path, sha256=sha256, validation=validation,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _require_ua(user_agent: str | None) -> str:
    ua = user_agent or os.environ.get("SEC_USER_AGENT") or os.environ.get("EDGAR_UA")
    if not ua:
        err_console.print(
            "[red]Error:[/red] SEC requires a User-Agent header identifying you.\n"
            "Supply it via [bold]--user-agent 'Name email@example.com'[/bold] "
            "or set the [bold]SEC_USER_AGENT[/bold] environment variable."
        )
        raise typer.Exit(code=2)
    return ua


def _normalize_tickers(
    raw: list[str],
    from_file: Path | None,
) -> list[str]:
    """Strip, uppercase, de-duplicate (preserving order), skip blanks/comments."""
    combined = list(raw)
    if from_file is not None:
        combined.extend(_read_ticker_file(from_file))
    if not combined:
        err_console.print(
            "[red]Error:[/red] No tickers supplied. "
            "Pass tickers as arguments or use --from-file."
        )
        raise typer.Exit(code=2)
    seen: set[str] = set()
    out: list[str] = []
    for t in combined:
        clean = t.strip().upper()
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _read_ticker_file(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        err_console.print(f"[red]Cannot read --from-file {path}: {exc}[/red]")
        raise typer.Exit(code=2) from exc
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


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
            f"{result.saved_path or ''}{val_note}"
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
