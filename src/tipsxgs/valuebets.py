"""Compare xGScore's model probabilities against Betclic's odds.

For every outcome the model gave a probability for, we compute:

* ``implied_probability`` = 1 / odd -- what the odd itself implies.
* ``fair_probability`` = implied_probability, rescaled to remove the
  bookmaker's overround (margin), *when every outcome of that market has
  an odd* (otherwise we can't compute the market's overround, so we fall
  back to the raw implied probability).
* ``edge`` = effective probability - fair (or implied) probability.
  Positive means the model thinks the event is more likely than the
  market does.
* ``value_ratio`` = effective probability * odd. This is the number
  from the user's own example: probability 0.70 and odd 2.00 ->
  value_ratio 1.40, i.e. a 40% edge over a fair bet (value_ratio == 1
  is break-even; > 1 is a positive-EV / "high value" bet).

"Effective probability" (see ``ValueBetEntry.effective_probability``)
is ``calibrated_probability`` when ``calibration_buckets`` is given and
has enough accumulated history for this exact market+outcome+band (see
``calibration.calibrated_probability``), otherwise the model's own raw
``probability`` -- explicitly requested (2026-11-14): once there's
enough real-world track record for a market/band, the money math
(``edge``/``value_ratio``, and therefore which bets clear
``min_value_ratio`` in the daily bet plan below) should reflect what
has actually happened, not just what the model itself claims. The raw
``probability`` field is NEVER overridden by this -- every band/
threshold filter in this module (``top_probability_bets_today`` and
everything built on it) keeps reading the model's own stated number,
unchanged.

Every outcome is also ranked by raw model probability across the whole
match (1 = most likely single event in the game, regardless of market),
which is exactly the "ordem de acontecimentos com maior para menor
probabilidade" view requested.
"""

from __future__ import annotations

from typing import Callable

from .calibration import CalibrationBucket, DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE, calibrated_probability
from .markets import full_label, market_family
from .models import MatchedGame, ValueBetEntry


def _build_value_bet_entries(
    game: MatchedGame,
    calibration_buckets: list[CalibrationBucket] | None,
    min_sample_size: int,
) -> list[ValueBetEntry]:
    """Shared body behind both ``compute_value_bets`` (gated at
    ``DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE``, the production threshold)
    and ``compute_real_rate_value_bets`` (gated at 1, i.e. any amount of
    history at all) -- everything is identical except which
    ``min_sample_size`` gets passed down to ``calibrated_probability``.
    """
    if game.prediction is None or not game.prediction.markets:
        return []

    odds_markets = game.odds.markets if game.odds else {}

    # Overround per market, only where every outcome has an odd.
    fair_probabilities: dict[str, dict[str, float]] = {}
    for market, model_outcomes in game.prediction.markets.items():
        offered = odds_markets.get(market, {})
        if not offered or set(model_outcomes) - set(offered):
            continue  # missing at least one outcome's odd -> can't normalize
        implied = {outcome: 1.0 / odd for outcome, odd in offered.items() if odd > 0}
        overround = sum(implied.values())
        if overround <= 0:
            continue
        fair_probabilities[market] = {o: v / overround for o, v in implied.items()}

    entries: list[ValueBetEntry] = []
    for market, outcomes in game.prediction.markets.items():
        offered = odds_markets.get(market, {})
        for outcome, probability in outcomes.items():
            odd = offered.get(outcome)

            calib_probability: float | None = None
            calib_sample_size: int | None = None
            if calibration_buckets:
                calib_probability, calib_sample_size = calibrated_probability(
                    market, outcome, probability, calibration_buckets, min_sample_size=min_sample_size
                )
            effective_probability = calib_probability if calib_probability is not None else probability

            implied_probability = (1.0 / odd) if odd and odd > 0 else None
            fair_probability = fair_probabilities.get(market, {}).get(outcome, implied_probability)
            edge = (effective_probability - fair_probability) if fair_probability is not None else None
            value_ratio = (effective_probability * odd) if odd else None

            entries.append(
                ValueBetEntry(
                    market=market,
                    outcome=outcome,
                    label=full_label(market, outcome),
                    probability=probability,
                    odd=odd,
                    implied_probability=implied_probability,
                    fair_probability=fair_probability,
                    edge=edge,
                    value_ratio=value_ratio,
                    calibrated_probability=calib_probability,
                    calibration_sample_size=calib_sample_size,
                )
            )

    entries.sort(key=lambda e: e.probability, reverse=True)
    for rank, entry in enumerate(entries, start=1):
        entry.rank_by_probability = rank
    return entries


