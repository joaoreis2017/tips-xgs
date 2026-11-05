"""Persist and reload a day's matched games as JSON.

Layout::

    data/
      2026-09-11/
        games.json     <- everything needed to re-render the report

Kept as plain JSON (no DB) so the data is easy to inspect, diff, and
commit if you want a history of value bets found each day.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from .models import Fixture, MatchedGame, OddsOffer, Prediction, ValueBetEntry


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def game_to_dict(game: MatchedGame) -> dict:
    return {
        "fixture": {
            "slug": game.fixture.slug,
            "league": game.fixture.league,
            "home_team": game.fixture.home_team,
            "away_team": game.fixture.away_team,
            "kickoff": _dt(game.fixture.kickoff),
            "preview_url": game.fixture.preview_url,
            "source": game.fixture.source,
        },
        "prediction": (
            {
                "fixture_id": game.prediction.fixture_id,
                "markets": game.prediction.markets,
                "extra_stats": game.prediction.extra_stats,
                "scraped_at": _dt(game.prediction.scraped_at),
            }
            if game.prediction
            else None
        ),
        "odds": (
            {
                "bookmaker": game.odds.bookmaker,
                "home_team": game.odds.home_team,
                "away_team": game.odds.away_team,
                "kickoff": _dt(game.odds.kickoff),
                "markets": game.odds.markets,
                "url": game.odds.url,
                "scraped_at": _dt(game.odds.scraped_at),
            }
            if game.odds
            else None
        ),
        "match_confidence": game.match_confidence,
        "value_bets": [
            {
                "market": v.market,
                "outcome": v.outcome,
                "label": v.label,
                "probability": v.probability,
                "odd": v.odd,
                "implied_probability": v.implied_probability,
                "fair_probability": v.fair_probability,
                "edge": v.edge,
                "value_ratio": v.value_ratio,
                "rank_by_probability": v.rank_by_probability,
            }
            for v in game.value_bets
        ],
    }


def game_from_dict(raw: dict) -> MatchedGame:
    f = raw["fixture"]
    fixture = Fixture(
        slug=f["slug"],
        league=f["league"],
        home_team=f["home_team"],
        away_team=f["away_team"],
        kickoff=_parse_dt(f.get("kickoff")),
        preview_url=f["preview_url"],
        source=f.get("source", "xgscore"),
    )

    prediction = None
    if raw.get("prediction"):
        p = raw["prediction"]
        prediction = Prediction(
            fixture_id=p["fixture_id"],
            markets=p.get("markets", {}),
            extra_stats=p.get("extra_stats", {}),
            scraped_at=_parse_dt(p.get("scraped_at")),
        )

    odds = None
    if raw.get("odds"):
        o = raw["odds"]
        odds = OddsOffer(
            bookmaker=o["bookmaker"],
            home_team=o["home_team"],
            away_team=o["away_team"],
            kickoff=_parse_dt(o.get("kickoff")),
            markets=o.get("markets", {}),
            url=o.get("url"),
            scraped_at=_parse_dt(o.get("scraped_at")),
        )

    value_bets = [
        ValueBetEntry(
            market=v["market"],
            outcome=v["outcome"],
            label=v["label"],
            probability=v["probability"],
            odd=v.get("odd"),
            implied_probability=v.get("implied_probability"),
            fair_probability=v.get("fair_probability"),
            edge=v.get("edge"),
            value_ratio=v.get("value_ratio"),
            rank_by_probability=v.get("rank_by_probability"),
        )
        for v in raw.get("value_bets", [])
    ]

    return MatchedGame(
        fixture=fixture,
        prediction=prediction,
        odds=odds,
        value_bets=value_bets,
        match_confidence=raw.get("match_confidence"),
    )


def save_day(day: date, games: list[MatchedGame], data_dir: Path) -> Path:
    day_dir = data_dir / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "games.json"
    payload = {
        "date": day.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "games": [game_to_dict(g) for g in games],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_day(day: date, data_dir: Path) -> list[MatchedGame]:
    path = data_dir / day.isoformat() / "games.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [game_from_dict(g) for g in payload.get("games", [])]
