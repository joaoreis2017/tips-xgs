"""Regression tests for the dashboard's "events by probability" filter.

Prompted by three real, sequential bug reports:

1. With every xGScore market extracted (every over/under line, every
   handicap line, ...), a game's full event list was dozens of rows of
   near-certain/near-impossible outcomes ("under 5 goals: 100%") -- fixed
   by requiring a probability threshold (``min_probability``).
2. Explicitly requested afterwards: show *every* event clearing that
   probability threshold, odd or no odd (a previous version additionally
   required a matched Betclic odd above a second threshold, which this
   request reverses).
3. Explicitly requested once more, after an intermediate version also
   dropped odd-less entries for markets Betclic has no extraction rule
   for at all (handicap, per-team totals): per game, this table is
   meant to be the *complete* picture of what xGScore thinks about that
   one match, Betclic-coverable or not -- unlike the cross-game "top
   probability" list (see ``betclic_markets`` / test_valuebets.py),
   which *does* still drop those to avoid flooding a list spanning many
   games with the same permanently-odd-less pattern repeated for each.
"""

from datetime import date

import pytest

from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.report import build_context
from tipsxgs.valuebets import compute_value_bets


def _game(
    markets: dict,
    odds_markets: dict | None,
    slug: str = "home-away",
    home: str = "Lazio",
    away: str = "Milan",
) -> MatchedGame:
    fixture = Fixture(
        slug=slug,
        league="serie-a",
        home_team=home,
        away_team=away,
        kickoff=None,
        preview_url=f"https://xgscore.io/serie-a/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets)
    odds = (
        OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=None, markets=odds_markets)
        if odds_markets is not None
        else None
    )
    game = MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=96.0)
    compute_value_bets(game)
    return game


def test_events_only_require_the_probability_threshold():
    game = _game(
        markets={
            # Clears the threshold, has a matched odd -- shows up.
            "1x2": {"home": 0.55},
            # Clears the threshold too, but no matching Betclic odd at
            # all -- still shows up (odd/valor render as "—"), since
            # nothing here requires an odd anymore.
            "btts": {"yes": 0.7},
            # Below the threshold -- excluded regardless of odds.
            "over_under_2.5": {"under": 0.3},
        },
        odds_markets={"1x2": {"home": 1.8}},
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5)
    events = ctx["games"][0]["events"]

    by_market = {e.market for e in events}
    assert by_market == {"1x2", "btts"}
    btts_event = next(e for e in events if e.market == "btts")
    assert btts_event.odd is None


def test_events_ignore_betclic_markets_unlike_the_cross_game_list():
    # Real screenshot bug report: a per-game table showing only 3 events
    # when xGScore had "muitas mais" (many more) above 50% probability --
    # caused by an intermediate version applying the SAME
    # betclic_markets filter here as the cross-game "top probability"
    # list uses. Per game, betclic_markets must NOT drop anything --
    # handicap_home (not in betclic_markets, and odd-less) still shows
    # up, since this table is meant to be xGScore's complete picture of
    # this one match, not just the Betclic-actionable slice.
    game = _game(
        markets={
            "1x2": {"home": 0.55},
            "btts": {"yes": 0.7},
            "handicap_home": {"-3": 0.99},
        },
        odds_markets={"1x2": {"home": 1.8}},
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5, betclic_markets={"1x2", "btts"})
    assert {e.market for e in ctx["games"][0]["events"]} == {"1x2", "btts", "handicap_home"}


def test_events_show_even_with_no_betclic_offer_matched():
    # Explicitly requested: a game with no matched Betclic offer at all
    # (odds is None, so every odd is None) still shows its
    # high-probability events -- odd/valor just render as "—".
    game = _game(markets={"1x2": {"home": 0.9}}, odds_markets=None)

    ctx = build_context(date(2026, 9, 12), [game])
    events = ctx["games"][0]["events"]
    assert len(events) == 1
    assert events[0].odd is None
    # The underlying probability data is untouched -- still there for
    # games.json / other views either way.
    assert game.prediction.markets == {"1x2": {"home": 0.9}}


def test_events_threshold_is_configurable():
    game = _game(markets={"1x2": {"home": 0.4}}, odds_markets={"1x2": {"home": 1.5}})

    # Below the default 0.5 probability threshold -- excluded.
    assert build_context(date(2026, 9, 12), [game])["games"][0]["events"] == []
    # Lowering the threshold includes it.
    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.3)
    assert len(ctx["games"][0]["events"]) == 1


def test_has_predictions_distinguishes_genuinely_empty_from_filtered_out():
    # An empty `events` table can mean two very different things -- the
    # dashboard template needs `has_predictions` to tell them apart
    # rather than showing the same "nothing was scraped" message for
    # both (a real bug report from a user who had plenty of xGScore
    # predictions, just none clearing the probability filter above).
    scraped_but_filtered = _game(markets={"1x2": {"home": 0.3}}, odds_markets=None)  # below threshold
    genuinely_empty = _game(markets={}, odds_markets=None)

    ctx = build_context(date(2026, 9, 12), [scraped_but_filtered, genuinely_empty])
    assert ctx["games"][0]["has_predictions"] is True
    assert ctx["games"][0]["events"] == []
    assert ctx["games"][1]["has_predictions"] is False
    assert ctx["games"][1]["events"] == []


def test_top_probability_bets_drops_markets_betclic_never_covers():
    # betclic_markets, when passed, drops odd-less entries for markets
    # config.yaml's betclic section has no extraction rule for at all
    # (e.g. handicap lines) -- see valuebets.top_probability_bets_today.
    game = _game(
        markets={"1x2": {"home": 0.9}, "handicap_home": {"-3": 0.99}},
        odds_markets=None,
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5, betclic_markets={"1x2", "btts"})
    rows = ctx["top_probability_bets"]
    assert len(rows) == 1
    assert rows[0]["game_slug"] == "home-away"
    assert rows[0]["label"] == "Resultado Final - Casa"


def test_top_probability_bets_covers_games_without_a_betclic_offer():
    # Requested explicitly: a cross-game "high probability" list that,
    # unlike top_value_bets, covers *every* game with a prediction --
    # including one with no matched Betclic offer at all.
    no_offer = _game(
        markets={"1x2": {"home": 0.9}}, odds_markets=None, slug="no-offer", home="Team C", away="Team D"
    )
    with_offer = _game(
        markets={"1x2": {"home": 0.55}},
        odds_markets={"1x2": {"home": 1.8}},
        slug="with-offer",
        home="Team A",
        away="Team B",
    )

    ctx = build_context(date(2026, 9, 12), [no_offer, with_offer], min_probability=0.5)
    rows = ctx["top_probability_bets"]

    by_slug = {r["game_slug"]: r for r in rows}
    assert "no-offer" in by_slug
    assert by_slug["no-offer"]["odd"] is None
    assert by_slug["no-offer"]["value_ratio"] is None
    assert "with-offer" in by_slug
    assert by_slug["with-offer"]["odd"] == pytest.approx(1.8)
    # Highest probability first.
    assert rows[0]["game_slug"] == "no-offer"