def compute_value_bets(
    game: MatchedGame,
    value_bet_threshold: float = 1.0,
    calibration_buckets: list[CalibrationBucket] | None = None,
) -> list[ValueBetEntry]:
    """Populate and return ``game.value_bets`` -- ``calibrated_probability``
    only kicks in once a market+outcome+band has the full
    ``DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE`` (the production threshold:
    see calibration.py's module docstring)."""
    game.value_bets = _build_value_bet_entries(game, calibration_buckets, DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE)
    return game.value_bets


def compute_real_rate_value_bets(
    game: MatchedGame,
    calibration_buckets: list[CalibrationBucket] | None,
) -> list[ValueBetEntry]:
    """Same per-entry computation as ``compute_value_bets``, but
    ``calibrated_probability``/``calibration_sample_size`` get populated
    as soon as there is ANY historical sample for that exact
    market+outcome+band (``min_sample_size=1``), not only once it clears
    the 30-game production threshold. Explicitly requested (2026-11-17):
    a second, parallel view ("apostas por taxa real") that selects and
    ranks bets by the real observed hit rate instead of the model's own
    probability, showing every band that has at least some track record
    -- flagged as still-provisional below 30 games, confirmed at or
    above it -- rather than only the production-ready ones. Returns a
    fresh list; does NOT touch ``game.value_bets`` (the model-probability
    page keeps working exactly as before)."""
    return _build_value_bet_entries(game, calibration_buckets, min_sample_size=1)


def compute_all(
    games: list[MatchedGame],
    value_bet_threshold: float = 1.0,
    calibration_buckets: list[CalibrationBucket] | None = None,
) -> list[MatchedGame]:
    for game in games:
        compute_value_bets(game, value_bet_threshold=value_bet_threshold, calibration_buckets=calibration_buckets)
    return games


def top_value_bets_today(games: list[MatchedGame], limit: int = 15) -> list[tuple[MatchedGame, ValueBetEntry]]:
    """Flatten every game's value bets into one list sorted by
    ``value_ratio`` descending -- the "top opportunities today" view.

    Requires a matched Betclic odd (``is_value_bet`` implies one), so a
    game with no paired offer never shows up here -- see
    ``top_probability_bets_today`` for the odds-optional counterpart.
    """
    pairs = [
        (game, entry)
        for game in games
        for entry in game.value_bets
        if entry.is_value_bet
    ]
    pairs.sort(key=lambda p: p[1].value_ratio, reverse=True)
    return pairs[:limit]


def _rounded_percent(probability: float) -> int:
    """The whole-percent value the dashboard actually displays for a
    probability (``"%.0f"|format(probability * 100)`` in the template).
    Bucketing by this, rather than by the raw float, means a probability
    like 0.669 -- which *displays* as "67%" -- lands in whichever band
    that displayed figure belongs to, instead of silently falling
    through a gap between a "> 0.66" and a ">= 0.67" raw-float check."""
    return round(probability * 100)


