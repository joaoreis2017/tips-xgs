"""Orchestrates one full daily run: scrape -> match -> compute -> store -> report."""

from __future__ import annotations

import logging
from datetime import date, datetime

from .betclic.odds import scrape_today_odds
from .config import AppConfig
from .matching import match_fixtures_to_odds
from .models import MatchedGame
from .report import render_dashboard, render_index
from .storage import save_day
from .valuebets import compute_all
from .xgscore.fixtures import filter_today, scrape_today_fixtures
from .xgscore.preview import scrape_previews

logger = logging.getLogger(__name__)


def run_daily(cfg: AppConfig, day: date | None = None) -> list[MatchedGame]:
    """Run the whole pipeline for ``day`` (default: today) and write both
    the JSON snapshot and the HTML dashboard to ``cfg.data_dir``.

    Returns the list of :class:`MatchedGame` produced, for callers (tests,
    the CLI) that want to inspect the result directly.
    """
    today = day or datetime.now().date()
    logger.info("=== tipsxgs daily run for %s ===", today)

    logger.info("Scraping xGScore fixtures...")
    fixtures = scrape_today_fixtures(cfg)
    fixtures = filter_today(fixtures, datetime.combine(today, datetime.min.time()))
    logger.info("Found %d fixtures for today", len(fixtures))

    logger.info("Scraping xGScore previews (probabilities) for each fixture...")
    predictions = scrape_previews(cfg, fixtures)
    logger.info("Scraped %d/%d previews successfully", len(predictions), len(fixtures))

    logger.info("Scraping Betclic odds...")
    odds_offers = scrape_today_odds(cfg)
    logger.info("Found %d Betclic odds offers", len(odds_offers))

    logger.info("Matching fixtures to odds offers...")
    games = match_fixtures_to_odds(
        fixtures, predictions, odds_offers, min_confidence=cfg.min_match_confidence
    )
    matched = sum(1 for g in games if g.odds is not None)
    logger.info("Matched %d/%d fixtures to a Betclic offer", matched, len(games))

    logger.info("Computing value bets...")
    compute_all(games, value_bet_threshold=cfg.value_bet_threshold)

    logger.info("Saving results...")
    json_path = save_day(today, games, cfg.data_dir)
    logger.info("Saved %s", json_path)

    logger.info("Rendering dashboard...")
    html_path = render_dashboard(today, games, cfg.reports_dir, value_bet_threshold=cfg.value_bet_threshold)
    render_index(cfg.reports_dir)
    logger.info("Rendered %s", html_path)

    return games
