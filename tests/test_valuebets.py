from datetime import datetime

import pytest

from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.valuebets import compute_value_bets, top_probability_bets_today, top_value_bets_today


def make_game(markets_prob, markets_odds, slug="union-berlin-schalke", home="Union Berlin", away="Schalke"):
    fixture = Fixture(
        slug=slug,
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=datetime(2026, 9, 11, 18, 0),
        preview_url=f"https://xgscore.io/bundesliga/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=markets_prob)
    odds = (
        OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=fixture.kickoff, markets=markets_odds)
        if markets_odds is not None
        else None
    )
    return MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=100.0 if odds else None)


def test_value_ratio_matches_user_example():
    # 70% probability, odd of 2.00 -> the user's own example of a "great value" bet.
    game = make_game(
        {"1x2": {"home": 0.70, "draw": 0.20, "away": 0.10}},
        {"1x2": {"home": 2.00, "draw": 4.0, "away": 8.0}},
    )
    entries = compute_value_bets(game)
    home = next(e for e in entries if e.market == "1x2" and e.outcome == "home")
    assert home.value_ratio == pytest.approx(1.4)
    assert home.is_value_bet is True


def test_rank_by_probability_orders_events_descending():
    game = make_game(
        {"1x2": {"home": 0.30, "draw": 0.25, "away": 0.45}, "btts": {"yes": 0.55, "no": 0.45}},
        {"1x2": {"home": 3.2, "draw": 3.4, "away": 2.1}, "btts": {"yes": 1.9, "no": 1.9}},
    )
    entries = compute_value_bets(game)
    probs = [e.probability for e in entries]
    assert probs == sorted(probs, reverse=True)
    assert entries[0].rank_by_probability == 1
    assert entries[0].outcome == "yes"  # btts yes at 0.55 is the highest single probability


def test_fair_probability_removes_overround_when_full_market_priced():
    # implied = 1/1.9091 + 1/3.6364 + 1/3.6364 = 0.5238 + 0.275 + 0.275 = 1.0738 (7.4% overround)
    game = make_game(
        {"1x2": {"home": 0.5, "draw": 0.25, "away": 0.25}},
        {"1x2": {"home": 1.9091, "draw": 3.6364, "away": 3.6364}},
    )
    entries = compute_value_bets(game)
    home = next(e for e in entries if e.outcome == "home")
    assert home.fair_probability < home.implied_probability
    assert home.fair_probability == pytest.approx(0.5238 / 1.0738, rel=1e-3)


def test_missing_odds_still_ranks_by_probability_without_value_fields():
    game = make_game({"1x2": {"home": 0.6, "draw": 0.25, "away": 0.15}}, {})
    entries = compute_value_bets(game)
    assert entries[0].outcome == "home"
    assert all(e.odd is None and e.value_ratio is None for e in entries)


def test_value_bets_ranked_excludes_non_positive_value():
    # home has value_ratio 1.4 (value bet); draw/away are < 1 (not value bets)
    game = make_game(
        {"1x2": {"home": 0.70, "draw": 0.20, "away": 0.10}},
        {"1x2": {"home": 2.00, "draw": 3.0, "away": 5.0}},
    )
    compute_value_bets(game)
    ranked = game.value_bets_ranked
    assert len(ranked) == 1
    assert ranked[0].outcome == "home"
    assert all(v.is_value_bet for v in ranked)


def test_top_value_bets_today_sorts_across_games():
    strong = make_game(
        {"1x2": {"home": 0.7, "draw": 0.2, "away": 0.1}},
        {"1x2": {"home": 2.5, "draw": 4.0, "away": 8.0}},
    )
    weak = make_game(
        {"1x2": {"home": 0.5, "draw": 0.3, "away": 0.2}},
        {"1x2": {"home": 1.5, "draw": 3.0, "away": 5.0}},
    )
    compute_value_bets(strong)
    compute_value_bets(weak)
    top = top_value_bets_today([strong, weak], limit=1)
    assert len(top) == 1
    game, entry = top[0]
    assert game is strong
    assert entry.outcome == "home"


def test_top_probability_bets_today_includes_games_with_no_betclic_offer():
    # Unlike top_value_bets_today, this doesn't require a matched odd at
    # all -- a game with none (odds=None, e.g. no Betclic pairing) still
    # shows up here as long as its probability clears the threshold.
    with_odds = make_game(
        {"1x2": {"home": 0.55, "draw": 0.25, "away": 0.2}},
        {"1x2": {"home": 1.8, "draw": 3.5, "away": 4.0}},
        slug="with-odds",
        home="Team A",
        away="Team B",
    )
    no_offer = make_game(
        {"1x2": {"home": 0.9, "draw": 0.07, "away": 0.03}},
        None,
        slug="no-offer",
        home="Team C",
        away="Team D",
    )
    compute_value_bets(with_odds)
    compute_value_bets(no_offer)

    top = top_probability_bets_today([with_odds, no_offer], min_probability=0.5)
    by_game = {g.fixture.slug: e for g, e in top}

    assert "no-offer" in by_game
    assert by_game["no-offer"].odd is None
    assert by_game["no-offer"].value_ratio is None
    assert by_game["no-offer"].probability == pytest.approx(0.9)

    assert "with-odds" in by_game
    assert by_game["with-odds"].odd == pytest.approx(1.8)

    # Highest probability first, regardless of odds availability.
    assert list(by_game.values())[0].probability == pytest.approx(0.9)


def test_top_probability_bets_today_respects_threshold_and_limit():
    game = make_game(
        {"1x2": {"home": 0.7, "draw": 0.2, "away": 0.1}},
        {"1x2": {"home": 2.0, "draw": 4.0, "away": 8.0}},
    )
    compute_value_bets(game)

    # draw (0.2) and away (0.1) fall below a 0.5 threshold.
    top = top_probability_bets_today([game], min_probability=0.5)
    assert [e.outcome for _, e in top] == ["home"]

    # limit caps the result even when more entries clear the threshold.
    top_all = top_probability_bets_today([game], min_probability=0.0, limit=2)
    assert len(top_all) == 2
