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
    # above was fixed instead by _expand_abbreviated_tokens (see below),
    # a narrower fix that this same fixture pair also guards.
    fixtures = [fx("Dynamo K.", "Epitsentr")]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Torino", "Roma")], min_confidence=80)
    assert games[0].odds is None


def test_period_abbreviated_team_name_expands_against_the_full_spelling():
    # Real case from a live run (2026-09-21): "Barracas C. - Indep. R."
    # (xGScore) against "Barracas Central - Independiente Rivadavia"
    # (Betclic) scored only 68 -- token_sort/token_set_ratio compare
    # "indep." and "independiente" as two unrelated words. Expanding the
    # abbreviation against the other side's full word (see
    # _expand_abbreviated_tokens) fixes this without reintroducing
    # WRatio's false-positive risk (see the test above).
    fixtures = [fx("Barracas C.", "Indep. R.")]
    games = match_fixtures_to_odds(
        fixtures, {}, [offer("Barracas Central", "Independiente Rivadavia")], min_confidence=80
    )
    assert games[0].odds is not None


def test_this_years_originally_reported_abbreviation_case_now_matches():
    # The exact case that originally motivated (and then burned) the
    # WRatio attempt -- see test_unrelated_fixtures_never_cross_a_sane_
    # confidence_threshold's docstring. Now fixed via
    # _expand_abbreviated_tokens instead.
    fixtures = [fx("Dep. Riestra", "Lanus")]
    games = match_fixtures_to_odds(
        fixtures, {}, [offer("Deportivo Riestra", "Atletico Lanus")], min_confidence=80
    )
    assert games[0].odds is not None


def test_short_abbreviated_tokens_do_not_expand_and_cannot_cause_false_positives():
    # "K." (1 letter) and "R." are far too short to be a reliable
    # abbreviation signal -- lots of unrelated words start with the same
    # letter -- so _MIN_ABBREVIATION_STEM_LEN keeps them untouched rather
    # than letting them latch onto some coincidentally-matching word on
    # the other side.
    fixtures = [fx("Dynamo K.", "Real R.")]
    games = match_fixtures_to_odds(fixtures, {}, [offer("Dynamo Kyiv", "Real Rovers")], min_confidence=90)
    assert games[0].odds is None


def test_predictions_are_attached_by_fixture_id():
    fixture = fx("Union Berlin", "Schalke")
    prediction = Prediction(fixture_id=fixture.id, markets={"1x2": {"home": 0.5, "draw": 0.3, "away": 0.2}})
    games = match_fixtures_to_odds([fixture], {fixture.id: prediction}, [])
    assert games[0].prediction is prediction
