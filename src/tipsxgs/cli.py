"""Command-line entry point.

    python -m tipsxgs run                 # scrape today, build dashboard
    python -m tipsxgs run --date 2026-09-12
    python -m tipsxgs report --date 2026-09-11   # re-render from saved JSON, no scraping
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import click

from .calibration import compute_calibration, match_games_to_results
from .config import load_config
from .pipeline import run_daily
from .report import render_calibration_report, render_dashboard, render_index
from .storage import load_day, load_results, save_results
from .xgscore.results import scrape_results as scrape_xgscore_results


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


@cli.command()
@click.option("--config", "config_path", default=None, help="Path to config.yaml (default: repo root)")
@click.option(
    "--since", "since_str", default=None, help="Only include days >= this date, YYYY-MM-DD (default: every saved day)"
)
@click.option(
    "--scrape-results/--no-scrape-results",
    default=True,
    help="Scrape a day's results from xGScore if data/<day>/results.json doesn't exist yet "
    "(requires xgscore.results to be calibrated -- see docs/CALIBRATION.md)",
)
@click.option("-v", "--verbose", is_flag=True, default=False)
def calibrate(config_path: str | None, since_str: str | None, scrape_results: bool, verbose: bool) -> None:
    """Compare past predictions (data/<day>/games.json) against actual
    results and report which markets/probability bands are well
    calibrated -- see docs/CALIBRATION.md's "xgscore.results" section."""
    _setup_logging(verbose)
    cfg = load_config(config_path)
    since = datetime.strptime(since_str, "%Y-%m-%d").date() if since_str else None
    # xgscore.results' real page has no way to request a specific past
    # date (see config.yaml's comment on it) -- its default view only
    # ever covers *yesterday*, relative to whenever the scrape actually
    # runs. So a day missing results.json only gets scraped when it IS
    # yesterday; any other missing day is simply skipped (no results
    # available for it until this project gains a way to request an
    # older date).
    scrapeable_day = datetime.now().date() - timedelta(days=1)

    day_dirs = sorted(p.parent.name for p in cfg.data_dir.glob("*/games.json"))
    paired = []
    for day_str in day_dirs:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        if since and day < since:
            continue
        games = load_day(day, cfg.data_dir)
        if not games:
            continue

        results = load_results(day, cfg.data_dir)
        if not results and scrape_results and day == scrapeable_day:
            try:
                results = scrape_xgscore_results(cfg, day)
            except RuntimeError as exc:
                click.echo(f"  {day_str}: {exc}", err=True)
                continue
            if results:
                save_results(day, results, cfg.data_dir)
        if not results:
            continue

        paired.extend(match_games_to_results(games, results, min_confidence=cfg.min_match_confidence))

    if not paired:
        raise click.ClickException(
            "No (prediction, actual result) pair found yet -- either there's no saved "
            f"{cfg.data_dir}/<day>/games.json, or xgscore.results isn't calibrated yet "
            "(see docs/CALIBRATION.md)."
        )

    buckets = compute_calibration(paired)

    click.echo(f"{len(paired)} finished game(s) matched to an actual result.\n")
    click.echo("Por mercado + escalão de probabilidade prevista (mais confiante primeiro):")
    last_family = None
    for b in buckets:
        if b.market_family != last_family:
            click.echo(f"\n{b.market_family}:")
            last_family = b.market_family
        click.echo(
            f"  {b.probability_bucket:<8} {b.hits}/{b.count}"
            f" ({b.actual_hit_rate * 100:.0f}% real vs {b.avg_predicted_probability * 100:.0f}% previsto)"
        )

    # Also render the same breakdown as a page under cfg.reports_dir, so
    # it's reachable from a browser (linked from every day's dashboard
    # and the landing page) -- not just this command's text output.
    html_path = render_calibration_report(buckets, len(paired), cfg.reports_dir)
    render_index(cfg.reports_dir)
    click.echo(f"\nRelatório HTML: {html_path}")


if __name__ == "__main__":
    cli()