def top_probability_bets_today(
    games: list[MatchedGame],
    min_probability: float = 0.5,
    max_probability: float | None = None,
    min_odd: float | None = None,
    max_odd: float | None = None,
    odd_bounds_inclusive: bool = False,
    limit: int | None = None,
    coverable_markets: set[str] | None = None,
    probability_of: Callable[[ValueBetEntry], float | None] | None = None,
    entries_of: Callable[[MatchedGame], list[ValueBetEntry]] | None = None,
) -> list[tuple[MatchedGame, ValueBetEntry]]:
    """Flatten every game's events into one list of model-probability
    "high confidence" picks, sorted by probability descending.

    Unlike ``top_value_bets_today``, this does *not* require a matched
    Betclic odd at all -- a game xGScore has predictions for shows up
    here even with no Betclic offer paired (odd/value just come back
    ``None`` for those entries), covering every game rather than only
    the ones with odds to compare against. ``min_odd``/``max_odd``
    (below) are the one exception to that -- when either is given, an
    odd becomes required again.

    ``min_probability``/``max_probability`` bound an inclusive band (by
    displayed whole-percent, see ``_rounded_percent``) -- e.g.
    ``min_probability=0.67`` keeps everything showing "67%" or higher;
    ``min_probability=0.34, max_probability=0.66`` keeps only "34%"
    through "66%". ``max_probability=None`` (the default) leaves the
    band open-ended at the top. Explicitly requested: splitting the
    single cross-game list into separate high-confidence and
    mid-confidence bands -- call this twice, once per band, and render
    each as its own panel (see ``report.build_context``).

    ``min_odd``/``max_odd`` (both ``None`` by default) additionally
    bound an odd range -- explicitly requested for both bands, each
    with its own bounds and its own inclusivity: the high-confidence
    band's is *exclusive* ("odd acima de 1.25 e abaixo de 1.45" --
    ``odd_bounds_inclusive=False``, the default), the mid-confidence
    band's is *inclusive* ("odd superior a 1.5 e inferior a 2.2,
    inclusive para os 2" -- ``odd_bounds_inclusive=True``). An entry
    needs odd > min_odd (or >= when inclusive) AND odd < max_odd (or <=
    when inclusive) to survive, and -- unlike every other filter here
    -- this now *requires* a matched odd at all once either bound is
    given: an odd-less entry is dropped outright rather than kept with
    odd/value_ratio as "—", since the whole point of this filter is to
    only show entries whose odd falls in that specific window.

    ``coverable_markets``, when given, additionally drops any odd-less
    entry whose market *family* (see ``markets.market_family`` -- e.g.
    ``over_under_2.5`` and ``over_under_1.5`` are both family
    ``over_under``) isn't in that set -- e.g. handicap or per-team-total
    lines that config.yaml's betclic section has *no extraction rule for
    at all* (only 1x2/btts/over_under are, as of writing), so they could
    never be paired with a real odd no matter how good the
    fixture<->offer matching is -- a permanent, structural gap rather
    than "not matched yet". Left unfiltered, these near-certain lines
    (handicap_home/away, home_total_<line>/away_total_<line>) tend to
    sit at 100% probability and flood the top of this list with entries
    that can never show an odd, crowding out the ones that actually
    could. Pass the set from ``pipeline._betclic_coverable_markets`` --
    an odd-less entry for a market family Betclic *is* calibrated for
    still shows up (that one's just unmatched for this game, or a line
    Betclic doesn't happen to offer this time), only
    structurally-uncoverable *families* get dropped. An entry that
    already has an odd is never affected by this (nor, obviously, by
    min_odd/max_odd once it's already in range).

    ``limit`` is ``None`` (no cap) by default -- explicitly requested:
    *every* event clearing the band across *every* game should show up,
    not just a top-N slice that would otherwise squeeze out most games
    once there are dozens of them each with several qualifying markets.
    Pass a number to cap it if the list ever needs trimming for display
    reasons.

    ``probability_of``/``entries_of`` (explicitly requested, 2026-11-17,
    for the "apostas por taxa real" page) let a caller swap in a
    different probability to filter/sort by -- e.g. ``lambda e:
    e.calibrated_probability`` to rank by the real observed hit rate
    instead of the model's own number -- and/or a different per-game
    entry list -- e.g. one built by ``compute_real_rate_value_bets``,
    which populates ``calibrated_probability`` for any band with at
    least one historical game, not just the production-ready ones.
    Default to the model's raw ``probability`` and ``game.value_bets``,
    i.e. today's existing behaviour, when omitted. An entry whose
    ``probability_of`` comes back ``None`` (no historical data at all,
    when using the calibrated one) is skipped outright, never silently
    falling back to another number.
    """
    get_probability = probability_of or (lambda e: e.probability)
    get_entries = entries_of or (lambda g: g.value_bets)
    min_pct = _rounded_percent(min_probability)
    max_pct = _rounded_percent(max_probability) if max_probability is not None else None

    def _odd_in_range(entry: ValueBetEntry) -> bool:
        if min_odd is None and max_odd is None:
            return True
        if entry.odd is None:
            return False
        if odd_bounds_inclusive:
            return (min_odd is None or entry.odd >= min_odd) and (max_odd is None or entry.odd <= max_odd)
        return (min_odd is None or entry.odd > min_odd) and (max_odd is None or entry.odd < max_odd)

    pairs = []
    for game in games:
        for entry in get_entries(game):
            probability = get_probability(entry)
            if probability is None:
                continue
            pct = _rounded_percent(probability)
            if pct < min_pct or (max_pct is not None and pct > max_pct):
                continue
            if not _odd_in_range(entry):
                continue
            if entry.odd is None and coverable_markets is not None and market_family(entry.market) not in coverable_markets:
                continue
            pairs.append((game, entry))
    pairs.sort(key=lambda p: get_probability(p[1]), reverse=True)
    return pairs if limit is None else pairs[:limit]


