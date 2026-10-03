"""Command-line entry point.

    python -m tipsxgs run                 # scrape today, build dashboard
    python -m tipsxgs run --date 2026-09-12
    python -m tipsxgs report --date 2026-09-11   # re-render from saved JSON, no scraping
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import click

from .config import load_config
from .pipeline import run_daily
from .report import render_dashboard
from .storage import load_day


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


@click.group()
def cli() -> None:
    """tipsxgs: xGScore predictions + Betclic odds -> value bet dashboard."""


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to config.yaml (default: repo root)")
@click.option("--date", "date_str", default=None, help="Day to run for, YYYY-MM-DD (default: today)")
@click.option("-v", "--verbose", is_flag=True, default=False)
def run(config_path: str | None, date_str: str | None, verbose: bool) -> None:
    """Scrape xGScore + Betclic and build today's (or DATE's) dashboard."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    day = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else date.today()
    games = run_daily(cfg, day)
    click.echo(f"Done. {len(games)} game(s) processed for {day.isoformat()}.")
    click.echo(f"Dashboard: {cfg.reports_dir / day.isoformat() / 'index.html'}")


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to config.yaml (default: repo root)")
@click.option("--date", "date_str", required=True, help="Day to re-render, YYYY-MM-DD")
def report(config_path: str | None, date_str: str) -> None:
    """Re-render the HTML dashboard for DATE from the already-saved JSON
    (no scraping) -- handy after tweaking the template."""
    cfg = load_config(config_path)
    day = datetime.strptime(date_str, "%Y-%m-%d").date()
    games = load_day(day, cfg.data_dir)
    if not games:
        raise click.ClickException(f"No saved data found for {day.isoformat()} in {cfg.data_dir}")
    path = render_dashboard(day, games, cfg.reports_dir, value_bet_threshold=cfg.value_bet_threshold)
    click.echo(f"Re-rendered {path}")


if __name__ == "__main__":
    cli()
