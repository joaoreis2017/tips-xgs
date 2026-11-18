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


def test_load_day_recomputes_the_label_instead_of_trusting_the_stored_one(tmp_path):
    # Explicitly requested (2026-11-18): a day saved under an older label
    # format (e.g. before the handicap sign/separator fix) must show the
    # CURRENT label as soon as it's reloaded/re-rendered, not whatever
    # string happened to be frozen in its games.json at save time --
    # load_day re-derives it from market/outcome every time instead.
    fixture = Fixture(
        slug="wales-portugal",
        league="world-cup-qualification",
        home_team="Wales",
        away_team="Portugal",
        kickoff=datetime(2026, 11, 17, 18, 0),
        preview_url="https://xgscore.io/world-cup-qualification/wales-portugal/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets={"handicap_home": {"1.5": 0.669}})
    game = MatchedGame(fixture=fixture, prediction=prediction, odds=None, match_confidence=97.5)
    compute_value_bets(game)

    day = date(2026, 11, 17)
    save_day(day, [game], tmp_path)

    # Simulate a day saved under the old (pre-fix) label format.
    games_path = tmp_path / day.isoformat() / "games.json"
    raw = games_path.read_text(encoding="utf-8")
    assert "Handicap Casa +1.5" in raw  # sanity: compute_value_bets already uses the fixed label
    games_path.write_text(raw.replace("Handicap Casa +1.5", "Handicap Casa - 1.5"), encoding="utf-8")

    loaded = load_day(day, tmp_path)
    entry = loaded[0].value_bets[0]
    assert entry.label == "Handicap Casa +1.5"  # NOT the stale "Handicap Casa - 1.5" on disk