# --- Daily bet plan -----------------------------------------------------
#
# Explicitly requested (2026-09-18): stop showing candidate lists the
# user has to pick from -- split every event into the stakes the user
# actually places each day (originally a small multiple plus two single
# bets at two different stake sizes), each governed by its own fixed
# probability/odd band. Same games.json in, same output out every time --
# no randomness anywhere below.
#
# CHANGED (2026-09-29, explicitly requested): every function here used to
# additionally narrow its band down to one single "best" pick (by
# value_ratio) -- reversed back to listing *every* candidate within the
# band, sorted by probability descending, so nothing within the
# already-configured parameters is hidden. The bands/parameters
# themselves are unchanged; only "and then pick just one" was removed.
# Dropped along with it: max_legs (the multiple no longer caps how many
# legs it shows) and exclude_fixture_ids (the sections no longer hide a
# fixture from one another just because another section also listed it
# -- each section is a complete, independent view of its own band).
#
# CHANGED (2026-10-06, explicitly requested): the band-unrestricted
# "0.50€ apostas de valor" single (pick_value_bets) was removed
# entirely -- too many low-value entries slipped through. The two
# remaining sections (multiple, mid-band single) now additionally
# require value_ratio >= 1.0 (inclusive) via each function's own
# min_value_ratio param, on top of their existing probability/odd bands.

BetPick = tuple[MatchedGame, ValueBetEntry]


