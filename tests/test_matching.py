from datetime import datetime

from tipsxgs.matching import match_fixtures_to_odds
from tipsxgs.models import Fixture, OddsOffer, Prediction


def fx(home, away, day=11):
    return Fixture(
        slug=f"{home}-{away}".lower().replace(" ", "-"),
        league="bundesliga",
        home_team=home,
        away_team=away,
        kickoff=datetime(2026, 9, day, 18, 0),
        preview_url="https://xgscore.io/x/preview",
    )


def offer(home, away, day=11):
    return OddsOffer(bookmaker="betclic", home_team=home, away_team=away, kickoff=datetime(2026, 9, day, 18, 0))


def test_exact_name_match():
    fixtures = [fx("Union Berlin", "Schalke")]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Union Berlin", "Schalke")])
    assert len(games) == 1
    assert games[0].odds is not None
    assert games[0].match_confidence == 100.0


def test_fuzzy_name_variants_still_match():
    fixtures = [fx("1. FC Union Berlin", "FC Schalke 04")]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Union Berlin", "Schalke")], min_confidence=60)
    assert games[0].odds is not None


def test_same_names_different_day_does_not_match():
    fixtures = [fx("Union Berlin", "Schalke", day=11)]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Union Berlin", "Schalke", day=25)])
    assert games[0].odds is None


def test_two_similar_fixtures_do_not_share_one_offer():
    fixtures = [fx("Real Madrid", "Sevilla"), fx("Real Sociedad", "Sevilla")]
    offers = [offer("Real Madrid", "Sevilla")]
    games = match_fixtures_to_odds(fixtures, {}, offers, min_confidence=70)
    matched = [g for g in games if g.odds is not None]
    assert len(matched) == 1
    assert matched[0].fixture.home_team == "Real Madrid"


def test_abbreviated_team_name_still_matches_via_token_set_ratio():
    # Real case from a live run: xGScore listed "Vitoria Guimaraes"
    # abbreviated down to "Victoria G.", which token_sort_ratio alone
    # scores too low (length/token-count mismatch) to clear a sane
    # min_confidence. token_set_ratio ignores the extra/missing tokens
    # instead of penalizing them, so the pair should still match.
    fixtures = [fx("Academico Viseu", "Victoria G.")]
    games = match_fixtures_to_odds(
        fixtures, {}, [offer("Academico Viseu", "Vitoria Guimaraes")], min_confidence=80
    )
    assert games[0].odds is not None


def test_unrelated_fixtures_never_cross_a_sane_confidence_threshold():
    # Regression guard for a real false-positive: fuzz.WRatio was briefly
    # added to _score() to rescue an abbreviated-name case ("Dep. Riestra
    # - Lanus" vs "Deportivo Riestra - Atletico Lanus", scoring only 68
    # on token_sort/token_set), and reverted the same day once a live
    # run's own data showed WRatio scoring "Torino - Roma" 85.5 against
    # the completely unrelated "Dynamo K. - Epitsentr" -- a wrong match
    # (feeding a real-looking but bogus odd into the value-bet
    # calculation) is worse than no match, so this locks in that no
    # algorithm added to _score() may score totally unrelated team names
    # anywhere near a sane min_confidence. The abbreviated-name case
    # above stays correctly unmatched below 80 until a safer fix exists.
    fixtures = [fx("Dynamo K.", "Epitsentr")]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Torino", "Roma")], min_confidence=80)
    assert games[0].odds is None


def test_predictions_are_attached_by_fixture_id():
    fixture = fx("Union Berlin", "Schalke")
    prediction = Prediction(fixture_id=fixture.id, markets={"1x2": {"home": 0.5, "draw": 0.3, "away": 0.2}})
    games = match_fixtures_to_odds([fixture], {fixture.id: prediction}, [])
    assert games[0].prediction is prediction
