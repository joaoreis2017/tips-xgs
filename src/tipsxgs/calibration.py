"""Check how well the model's own probabilities (saved per day in
``data/<day>/games.json``) held up against what actually happened
(``MatchResult``, scraped from xGScore's statistics/history page -- see
``xgscore/results.py``).

Two views, both built from the same (prediction, actual result) pairs:

- :func:`compute_market_family_summary` -- one row per market *family*
  (``1x2``, ``over_under``, ``btts``, ...): how often it actually hit,
  overall. Answers "que tipos de aposta mais são ganhos".
- :func:`compute_calibration` -- the same, but also split by the
  probability band the model itself predicted (e.g. "70-79%"). A
  well-calibrated market/band hits close to its own band's percentage;
  a lower actual rate means the model is overconfident there, a higher
  one means it's underselling itself. Answers "quais percentagens
  normalmente resultam mais".

Both only cover markets whose actual outcome can be derived purely from
the final score (:func:`actual_outcome_hit`) -- a market this can't
judge (e.g. a handicap line, correct score) is silently excluded rather
than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .markets import market_family
from .matching import _score
from .models import MatchedGame, MatchResult

_OVER_UNDER_LINE_RE = re.compile(r"^over_under_(?P<line>\d+(?:\.\d+)?)$")
# Per-team total goals -- a *different* market family from over_under
# above (total goals for the whole match): market_family() already
# tells these apart on the market key alone ("home_total"/"away_total"
# vs "over_under"), so once actual_outcome_hit can judge them too, they
# show up as their own separate rows rather than being silently dropped.
_HOME_TOTAL_LINE_RE = re.compile(r"^home_total_(?P<line>\d+(?:\.\d+)?)$")
_AWAY_TOTAL_LINE_RE = re.compile(r"^away_total_(?P<line>\d+(?:\.\d+)?)$")

_DOUBLE_CHANCE_COVERS: dict[str, set[str]] = {
    "1x": {"home", "draw"},
    "12": {"home", "away"},
    "x2": {"draw", "away"},
}


def actual_outcome_hit(market: str, outcome: str, home_goals: int, away_goals: int) -> bool | None:
    """Whether ``market``/``outcome`` actually happened, given the final
    score -- or ``None`` when that market can't be judged from the score
    alone (e.g. a handicap line, correct score, half-time result)."""
    total = home_goals + away_goals
    actual_1x2 = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"

    if market == "1x2":
        return outcome == actual_1x2
    if market == "double_chance":
        covers = _DOUBLE_CHANCE_COVERS.get(outcome)
        return actual_1x2 in covers if covers else None
    if market == "btts":
        actual = "yes" if home_goals > 0 and away_goals > 0 else "no"
        return outcome == actual

    m = _OVER_UNDER_LINE_RE.match(market)
    if m:
        line = float(m.group("line"))
        if outcome == "over":
            return total > line
        if outcome == "under":
            return total < line
        return None

    m = _HOME_TOTAL_LINE_RE.match(market)
    if m:
        line = float(m.group("line"))
        if outcome == "over":
            return home_goals > line
        if outcome == "under":
            return home_goals < line
        return None

    m = _AWAY_TOTAL_LINE_RE.match(market)
    if m:
        line = float(m.group("line"))
        if outcome == "over":
            return away_goals > line
        if outcome == "under":
            return away_goals < line
        return None

    return None


def match_games_to_results(
    games: list[MatchedGame], results: list[MatchResult], min_confidence: float = 80.0
) -> list[tuple[MatchedGame, MatchResult]]:
    """Pair each game with its actual final result, one result used at
    most once (greedy, highest score first) -- same fuzzy team-name +
    same-day matching as ``matching.match_fixtures_to_odds`` (reused via
    duck typing: a ``MatchResult`` has the same ``home_team``/
    ``away_team``/``kickoff`` attributes ``_score`` looks at on an
    ``OddsOffer``). A game whose best candidate scores below
    ``min_confidence`` is simply left out, not guessed at.
    """
    remaining = list(enumerate(results))
    candidates: list[tuple[float, int, MatchedGame]] = []
    for game in games:
        for idx, result in remaining:
            candidates.append((_score(game.fixture, result), idx, game))
    candidates.sort(key=lambda c: c[0], reverse=True)

    assigned: dict[str, int] = {}
    used: set[int] = set()
    for score, idx, game in candidates:
        if score < min_confidence:
            continue
        if game.fixture.id in assigned or idx in used:
            continue
        assigned[game.fixture.id] = idx
        used.add(idx)

    return [(game, results[assigned[game.fixture.id]]) for game in games if game.fixture.id in assigned]


@dataclass
class MarketFamilySummary:
    market_family: str
    count: int
    hits: int
    avg_predicted_probability: float

    @property
    def hit_rate(self) -> float:
        return self.hits / self.count if self.count else 0.0


@dataclass
class CalibrationBucket:
    market_family: str
    probability_bucket: str  # e.g. "70-79%"
    count: int
    hits: int
    avg_predicted_probability: float

    @property
    def actual_hit_rate(self) -> float:
        return self.hits / self.count if self.count else 0.0


def _bucket_label(probability: float) -> str:
    pct = min(max(int(probability * 100), 0), 99)  # clamp: a 100% prediction still falls in "90-99%"
    low = (pct // 10) * 10
    return f"{low:02d}-{low + 9:02d}%"


def _collect_rows(
    paired: list[tuple[MatchedGame, MatchResult]],
) -> dict[str, list[tuple[float, bool]]]:
    """One list of ``(predicted_probability, did_it_hit)`` per market
    family, pooling every value-bet entry across every paired game whose
    outcome ``actual_outcome_hit`` can actually judge."""
    rows: dict[str, list[tuple[float, bool]]] = {}
    for game, result in paired:
        for v in game.value_bets:
            hit = actual_outcome_hit(v.market, v.outcome, result.home_goals, result.away_goals)
            if hit is None:
                continue
            rows.setdefault(market_family(v.market), []).append((v.probability, hit))
    return rows


def compute_market_family_summary(
    paired: list[tuple[MatchedGame, MatchResult]],
) -> list[MarketFamilySummary]:
    """One row per market family, sorted by actual hit rate descending
    -- "que tipos de aposta mais são ganhos"."""
    summaries = []
    for family, rows in _collect_rows(paired).items():
        count = len(rows)
        hits = sum(1 for _, hit in rows if hit)
        avg_prob = sum(p for p, _ in rows) / count
        summaries.append(MarketFamilySummary(family, count, hits, avg_prob))
    summaries.sort(key=lambda s: s.hit_rate, reverse=True)
    return summaries


def compute_calibration(paired: list[tuple[MatchedGame, MatchResult]]) -> list[CalibrationBucket]:
    """One row per (market family, predicted-probability decile), sorted
    by market family then bucket -- a reliability diagram: compare each
    bucket's ``actual_hit_rate`` against its own probability range to
    see which markets/bands the model over- or under-estimates."""
    buckets_rows: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    for family, rows in _collect_rows(paired).items():
        for probability, hit in rows:
            key = (family, _bucket_label(probability))
            buckets_rows.setdefault(key, []).append((probability, hit))

    buckets = []
    for (family, bucket_label), rows in buckets_rows.items():
        count = len(rows)
        hits = sum(1 for _, hit in rows if hit)
        avg_prob = sum(p for p, _ in rows) / count
        buckets.append(CalibrationBucket(family, bucket_label, count, hits, avg_prob))
    buckets.sort(key=lambda b: (b.market_family, b.probability_bucket))
    return buckets