def pick_multiple_legs(
    games: list[MatchedGame],
    min_probability: float,
    min_odd: float,
    max_odd: float,
    min_value_ratio: float = 1.0,
    coverable_markets: set[str] | None = None,
    probability_of: Callable[[ValueBetEntry], float | None] | None = None,
    entries_of: Callable[[MatchedGame], list[ValueBetEntry]] | None = None,
) -> list[BetPick]:
    """Every candidate leg for the daily multiple/parlay: entries
    clearing ``min_probability`` with a matched odd between
    ``min_odd``/``max_odd`` (the "safe, moderate-odd" shape of the
    dashboard's high-confidence band -- see ``top_probability_bets_today``)
    AND a ``value_ratio`` of at least ``min_value_ratio``, sorted by
    probability descending. All three bounds are inclusive (explicitly
    requested 2026-10-12: "todos os valores inclusive" -- CHANGED from
    the odd range's previous exclusive bounds). At most ONE leg per
    fixture (two outcomes of the *same* match aren't independent, so
    combining them into one multiple would misrepresent
    ``multiple_combined_odd``/``multiple_combined_probability`` below) --
    when a fixture has more than one qualifying outcome, the one with
    the higher ``value_ratio`` wins that fixture's slot.

    ``probability_of``/``entries_of`` pass straight through to
    ``top_probability_bets_today`` -- see there (used by the "apostas por
    taxa real" page to rank by the real observed hit rate instead).
    """
    candidates = top_probability_bets_today(
        games,
        min_probability=min_probability,
        min_odd=min_odd,
        max_odd=max_odd,
        odd_bounds_inclusive=True,
        coverable_markets=coverable_markets,
        probability_of=probability_of,
        entries_of=entries_of,
    )
    candidates = [
        (game, entry)
        for game, entry in candidates
        if entry.value_ratio is not None and entry.value_ratio >= min_value_ratio
    ]

    best_per_fixture: dict[str, BetPick] = {}
    for game, entry in candidates:
        current = best_per_fixture.get(game.fixture.id)
        if current is None or (entry.value_ratio or 0.0) > (current[1].value_ratio or 0.0):
            best_per_fixture[game.fixture.id] = (game, entry)

    get_probability = probability_of or (lambda e: e.probability)
    legs = list(best_per_fixture.values())
    legs.sort(key=lambda pair: get_probability(pair[1]), reverse=True)
    return legs


def multiple_combined_odd(legs: list[BetPick]) -> float | None:
    """Product of every leg's own odd -- the odd the multiple itself
    pays out at (assuming, as any bookmaker's own multiple bet does,
    that every leg wins)."""
    if not legs:
        return None
    odd = 1.0
    for _, entry in legs:
        odd *= entry.odd
    return odd


def multiple_combined_probability(
    legs: list[BetPick],
    probability_of: Callable[[ValueBetEntry], float | None] | None = None,
) -> float | None:
    """Product of every leg's own probability -- the model's own
    estimate of the whole multiple landing, *assuming the legs are
    independent* (picking at most one leg per fixture, enforced by
    ``pick_multiple_legs``, is what makes that assumption reasonable --
    two outcomes of the same match are never independent). Pass
    ``probability_of`` (e.g. ``lambda e: e.calibrated_probability``) to
    get the combined REAL probability instead -- used by the "apostas
    por taxa real" page."""
    if not legs:
        return None
    get_probability = probability_of or (lambda e: e.probability)
    probability = 1.0
    for _, entry in legs:
        probability *= get_probability(entry)
    return probability


def pick_band_bets(
    games: list[MatchedGame],
    min_probability: float,
    max_probability: float | None,
    min_odd: float,
    max_odd: float,
    odd_bounds_inclusive: bool = True,
    min_value_ratio: float = 1.0,
    coverable_markets: set[str] | None = None,
    probability_of: Callable[[ValueBetEntry], float | None] | None = None,
    entries_of: Callable[[MatchedGame], list[ValueBetEntry]] | None = None,
) -> list[BetPick]:
    """Every entry within one probability/odd band (see
    ``top_probability_bets_today``, which already sorts by probability
    descending) AND a ``value_ratio`` of at least ``min_value_ratio``
    (explicitly requested: "nestas duas secções apenas quero as apostas
    de valor maior ou igual a 1.00x") -- used for a section that should
    only show bets from a specific confidence band (e.g. "60%-69%, odd
    1.5-2.2"). ``probability_of``/``entries_of`` pass straight through
    to ``top_probability_bets_today`` -- see there.
    """
    candidates = top_probability_bets_today(
        games,
        min_probability=min_probability,
        max_probability=max_probability,
        min_odd=min_odd,
        max_odd=max_odd,
        odd_bounds_inclusive=odd_bounds_inclusive,
        coverable_markets=coverable_markets,
        probability_of=probability_of,
        entries_of=entries_of,
    )
    return [
        (game, entry)
        for game, entry in candidates
        if entry.value_ratio is not None and entry.value_ratio >= min_value_ratio
    ]
