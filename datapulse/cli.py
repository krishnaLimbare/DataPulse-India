"""`datapulse` command line entry point."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from datapulse.core.config import REPO_ROOT, load_settings
from datapulse.core.logging import setup_logging
from datapulse.core.runner import run as run_pipeline
from datapulse.core.source import registry
from datapulse.core.summary import write_summary

app = typer.Typer(help="DataPulse-India — multi-dataset daily data hub.", no_args_is_help=True)
console = Console()


@app.command("list")
def list_sources(config: Path = typer.Option(None, "--config", "-c")) -> None:
    """Show every registered source and whether it is enabled."""
    settings = load_settings(config)
    table = Table("source", "domain", "enabled", "schedule")
    for name, cls in sorted(registry().items()):
        cfg = settings.sources.get(name)
        table.add_row(
            name,
            cls.domain,
            "yes" if cfg and cfg.enabled else "no",
            cfg.schedule if cfg else "-",
        )
    console.print(table)


@app.command()
def run(
    source: list[str] = typer.Option(None, "--source", "-s", help="Run only these sources."),
    domain: list[str] = typer.Option(None, "--domain", "-d", help="Run only these domains."),
    run_date: str = typer.Option(None, "--date", help="YYYY-MM-DD; defaults to today (UTC)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Collect and validate, write nothing."),
    config: Path = typer.Option(None, "--config", "-c"),
    report: Path = typer.Option(None, "--report", help="Write a JSON run report here."),
    fail_fast: bool = typer.Option(
        True, "--fail-fast/--no-fail-fast", help="Exit non-zero if any source failed."
    ),
) -> None:
    """Collect one or more datasets."""
    settings = load_settings(config)
    settings.dry_run = dry_run or settings.dry_run
    setup_logging(settings.log_level)

    parsed_date = date.fromisoformat(run_date) if run_date else None
    result = run_pipeline(
        settings, run_date=parsed_date, only=source or None, domains=domain or None
    )
    result.write(report or REPO_ROOT / "datasets" / "_runs" / f"{result.run_date}.json")

    table = Table("source", "status", "rows", "seconds", "error")
    for r in result.results:
        table.add_row(r.name, r.status, str(r.rows), str(r.duration_seconds), r.error or "")
    console.print(table)

    if fail_fast and result.failed:
        raise typer.Exit(code=1)


@app.command()
def summarize(
    config: Path = typer.Option(None, "--config", "-c"),
    out: Path = typer.Option(None, "--out", help="Defaults to dashboard/data/summary.json."),
) -> None:
    """Pre-aggregate the archive into the JSON the dashboard reads."""
    settings = load_settings(config)
    setup_logging(settings.log_level)
    written = write_summary(settings, out or REPO_ROOT / "dashboard" / "data" / "summary.json")
    console.print(f"[green]wrote[/] {written}")


@app.command()
def validate(config: Path = typer.Option(None, "--config", "-c")) -> None:
    """Check that config and registered sources line up. Cheap CI guard."""
    settings = load_settings(config)
    known = set(registry())
    unknown = set(settings.sources) - known
    unconfigured = known - set(settings.sources)
    for name in sorted(unknown):
        console.print(f"[yellow]config block for unknown source:[/] {name}")
    for name in sorted(unconfigured):
        console.print(f"[yellow]registered source without config:[/] {name}")
    if unknown or unconfigured:
        raise typer.Exit(code=1)
    console.print(f"[green]ok[/] — {len(known)} sources configured")


if __name__ == "__main__":
    app()
