"""Command-line entry point.

    python -m tipsxgs run                 # scrape today, build dashboard
    python -m tipsxgs run --date 2026-09-12
    python -m tipsxgs report --date 2026-09-11   # re-render from saved JSON, no scraping
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import click

from .calibration import compute_calibration, load_accumulated_calibration, match_games_to_results
from .config import load_config
from .markets import full_label
from .pipeline import run_daily
from .report import render_calibration_report, render_dashboard, render_index, render_real_report
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
    calibration_buckets = load_accumulated_calibration(cfg.data_dir, min_confidence=cfg.min_match_confidence)
    path = render_dashboard(
        day, games, cfg.reports_dir, value_bet_threshold=cfg.value_bet_threshold, has_real_report=True
    )
    real_path = render_real_report(
        day,
        games,
        calibration_buckets,
        cfg.reports_dir,
        min_probability=cfg.report_min_probability,
        high_probability_min=cfg.report_high_probability_min,
        high_odd_min=cfg.report_high_odd_min,
        high_odd_max=cfg.report_high_odd_max,
        mid_probability_min=cfg.report_real_mid_probability_min,
        mid_odd_min=cfg.report_real_mid_odd_min,
        mid_odd_max=cfg.report_real_mid_odd_max,
        min_value_ratio=cfg.report_min_value_ratio,
        multiple_stake=cfg.report_multiple_stake,
        mid_single_stake=cfg.report_mid_single_stake,
        multiple_leg_cap=cfg.report_real_multiple_leg_cap,
    )
    click.echo(f"Re-rendered {path} and {real_path}")


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

    day_dirs = sorted(p.parent.name for p in cfg.data_dir.glob("*/games.json"))
    days_with_games: list[date] = []
    for day_str in day_dirs:
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        if since and day < since:
            continue
        if load_day(day, cfg.data_dir):
            days_with_games.append(day)

    missing_days = [d for d in days_with_games if not load_results(d, cfg.data_dir)]
    if missing_days:
        click.echo(f"{len(missing_days)} day(s) missing results: {', '.join(d.isoformat() for d in missing_days)}")
    else:
        click.echo("No day is missing results -- nothing to scrape.")

    # Explicitly requested (2026-11-20): scrape ONCE (not once per
    # missing day, and no longer gated on "the missing day IS literally
    # yesterday") and sort whatever comes back into the right day(s) by
    # each result's OWN date, instead of blindly trusting that the page
    # was showing a particular day at all. This is what actually fixes
    # the real incident from the day before (results.json saved under
    # "yesterday" that, checked afterwards, weren't for that day at all
    # -- the page had drifted to showing "Today" instead, and nothing
    # here was checking) -- a mismatched scrape now just contributes
    # nothing (no day's date matches), rather than silently mislabeling
    # itself. It also means a "Week"-style view (several days' worth of
    # results in one response -- see config.yaml's xgscore.results.
    # click_selector) can backfill every missing day it covers in one
    # scrape, not just a single one.
    if scrape_results and missing_days:
        click.echo("Scraping xgscore.results for missing results...")
        scrapeable_day = datetime.now().date() - timedelta(days=1)
        try:
            scraped = scrape_xgscore_results(cfg, scrapeable_day)
        except RuntimeError as exc:
            click.echo(f"  {exc}", err=True)
            scraped = []
        results_by_date: dict[date, list] = {}
        for r in scraped:
            if r.kickoff is None:
                continue
            results_by_date.setdefault(r.kickoff.date(), []).append(r)
        if results_by_date:
            covered = ", ".join(f"{d.isoformat()} ({len(rs)})" for d, rs in sorted(results_by_date.items()))
            click.echo(f"  scraped {len(scraped)} result(s) total, covering: {covered}")
        else:
            click.echo(f"  scraped {len(scraped)} result(s) total, none with a usable kickoff date")
        saved_days = [day for day in missing_days if day in results_by_date]
        for day in saved_days:
            save_results(day, results_by_date[day], cfg.data_dir)
        still_missing = [day for day in missing_days if day not in results_by_date]
        if saved_days:
            click.echo(f"  filled in: {', '.join(d.isoformat() for d in saved_days)}")
        if still_missing:
            click.echo(f"  still missing (not covered by this scrape): {', '.join(d.isoformat() for d in still_missing)}")

    paired = []
    for day in days_with_games:
        games = load_day(day, cfg.data_dir)
        results = load_results(day, cfg.data_dir)
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
    click.echo("Por mercado + resultado + escalão de probabilidade prevista (mais confiante primeiro):")
    last_group = None
    for b in buckets:
        group = (b.market, b.outcome)
        if group != last_group:
            click.echo(f"\n{full_label(b.market, b.outcome)}:")
            last_group = group
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
