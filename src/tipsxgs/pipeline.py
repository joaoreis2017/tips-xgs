"""Orchestrates one full daily run: scrape -> match -> compute -> store -> report."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from .betclic.odds import scrape_today_odds
from .config import AppConfig
from .markets import market_family
from .matching import match_fixtures_to_odds
from .models import MatchedGame
from .report import render_dashboard, render_index
from .storage import save_day
from .valuebets import compute_all
from .xgscore.fixtures import filter_today, scrape_today_fixtures
from .xgscore.preview import scrape_previews

logger = logging.getLogger(__name__)


def _count_with_data(predictions: dict) -> int:
    """How many of ``scrape_previews``'s results actually got real
    market data, as opposed to an empty ``Prediction`` returned because
    that page's extraction found nothing (see
    ``xgscore.preview.scrape_preview`` -- it returns an empty Prediction
    rather than raising, so one bad page doesn't abort the whole run).
    ``len(predictions)`` alone can't tell these apart -- a real run once
    logged "Scraped 15/15 previews successfully" while 12 of those 15
    had individually logged "No preview data extracted" warnings just
    above it, which is what this now feeds into a less misleading count.
    """
    return sum(1 for p in predictions.values() if p.markets)


def _betclic_coverable_markets(cfg: AppConfig) -> set[str]:
    """The set of canonical market *families* Betclic's own calibration
    could ever carry a real odd for, given config.yaml as it stands (as
    of writing: ``1x2``, ``btts``, ``over_under``) -- passed to the
    dashboard's odds-optional "top probability" list so it doesn't fill
    up with markets config.yaml has no extraction rule for at all
    (handicap, per-team totals, ...), which can never be paired with a
    real odd no matter how good the fixture<->offer matching is -- see
    valuebets.top_probability_bets_today's ``coverable_markets`` param.

    Two sources, both reduced to a *family* via ``markets.market_family``
    rather than an exact market string, since a family can cover many
    concrete lines without config.yaml needing to spell out every one:
    - ``market_aliases`` (fixtures' inline odds + the match-detail
      page's fixed-shape markets, e.g. ``1x2.home`` -> family ``1x2``).
    - ``selection_matrix_markets`` (a whole market expanded line by
      line, e.g. ``market_template: "over_under_{line}"`` -> family
      ``over_under``, covering every line that rule expands into without
      needing to enumerate them here).
    """
    aliases = {**cfg.betclic.page("fixtures").market_aliases, **cfg.betclic.page("odds").market_aliases}
    families = {market_family(canonical.rsplit(".", 1)[0]) for canonical in aliases.values()}
    for rule in cfg.betclic.page("odds").selection_matrix_markets:
        template_sample = re.sub(r"\{[^}]+\}", "0", rule.market_template)
        families.add(market_family(template_sample))
    # HandicapMatrixRule always produces exactly these two fixed market
    # names (the *line* is the outcome, not part of the market key --
    # see config.yaml's xgscore.preview.array_markets h1/h2 comment).
    if cfg.betclic.page("odds").handicap_matrix_markets:
        families.add("handicap_home")
        families.add("handicap_away")
    return families


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
    # len(predictions) alone doesn't mean "got real data" -- scrape_preview
    # returns an *empty* Prediction (not an exception) for a page whose
    # extraction found nothing, so this counts non-empty ones specifically
    # rather than repeat the same "successfully" claim the per-page "No
    # preview data extracted" warnings above already contradict.
    with_data = _count_with_data(predictions)
    logger.info("Scraped %d/%d previews with real data", with_data, len(fixtures))
    if with_data < len(fixtures):
        logger.warning(
            "%d/%d fixture(s) got no xGScore preview data at all -- see the "
            "'No preview data extracted' warning(s) above for which ones; "
            "config.yaml's xgscore.preview.wait_ms may need raising further.",
            len(fixtures) - with_data,
            len(fixtures),
        )

    logger.info("Scraping Betclic odds...")
    odds_offers = scrape_today_odds(cfg, day=today)
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
    # Repeat the match count on this same line (not just the separate
    # "Matched X/Y" line above) so a pasted log tail always carries both
    # numbers *and* the file path together -- a real point of confusion
    # once: a games.json pasted separately from its own run's log looked
    # like a 100%-unmatched regression, when it was actually just a
    # leftover file from an earlier run that day (config.data_dir is the
    # same across runs, so each run's save overwrites the previous one's
    # games.json -- only the freshest run's file and its own "Saved" line
    # ever agree).
    logger.info("Saved %s (%d/%d fixtures matched to a Betclic offer this run)", json_path, matched, len(games))

    logger.info("Rendering dashboard...")
    html_path = render_dashboard(
        today,
        games,
        cfg.reports_dir,
        value_bet_threshold=cfg.value_bet_threshold,
        min_probability=cfg.report_min_probability,
        betclic_markets=_betclic_coverable_markets(cfg),
        high_probability_min=cfg.report_high_probability_min,
        mid_probability_min=cfg.report_mid_probability_min,
        mid_probability_max=cfg.report_mid_probability_max,
        high_odd_min=cfg.report_high_odd_min,
        high_odd_max=cfg.report_high_odd_max,
        mid_odd_min=cfg.report_mid_odd_min,
        mid_odd_max=cfg.report_mid_odd_max,
    )
    render_index(cfg.reports_dir)
    logger.info("Rendered %s", html_path)

    return games
