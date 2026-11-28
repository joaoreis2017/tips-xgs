from datetime import date, datetime

from tipsxgs.config import load_config
from tipsxgs.models import Fixture, Prediction
from tipsxgs.pipeline import _betclic_coverable_markets, _count_with_data, run_daily


def test_betclic_coverable_markets_derived_from_real_config():
    # Real config.yaml has extraction rules for 1x2 (inline on the
    # fixtures listing) + btts/double_chance (fixed fields) +
    # over_under/home_total/away_total (selection_matrix_markets,
    # each covering every line Betclic offers) + handicap_home/
    # handicap_away (handicap_matrix_markets, Betclic's 3-way integer
    # handicap remapped to xGScore's Asian half-lines) -- only
    # correct_score remains uncalibrated (a large variable-size grid,
    # and xGScore's own "cs" field is often null pre-kickoff anyway).
    cfg = load_config()
    assert _betclic_coverable_markets(cfg) == {
        "1x2",
        "btts",
        "double_chance",
        "over_under",
        "home_total",
        "away_total",
        "handicap_home",
        "handicap_away",
    }


def test_run_daily_skip_betclic_never_calls_the_betclic_scraper(tmp_path, monkeypatch):
    # Real case (2026-11-27): GitHub Actions' datacenter IP is
    # geo-blocked by Betclic outright -- every request would just
    # fail/retry for nothing while away from a Portuguese-IP machine for
    # a week. skip_betclic=True must skip calling scrape_today_odds
    # entirely rather than let it run and 403.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        "xgscore: {}\nbetclic: {}\n",
        encoding="utf-8",
    )
    cfg = load_config(tmp_path / "config.yaml")
    day = date(2026, 11, 27)
    fixture = Fixture(
        slug="a-b",
        league="test-league",
        home_team="Team A",
        away_team="Team B",
        kickoff=datetime(2026, 11, 27, 18, 0),
        preview_url="https://xgscore.io/test-league/a-b/preview",
    )
    monkeypatch.setattr("tipsxgs.pipeline.scrape_today_fixtures", lambda cfg: [fixture])
    monkeypatch.setattr(
        "tipsxgs.pipeline.scrape_previews",
        lambda cfg, fixtures: {fixture.id: Prediction(fixture_id=fixture.id, markets={"1x2": {"home": 0.6}})},
    )

    betclic_calls = []
    monkeypatch.setattr(
        "tipsxgs.pipeline.scrape_today_odds", lambda *a, **kw: (betclic_calls.append(1) or [])
    )

    games = run_daily(cfg, day, skip_betclic=True)

    assert betclic_calls == []  # never even attempted
    assert len(games) == 1
    assert games[0].odds is None


def test_count_with_data_ignores_empty_previews():
    # Real bug: scrape_preview() returns an *empty* Prediction (not an
    # exception) when a page's extraction found nothing, so
    # len(predictions) alone claimed "15/15 successfully" on a live run
    # where 12 of those 15 had no real data at all. _count_with_data
    # only counts the ones that actually got market data.
    class _P:
        def __init__(self, markets):
            self.markets = markets

    predictions = {"a": _P({"1x2": {"home": 0.5}}), "b": _P({}), "c": _P({"btts": {"yes": 0.6}})}
    assert _count_with_data(predictions) == 2
