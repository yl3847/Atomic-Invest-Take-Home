"""Entry point for the prospectus-fetch CLI command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(
    name="prospectus-fetch",
    help="Retrieve the latest SEC fund prospectus for one or more tickers.",
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)


# TODO: implement fetch command
#   1. Accept one or more tickers as arguments
#   2. Accept --output-dir (default: ./output), --force (re-download if exists),
#      --user-agent (override), --log-level
#   3. For each ticker call orchestrate(ticker, ...) from resolver.py
#   4. Collect FetchResult list and pass to report.render_summary()
#   5. Exit with code 1 if any result has status != OK and != SKIPPED_EXISTING
@app.command()
def fetch(
    tickers: Annotated[list[str], typer.Argument(help="One or more fund tickers")],
    output_dir: Annotated[Path, typer.Option("--output-dir", "-o")] = Path("output"),
    force: Annotated[bool, typer.Option("--force", "-f")] = False,
    user_agent: Annotated[str | None, typer.Option("--user-agent")] = None,
    log_level: Annotated[str, typer.Option("--log-level")] = "INFO",
) -> None:
    """Fetch the latest prospectus for each TICKER and save to OUTPUT_DIR."""
    # TODO: implement
    err_console.print("[yellow]Not yet implemented[/yellow]")
    raise typer.Exit(code=1)
