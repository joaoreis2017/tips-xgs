"""Core data structures shared across the pipeline.

Every probability is stored as a float in [0, 1]. Every odd is a decimal
(European) odd, e.g. 2.00. Markets are represented as::

    {"1x2": {"home": 0.45, "draw": 0.25, "away": 0.30}, ...}

so that a prediction (probabilities) and an odds offer (decimal odds) share
the exact same shape and can be zipped together outcome by outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

MarketMap = dict[str, dict[str, float]]


@dataclass
class Fixture:
    """One game listed on xGScore for the day."""

    slug: str  # e.g. "union-berlin-schalke"
    league: str  # e.g. "bundesliga"
    home_team: str
    away_team: str
    kickoff: Optional[datetime]
    preview_url: str
    source: str = "xgscore"

    @property
    def id(self) -> str:
        return f"{self.league}/{self.slug}"

    @property
    def label(self) -> str:
        return f"{self.home_team} - {self.away_team}"


@dataclass
class Prediction:
    """Model probabilities scraped from an xGScore preview page."""

    fixture_id: str
    markets: MarketMap = field(default_factory=dict)
    extra_stats: dict = field(default_factory=dict)  # e.g. xG, form, etc.
    scraped_at: Optional[datetime] = None


@dataclass
class OddsOffer:
    """Decimal odds scraped from a bookmaker (Betclic) for one game."""

    bookmaker: str
    home_team: str
    away_team: str
    kickoff: Optional[datetime]
    markets: MarketMap = field(default_factory=dict)
    url: Optional[str] = None
    scraped_at: Optional[datetime] = None


@dataclass
class ValueBetEntry:
    """One outcome of one market, with model probability + bookmaker odd."""

    market: str
    outcome: str
    label: str  # human readable, e.g. "Resultado Final - Casa"
    probability: float  # model probability, 0..1 -- ALWAYS the raw model number, never overridden (see calibrated_probability for the historically-adjusted one)
    odd: Optional[float] = None  # decimal odd offered by the bookmaker
    implied_probability: Optional[float] = None  # 1 / odd
    fair_probability: Optional[float] = None  # overround-adjusted implied prob
    edge: Optional[float] = None  # effective_probability - fair_probability
    value_ratio: Optional[float] = None  # effective_probability * odd (>1 == positive EV)
    # Explicitly requested (2026-11-14): once enough historical (day,
    # market+band) games have accumulated (see calibration.py), the
    # real observed hit rate for this exact market-family + probability
    # band -- e.g. the model says 70% for "ambas marcam" but history
    # shows that band actually lands 83% of the time. None when there
    # isn't a calibrated/accumulated-history run yet, or that band
    # hasn't reached the minimum sample size (see
    # calibration.calibrated_probability) -- callers then fall back to
    # the model's own raw `probability` for `edge`/`value_ratio` below.
    calibrated_probability: Optional[float] = None
    # How many historical games back calibrated_probability, when set
    # (shown alongside it so the dashboard can say e.g. "45 jogos").
    calibration_sample_size: Optional[int] = None
    rank_by_probability: Optional[int] = None  # 1 = most likely event in match

    @property
    def effective_probability(self) -> float:
        """What `edge`/`value_ratio` are actually computed from:
        `calibrated_probability` once enough history has accumulated
        for this exact market+band, otherwise the model's own raw
        `probability` unchanged."""
        return self.calibrated_probability if self.calibrated_probability is not None else self.probability

    @property
    def is_value_bet(self) -> bool:
        return self.value_ratio is not None and self.value_ratio > 1.0


@dataclass
class MatchedGame:
    """An xGScore fixture+prediction paired with its Betclic odds."""

    fixture: Fixture
    prediction: Optional[Prediction]
    odds: Optional[OddsOffer]
    value_bets: list[ValueBetEntry] = field(default_factory=list)
    match_confidence: Optional[float] = None  # 0..100, fuzzy match score

    @property
    def best_value_bet(self) -> Optional[ValueBetEntry]:
        candidates = [v for v in self.value_bets if v.is_value_bet]
        if not candidates:
            return None
        return max(candidates, key=lambda v: v.value_ratio)

    @property
    def events_by_probability(self) -> list[ValueBetEntry]:
        return sorted(self.value_bets, key=lambda v: v.probability, reverse=True)

    @property
    def value_bets_ranked(self) -> list[ValueBetEntry]:
        """Only actual value bets (``value_ratio > 1``), sorted best first."""
        return sorted(
            (v for v in self.value_bets if v.is_value_bet),
            key=lambda v: v.value_ratio,
            reverse=True,
        )


@dataclass
class MatchResult:
    """Actual final result of a past fixture, scraped from xGScore's
    statistics/history page (``xg-statistics``) -- paired against that
    day's saved predictions (``data/<day>/games.json``) in
    ``calibration.py`` to check how well the model's own probabilities
    held up, e.g. whether "over 2.5" predicted at 70-79% actually hit
    close to 70-79% of the time."""

    league: str
    home_team: str
    away_team: str
    kickoff: Optional[datetime]
    home_goals: int
    away_goals: int


@dataclass
class DailyReport:
    day: date
    games: list[MatchedGame] = field(default_factory=list)
    generated_at: Optional[datetime] = None
