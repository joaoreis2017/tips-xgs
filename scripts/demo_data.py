#!/usr/bin/env python3
"""Render the dashboard from made-up (but realistic-shaped) data.

Useful for:
* Previewing/tweaking dashboard.html.j2 without needing network access.
* Confirming the whole models -> valuebets -> report chain works before
  config.yaml is calibrated against the real sites.

    python scripts/demo_data.py
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tipsxgs.models import Fixture, MatchedGame, OddsOffer, Prediction  # noqa: E402
from tipsxgs.report import render_dashboard, render_index  # noqa: E402
from tipsxgs.valuebets import compute_all  # noqa: E402

DAY = date.today()


def game(league, home, away, hour, minute, model_markets, betclic_markets, confidence=96.0):
    fixture = Fixture(
        slug=f"{home}-{away}".lower().replace(" ", "-"),
        league=league,
        home_team=home,
        away_team=away,
        kickoff=datetime(DAY.year, DAY.month, DAY.day, hour, minute),
        preview_url=f"https://xgscore.io/{league}/{home}-{away}".lower().replace(" ", "-") + "/preview",
    )
    prediction = Prediction(fixture_id=fixture.id, markets=model_markets)
    odds = OddsOffer(
        bookmaker="betclic",
        home_team=home,
        away_team=away,
        kickoff=fixture.kickoff,
        markets=betclic_markets,
    )
    return MatchedGame(fixture=fixture, prediction=prediction, odds=odds, match_confidence=confidence)


GAMES = [
    game(
        "bundesliga", "Union Berlin", "Schalke", 18, 30,
        model_markets={
            "1x2": {"home": 0.70, "draw": 0.20, "away": 0.10},
            "btts": {"yes": 0.42, "no": 0.58},
            "over_under_2.5": {"over": 0.38, "under": 0.62},
        },
        betclic_markets={
            "1x2": {"home": 2.00, "draw": 3.60, "away": 6.50},
            "btts": {"yes": 2.10, "no": 1.72},
            "over_under_2.5": {"over": 2.35, "under": 1.58},
        },
    ),
    game(
        "premier-league", "Arsenal", "Brighton", 16, 0,
        model_markets={
            "1x2": {"home": 0.58, "draw": 0.24, "away": 0.18},
            "btts": {"yes": 0.61, "no": 0.39},
            "over_under_2.5": {"over": 0.66, "under": 0.34},
        },
        betclic_markets={
            "1x2": {"home": 1.65, "draw": 3.90, "away": 5.20},
            "btts": {"yes": 1.75, "no": 2.00},
            "over_under_2.5": {"over": 1.80, "under": 1.95},
        },
    ),
    game(
        "la-liga", "Real Sociedad", "Getafe", 21, 0,
        model_markets={
            "1x2": {"home": 0.48, "draw": 0.29, "away": 0.23},
            "btts": {"yes": 0.35, "no": 0.65},
            "over_under_2.5": {"over": 0.30, "under": 0.70},
        },
        betclic_markets={
            "1x2": {"home": 2.05, "draw": 3.30, "away": 3.80},
            "btts": {"yes": 2.60, "no": 1.48},
            "over_under_2.5": {"over": 2.70, "under": 1.42},
        },
        confidence=89.0,
    ),
]


def main():
    compute_all(GAMES)
    out_dir = Path(__file__).resolve().parents[1] / "examples" / "demo"
    path = render_dashboard(DAY, GAMES, out_dir, demo=True)
    render_index(out_dir)
    print(f"Demo dashboard written to {path}")


if __name__ == "__main__":
    main()
