"""Check how well the model's own probabilities (saved per day in
``data/<day>/games.json``) held up against what actually happened
(``MatchResult``, scraped from xGScore's statistics/history page -- see
``xgscore/results.py``).

:func:`compute_calibration` -- one row per (exact market, outcome,
predicted-probability band, e.g. "70-79%") -- a reliability diagram:
compare each bucket's ``actual_hit_rate`` against the probability
range the model itself predicted, to answer "quando o modelo diz 70%
para ambas marcam, isso acontece mesmo à volta de 70% das vezes?".

Explicitly requested (2026-11-14, then again to go further): kept
fully separate per *outcome*, not just per market -- home wins tracked
apart from away wins, over apart from under, home_total's own
over/under apart from away_total's, double_chance's "1x" apart from
its "x2" (reported as more trustworthy this way: a market's different
outcomes can behave very differently, e.g. a model might be
well-calibrated on home wins but overconfident on away wins, which
pooling them would hide) -- AND, on top of that, per *exact market*
rather than market *family*: ``over_under_1.5`` is tracked completely
apart from ``over_under_2.5``/``3.5``/``4.5``/``5.5``, and likewise for
every ``home_total_<line>``/``away_total_<line>`` -- markets.
market_family() (which strips the trailing line number so
``over_under_1.5``/``2.5`` are seen as one family) is used elsewhere
in the codebase (e.g. checking whether Betclic covers a market *kind*
at all) but deliberately NOT here: different lines of the same market
can be calibrated very differently in practice (over 1.5 is a near-
certain bet that may be well-calibrated, over 4.5 is a long shot that
may not be), and pooling them the way an earlier version of this
module did would hide that.
``double_chance``'s "12" outcome is excluded entirely (not just split
out) at the same request -- never bet on, so never tracked. Likewise
(2026-11-16): a whole-number over/under line (1, 2, 3, ...) is excluded
entirely -- only half-integer lines (0.5, 1.5, 2.5, ...) are ever bet
on, so only those are tracked. Likewise (2026-11-18):
``handicap_home``/``handicap_away`` at exactly their own +0.5 line are
excluded too -- each is mathematically the SAME bet as a
``double_chance`` outcome (home covers +0.5 iff it doesn't lose, i.e.
exactly "1x"; away's own +0.5 is exactly "x2"), so tracking both would
calibrate the identical real-world event twice under two different
labels.

Deliberately does NOT also report a single hit-rate *per market*
pooled across every probability level (an earlier version did, and was
removed -- explicitly reported as not making sense, 2026-11-14): for
any market whose outcomes are exhaustive and always sum to 1 (btts
yes/no, 1x2 home/draw/away, double_chance 1x/12/x2, over/under at one
line), pooling every outcome of every game is mathematically forced to
hover around a fixed 1/n-ish constant (~50% for a 2-way market, ~33%
for 3-way, ~67% for double_chance, which always covers exactly 2 of 3
possible results) *regardless of how good or bad the model actually
is* -- it carries zero information about skill. Splitting by
probability band removes this degeneracy: a high band (e.g. 80-89%)
can only ever be reached by a game's one favored side (its
complementary side is necessarily below 50%, landing in a low band
instead), so that band's hit rate is a genuine, non-tautological
measure of "when the model is this confident, how often is it right".

Only covers markets whose actual outcome can be derived purely from
the final score (:func:`actual_outcome_hit`) -- a market this still
can't judge (e.g. correct score, half-time result) is silently
excluded rather than guessed at. ``handicap_home``/``handicap_away``
(2026-11-17) ARE covered: a team covers its own Asian-handicap line L
if its score, with L added, still beats the other side's.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .matching import _score
from .models import MatchedGame, MatchResult

# Below this many accumulated historical games, a bucket's own
# actual_hit_rate is considered too noisy to act on -- see
# calibrated_probability, which falls back to the model's raw
# probability until a bucket clears this.
DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE = 30

_OVER_UNDER_LINE_RE = re.compile(r"^over_under_(?P<line>\d+(?:\.\d+)?)$")
# Per-team total goals -- a *different* market from over_under above
# (total goals for the whole match), judged from that one side's own
# goals rather than the combined total.
_HOME_TOTAL_LINE_RE = re.compile(r"^home_total_(?P<line>\d+(?:\.\d+)?)$")
_AWAY_TOTAL_LINE_RE = re.compile(r"^away_total_(?P<line>\d+(?:\.\d+)?)$")

# Explicitly requested (2026-11-16): whole-number lines (over/under 1,
# 2, 3, ...) are never tracked at all -- only half-integer lines (0.5,
# 1.5, 2.5, ...), the only ones actually bet on (a whole-number line
# can push -- the total lands exactly on it -- which isn't a market
# this project places).
_LINE_MARKET_RE = re.compile(r"^(?:over_under|home_total|away_total)_(?P<line>\d+(?:\.\d+)?)$")


def _is_whole_number_line(market: str) -> bool:
    m = _LINE_MARKET_RE.match(market)
    return bool(m) and float(m.group("line")).is_integer()


# Same rule as above (2026-11-17, explicitly requested), but for
# handicap_home/handicap_away -- there the line is the *outcome*
# string (e.g. "-1.5", "0", "1"), not part of the market key, since
# xGScore's own h1/h2 report one outcome per line it covers (see
# actual_outcome_hit). A whole-number handicap line (0, 1, -1, ...) can
# push (the adjusted scores land exactly level) the same way a
# whole-number over/under line can -- excluded entirely, same as above.
def _is_whole_number_handicap(market: str, outcome: str) -> bool:
    if market not in ("handicap_home", "handicap_away"):
        return False
    try:
        return float(outcome).is_integer()
    except (TypeError, ValueError):
        return False


_DOUBLE_CHANCE_COVERS: dict[str, set[str]] = {
    "1x": {"home", "draw"},
    "12": {"home", "away"},
    "x2": {"draw", "away"},
}

# (market, outcome) pairs explicitly excluded from calibration
# entirely -- never tracked, rather than tracked separately like every
# other outcome. See the module docstring.
_EXCLUDED_MARKET_OUTCOMES: set[tuple[str, str]] = {
    ("double_chance", "12"),  # never bet on
    # Explicitly requested (2026-11-18): a team's own handicap_home/away
    # at exactly the +0.5 line is the SAME bet as a double_chance
    # outcome, not just correlated with it -- home covers +0.5 iff
    # home_goals + 0.5 > away_goals, i.e. home_goals >= away_goals (home
    # doesn't lose), which is exactly double_chance "1x" (home or draw);
    # likewise handicap_away's own +0.5 is exactly "x2" (draw or away).
    # Tracking both separately would calibrate the identical real-world
    # event twice under two different labels -- "1x"/"x2" themselves
    # stay tracked (only this one redundant handicap line is dropped).
    ("handicap_home", "0.5"),
    ("handicap_away", "0.5"),
}


def actual_outcome_hit(market: str, outcome: str, home_goals: int, away_goals: int) -> bool | None:
    """Whether ``market``/``outcome`` actually happened, given the final
    score -- or ``None`` when that market can't be judged from the score
    alone (e.g. correct score, half-time result)."""
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

    # handicap_home/handicap_away: unlike every market above, the line
    # lives in the *outcome* (e.g. market="handicap_home",
    # outcome="-1.5"), not the market key -- xGScore's own h1/h2 report
    # one outcome per Asian-handicap line it covers. A team covers its
    # own line L if its score, with L added, still beats the other
    # side's -- e.g. home covers -1.5 only by winning by 2+ goals.
    if market in ("handicap_home", "handicap_away"):
        try:
            line = float(outcome)
        except (TypeError, ValueError):
            return None
        if market == "handicap_home":
            return (home_goals + line) > away_goals
        return (away_goals + line) > home_goals

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
class CalibrationBucket:
    market: str  # exact market key, e.g. "over_under_2.5" -- NOT the stripped-line family, see module docstring
    outcome: str
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
) -> dict[tuple[str, str], list[tuple[float, bool]]]:
    """One list of ``(predicted_probability, did_it_hit)`` per (exact
    market, outcome) -- kept fully separate per outcome AND per exact
    market/line (see the module docstring), pooling every value-bet
    entry across every paired game whose outcome ``actual_outcome_hit``
    can actually judge, that isn't in ``_EXCLUDED_MARKET_OUTCOMES``, and
    that isn't a whole-number over/under or handicap line (see
    ``_is_whole_number_line``/``_is_whole_number_handicap``).
    """
    rows: dict[tuple[str, str], list[tuple[float, bool]]] = {}
    for game, result in paired:
        for v in game.value_bets:
            if (v.market, v.outcome) in _EXCLUDED_MARKET_OUTCOMES:
                continue
            if _is_whole_number_line(v.market) or _is_whole_number_handicap(v.market, v.outcome):
                continue
            hit = actual_outcome_hit(v.market, v.outcome, result.home_goals, result.away_goals)
            if hit is None:
                continue
            rows.setdefault((v.market, v.outcome), []).append((v.probability, hit))
    return rows


def compute_calibration(paired: list[tuple[MatchedGame, MatchResult]]) -> list[CalibrationBucket]:
    """One row per (exact market, outcome, predicted-probability
    decile) -- see the module docstring for why this is the only
    aggregate reported (a single hit-rate pooled across every outcome,
    line, and/or probability level would be mathematically meaningless
    or hide real per-line differences for most markets here).

    Sorted by market, then outcome, then by probability band
    descending (highest confidence first within each market+outcome)
    -- that ordering matches what this is actually used for: "é mais
    seguro apostar quando a probabilidade está acima de X%", read
    top-down per market+outcome.
    """
    buckets_rows: dict[tuple[str, str, str], list[tuple[float, bool]]] = {}
    for (market, outcome), rows in _collect_rows(paired).items():
        for probability, hit in rows:
            key = (market, outcome, _bucket_label(probability))
            buckets_rows.setdefault(key, []).append((probability, hit))

    buckets = []
    for (market, outcome, bucket_label), rows in buckets_rows.items():
        count = len(rows)
        hits = sum(1 for _, hit in rows if hit)
        avg_prob = sum(p for p, _ in rows) / count
        buckets.append(CalibrationBucket(market, outcome, bucket_label, count, hits, avg_prob))
    buckets.sort(key=lambda b: (b.market, b.outcome, -int(b.probability_bucket.split("-")[0])))
    return buckets


def calibrated_probability(
    market: str,
    outcome: str,
    probability: float,
    buckets: list[CalibrationBucket],
    min_sample_size: int = DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE,
) -> tuple[float | None, int | None]:
    """Look up ``market``/``outcome``/``probability``'s own (exact
    market, outcome, probability band) in the already-computed
    ``buckets`` and return ``(actual_hit_rate, count)`` -- but only
    once that band has at least ``min_sample_size`` games behind it;
    otherwise ``(None, None)``, so a caller falls back to the model's
    own raw ``probability`` rather than adjusting it on a handful of
    noisy games. See ``valuebets.compute_value_bets``, the caller that
    actually uses this to compute ``value_ratio``/``edge``.
    """
    bucket_label = _bucket_label(probability)
    for b in buckets:
        if b.market == market and b.outcome == outcome and b.probability_bucket == bucket_label:
            if b.count >= min_sample_size:
                return b.actual_hit_rate, b.count
            return None, None
    return None, None


def load_accumulated_calibration(data_dir: Path, min_confidence: float = 80.0) -> list[CalibrationBucket]:
    """Scan every already-saved ``data/<day>/{games,results}.json`` pair
    on disk and compute today's calibration buckets from it -- no
    scraping (see ``cli.calibrate`` for that, which is what actually
    puts new ``results.json`` files on disk in the first place). This
    is what lets each new day's own picks automatically benefit from
    everything accumulated so far, with no manual step: ``pipeline.
    run_daily`` calls this before computing that day's value bets.
    """
    from .storage import load_day, load_results  # local import: avoids a needless import cycle risk

    paired: list[tuple[MatchedGame, MatchResult]] = []
    for day_str in sorted(p.parent.name for p in data_dir.glob("*/games.json")):
        day = datetime.strptime(day_str, "%Y-%m-%d").date()
        games = load_day(day, data_dir)
        if not games:
            continue
        results = load_results(day, data_dir)
        if not results:
            continue
        paired.extend(match_games_to_results(games, results, min_confidence=min_confidence))
    return compute_calibration(paired)
