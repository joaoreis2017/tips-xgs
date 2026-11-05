from datetime import date, datetime

from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction
from tipsxgs.storage import load_day, save_day
from tipsxgs.valuebets import compute_value_bets


def test_save_and_load_day_roundtrips(tmp_path):
    fixture = Fixture(
        slug="union-berlin-schalke",
        league="bundesliga",
        home_team="Union Berlin",
        away_team="Schalke",
        kickoff=datetime(2026, 9, 11, 18, 0),
        preview_url="https://xgscore.io/bundesliga/union-berlin-schalke/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets={"1x2": {"home": 0.7, "draw": 0.2, "away": 0.1}})
    odds = OddsOffer(
        bookmaker="betclic",
        home_team="Union Berlin",
        away_team="Schalke",
        kickoff=fixture.kickoff,
        markets={"1x2": {"home": 2.0, "draw": 4.0, "away": 8.0}},
    )
    game = MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=97.5)
    compute_value_bets(game)

    day = date(2026, 9, 11)
    save_day(day, [game], tmp_path)
    loaded = load_day(day, tmp_path)

    assert len(loaded) == 1
    reloaded = loaded[0]
    assert reloaded.fixture.home_team == "Union Berlin"
    assert reloaded.match_confidence == 97.5
    assert reloaded.prediction.markets == prediction.markets
    assert reloaded.odds.markets == odds.markets
    home_entry = next(v for v in reloaded.value_bets if v.outcome == "home")
    assert home_entry.value_ratio == 1.4


def test_load_day_missing_returns_empty(tmp_path):
    assert load_day(date(2099, 1, 1), tmp_path) == []
