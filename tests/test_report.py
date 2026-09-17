"""Regression tests for the dashboard's "events by probability" filter.

Prompted by four real, sequential bug reports/requests -- the per-game
table's filter has flipped on the "does it need a matched Betclic odd"
question twice now:

1. With every xGScore market extracted (every over/under line, every
   handicap line, ...), a game's full event list was dozens of rows of
   near-certain/near-impossible outcomes ("under 5 goals: 100%") -- fixed
   by requiring a probability threshold (``min_probability``).
2. Explicitly requested afterwards: show *every* event clearing that
   probability threshold, odd or no odd (a previous version additionally
   required a matched Betclic odd above a second threshold, which this
   request reversed).
3. Explicitly requested once more, after an intermediate version also
   dropped odd-less entries for markets Betclic has no extraction rule
   for at all (handicap, per-team totals): per game, this table was
   made the *complete* picture of what xGScore thinks about that one
   match, Betclic-coverable or not.
4. Explicitly requested a third time, reversing #2 back: a "—" row for
   a market/line Betclic simply doesn't offer isn't worth showing at
   all -- an event now needs BOTH to clear ``min_probability`` AND have
   a real matched Betclic odd. The cross-game "top probability" list
   (see ``betclic_markets`` / test_valuebets.py) is unaffected by this
   -- it was never asked to change, and stays odds-optional (only
   dropping the structurally-uncoverable markets from #3).
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


def test_events_require_both_probability_threshold_and_a_matched_odd():
    game = _game(
        markets={
            # Clears the threshold, has a matched odd -- shows up.
            "1x2": {"home": 0.55},
            # Clears the threshold too, but no matching Betclic odd at
            # all -- dropped: a "—" row isn't worth showing.
            "btts": {"yes": 0.7},
            # Below the threshold -- excluded regardless of odds.
            "over_under_2.5": {"under": 0.3},
        },
        odds_markets={"1x2": {"home": 1.8}},
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5)
    events = ctx["games"][0]["events"]

    assert {e.market for e in events} == {"1x2"}
    assert all(e.odd is not None for e in events)


def test_events_drop_markets_with_no_matched_odd_even_if_betclic_covers_them():
    # handicap_home (odd-less here, e.g. Betclic just doesn't offer this
    # exact line) is dropped same as btts (also odd-less) -- unlike the
    # cross-game "top probability" list, betclic_markets doesn't even
    # come into it: any odd-less entry is dropped regardless of whether
    # its market family is one Betclic ever covers.
    game = _game(
        markets={
            "1x2": {"home": 0.55},
            "btts": {"yes": 0.7},
            "handicap_home": {"-3": 0.99},
        },
        odds_markets={"1x2": {"home": 1.8}},
    )

    ctx = build_context(date(2026, 9, 12), [game], min_probability=0.5, betclic_markets={"1x2", "btts"})
    assert {e.market for e in ctx["games"][0]["events"]} == {"1x2"}


def test_events_empty_when_no_betclic_offer_matched_at_all():
    # A game with no matched Betclic offer at all (odds is None, so
    # every odd is None) now shows no events -- there's nothing to
    # compare its high-probability picks against.
    game = _game(markets={"1x2": {"home": 0.9}}, odds_markets=None)

    ctx = build_context(date(2026, 9, 12), [game])
    assert ctx["games"][0]["events"] == []
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


def test_high_band_requires_probability_and_odd_in_range():
    # CHANGED (2026-09-17, explicitly requested): the high band is now
    # >=70% AND a matched odd strictly between 1.25 and 1.45 -- unlike
    # every other probability-ranked view, an odd is required here, and
    # only within that specific window.
    game = _game(
        markets={
            "1x2": {"home": 0.9},  # 90%, odd in range -> shows
            "btts": {"yes": 0.85},  # 85%, odd outside range -> dropped
            "handicap_home": {"-3": 0.99},  # 99%, no odd at all -> dropped
        },
        odds_markets={"1x2": {"home": 1.35}, "btts": {"yes": 1.10}},
    )

    ctx = build_context(date(2026, 9, 12), [game])
    rows = ctx["high_probability_bets"]
    assert [r["label"] for r in rows] == ["Resultado Final - Casa"]
    assert rows[0]["odd"] == pytest.approx(1.35)
    assert ctx["mid_probability_bets"] == []


def test_mid_band_stays_odds_optional_and_drops_uncoverable_markets():
    # The mid band (60%-69%) has no odd-range requirement -- unlike the
    # high band above, an odd-less entry still shows (odd/valor as "—"),
    # except for markets betclic_markets says Betclic never covers at
    # all (same coverable_markets behavior as before).
    game = _game(
        markets={"1x2": {"home": 0.65}, "handicap_home": {"-3": 0.65}},
        odds_markets=None,
    )

    ctx = build_context(date(2026, 9, 12), [game], betclic_markets={"1x2", "btts"})
    rows = ctx["mid_probability_bets"]
    assert len(rows) == 1
    assert rows[0]["label"] == "Resultado Final - Casa"
    assert rows[0]["odd"] is None
    assert ctx["high_probability_bets"] == []


def test_probability_bands_cover_games_without_a_betclic_offer_and_split_by_band():
    # Requested explicitly: two cross-game "probability" lists that,
    # unlike top_value_bets, cover *every* game with a prediction --
    # including one with no matched Betclic offer at all. A no-offer
    # game can now only ever land in the mid band, since the high band
    # requires a matched odd in a specific range.
    no_offer = _game(
        markets={"1x2": {"home": 0.65}}, odds_markets=None, slug="no-offer", home="Team C", away="Team D"
    )
    with_offer = _game(
        markets={"1x2": {"home": 0.9}},
        odds_markets={"1x2": {"home": 1.35}},
        slug="with-offer",
        home="Team A",
        away="Team B",
    )

    ctx = build_context(date(2026, 9, 12), [no_offer, with_offer])

    high_rows = ctx["high_probability_bets"]
    assert len(high_rows) == 1
    assert high_rows[0]["game_slug"] == "with-offer"
    assert high_rows[0]["odd"] == pytest.approx(1.35)

    mid_rows = ctx["mid_probability_bets"]
    assert len(mid_rows) == 1
    assert mid_rows[0]["game_slug"] == "no-offer"
    assert mid_rows[0]["odd"] is None
