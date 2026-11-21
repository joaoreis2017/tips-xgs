"""cli.calibrate's scraping/backfill logic.

Explicitly requested (2026-11-20), after a real incident the day
before (xgscore.results' page silently showed "Today" instead of the
"Yesterday" this project was calibrated against, and the scrape got
saved under "yesterday" regardless, without checking): scrape ONCE per
``calibrate`` run (not once per missing day, and no longer gated on
"the missing day IS literally yesterday"), then sort whatever comes
back into the right day(s) by each result's OWN date -- never by
trusting which day the scrape was *for*. This also means a "Week"-style
view (several days' worth of results in one response -- see
config.yaml's xgscore.results.click_selector) can backfill every
missing day it covers in one go, not just a single one.
"""

from __future__ import annotations

from datetime import date, datetime

from click.testing import CliRunner

from tipsxgs.cli import cli
from tipsxgs.models import Fixture, MatchedGame, MatchResult, Prediction
from tipsxgs.storage import load_results, save_day


def _make_game(slug, home, away, day: date, hour=18):
    fixture = Fixture(
        slug=slug,
        league="test-league",
        home_team=home,
        away_team=away,
        kickoff=datetime(day.year, day.month, day.day, hour, 0),
        preview_url=f"https://xgscore.io/test-league/{slug}/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets={"1x2": {"home": 0.6, "draw": 0.25, "away": 0.15}})
    return MatchedGame(fixture=fixture, prediction=prediction, odds=None, match_confidence=None)


def _write_minimal_config(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "xgscore: {results: {url: 'https://xgscore.io/xg-statistics'}}\nbetclic: {}\n",
        encoding="utf-8",
    )
    return tmp_path / "config.yaml"


def test_calibrate_backfills_every_missing_day_covered_by_one_scrape(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path)
    day1, day2, day3 = date(2026, 11, 18), date(2026, 11, 19), date(2026, 11, 20)

    data_dir = tmp_path / "data"
    save_day(day1, [_make_game("a-b", "Team A", "Team B", day1)], data_dir)
    save_day(day2, [_make_game("c-d", "Team C", "Team D", day2)], data_dir)
    save_day(day3, [_make_game("e-f", "Team E", "Team F", day3)], data_dir)

    # Simulates a "Week" view: one scrape returns results for TWO
    # different days at once. day3 (today) isn't covered at all -- its
    # games haven't been played/reported yet.
    scraped = [
        MatchResult(league="L", home_team="Team A", away_team="Team B", kickoff=datetime(2026, 11, 18, 20, 0), home_goals=2, away_goals=1),
        MatchResult(league="L", home_team="Team C", away_team="Team D", kickoff=datetime(2026, 11, 19, 20, 0), home_goals=0, away_goals=0),
    ]
    calls = []

    def fake_scrape(cfg, day):
        calls.append(day)
        return scraped

    monkeypatch.setattr("tipsxgs.cli.scrape_xgscore_results", fake_scrape)

    runner = CliRunner()
    result = runner.invoke(cli, ["calibrate", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1  # scraped ONCE, not once per missing day

    assert len(load_results(day1, data_dir)) == 1
    assert len(load_results(day2, data_dir)) == 1
    assert load_results(day3, data_dir) == []  # not covered by the scrape -- left missing


def test_calibrate_does_not_scrape_again_once_every_day_already_has_results(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path)
    day1 = date(2026, 11, 18)
    data_dir = tmp_path / "data"
    save_day(day1, [_make_game("a-b", "Team A", "Team B", day1)], data_dir)
    from tipsxgs.storage import save_results

    save_results(
        day1,
        [MatchResult(league="L", home_team="Team A", away_team="Team B", kickoff=datetime(2026, 11, 18, 20, 0), home_goals=2, away_goals=1)],
        data_dir,
    )

    calls = []
    monkeypatch.setattr("tipsxgs.cli.scrape_xgscore_results", lambda cfg, day: (calls.append(day) or []))

    runner = CliRunner()
    result = runner.invoke(cli, ["calibrate", "--config", str(cfg_path)])

    assert result.exit_code == 0, result.output
    assert calls == []  # nothing missing -- never scrapes at all


def test_calibrate_respects_no_scrape_results_flag(tmp_path, monkeypatch):
    cfg_path = _write_minimal_config(tmp_path)
    day1 = date(2026, 11, 18)
    data_dir = tmp_path / "data"
    save_day(day1, [_make_game("a-b", "Team A", "Team B", day1)], data_dir)

    calls = []
    monkeypatch.setattr("tipsxgs.cli.scrape_xgscore_results", lambda cfg, day: (calls.append(day) or []))

    runner = CliRunner()
    result = runner.invoke(cli, ["calibrate", "--config", str(cfg_path), "--no-scrape-results"])

    assert calls == []
    assert "No (prediction, actual result) pair found yet" in result.output
