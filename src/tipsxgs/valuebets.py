"""Compare xGScore's model probabilities against Betclic's odds.

For every outcome the model gave a probability for, we compute:

* ``implied_probability`` = 1 / odd -- what the odd itself implies.
* ``fair_probability`` = implied_probability, rescaled to remove the
  bookmaker's overround (margin), *when every outcome of that market has
  an odd* (otherwise we can't compute the market's overround, so we fall
  back to the raw implied probability).
* ``edge`` = model probability - fair (or implied) probability. Positive
  means the model thinks the event is more likely than the market does.
* ``value_ratio`` = model probability * odd. This is the number from the
  user's own example: probability 0.70 and odd 2.00 -> value_ratio 1.40,
  i.e. a 40% edge over a fair bet (value_ratio == 1 is break-even; > 1 is
  a positive-EV / "high value" bet).

Every outcome is also ranked by raw model probability across the whole
match (1 = most likely single event in the game, regardless of market),
which is exactly the "ordem de acontecimentos com maior para menor
probabilidade" view requested.
"""

from __future__ import annotations

from .markets import full_label, market_family
from .models import MatchedGame, ValueBetEntry


def compute_value_bets(game: MatchedGame, value_bet_threshold: float = 1.0) -> list[ValueBetEntry]:
    """Populate and return ``game.value_bets``."""
    if game.prediction is None or not game.prediction.markets:
        game.value_bets = []
        return game.value_bets

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
            implied_probability = (1.0 / odd) if odd and odd > 0 else None
            fair_probability = fair_probabilities.get(market, {}).get(outcome, implied_probability)
            edge = (probability - fair_probability) if fair_probability is not None else None
            value_ratio = (probability * odd) if odd else None

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
                )
            )

    entries.sort(key=lambda e: e.probability, reverse=True)
    for rank, entry in enumerate(entries, start=1):
        entry.rank_by_probability = rank

    game.value_bets = entries
    return entries


def compute_all(games: list[MatchedGame], value_bet_threshold: float = 1.0) -> list[MatchedGame]:
    for game in games:
        compute_value_bets(game, value_bet_threshold=value_bet_threshold)
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
    """
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

    pairs = [
        (game, entry)
        for game in games
        for entry in game.value_bets
        if _rounded_percent(entry.probability) >= min_pct
        and (max_pct is None or _rounded_percent(entry.probability) <= max_pct)
        and _odd_in_range(entry)
        and (
            entry.odd is not None
            or coverable_markets is None
            or market_family(entry.market) in coverable_markets
        )
    ]
    pairs.sort(key=lambda p: p[1].probability, reverse=True)
    return pairs if limit is None else pairs[:limit]


# --- Daily bet plan -----------------------------------------------------
#
# Explicitly requested (2026-09-18): stop showing candidate lists the
# user has to pick from -- have the model make every choice itself,
# deterministically, split into the three stakes the user actually
# places each day: a small multiple (several "safe" legs combined into
# one bet) and two single bets at two different stake sizes. Same
# games.json in, same picks out every time -- no randomness anywhere
# below.

BetPick = tuple[MatchedGame, ValueBetEntry]


def pick_multiple_legs(
    games: list[MatchedGame],
    min_probability: float,
    min_odd: float,
    max_odd: float,
    max_legs: int = 4,
    coverable_markets: set[str] | None = None,
) -> list[BetPick]:
    """Deterministically pick up to ``max_legs`` legs for a daily
    multiple/parlay: candidates are every entry clearing
    ``min_probability`` with a matched odd strictly between
    ``min_odd``/``max_odd`` (the same "safe, moderate-odd" shape as the
    dashboard's high-confidence band -- see
    ``top_probability_bets_today``). At most ONE leg per fixture (two
    outcomes of the *same* match aren't independent, so combining them
    into one multiple would misrepresent the combined odds/probability
    below); ties broken by ``value_ratio`` descending -- among equally
    "safe" legs, prefer the ones the model also rates as better value.
    Returns fewer than ``max_legs`` (down to zero) if that many
    distinct-fixture candidates simply aren't available today -- never
    pads with a leg that doesn't meet the bar.
    """
    candidates = top_probability_bets_today(
        games,
        min_probability=min_probability,
        min_odd=min_odd,
        max_odd=max_odd,
        odd_bounds_inclusive=False,
        coverable_markets=coverable_markets,
    )
    candidates = sorted(candidates, key=lambda pair: pair[1].value_ratio or 0.0, reverse=True)

    legs: list[BetPick] = []
    used_fixture_ids: set[str] = set()
    for game, entry in candidates:
        if game.fixture.id in used_fixture_ids:
            continue
        legs.append((game, entry))
        used_fixture_ids.add(game.fixture.id)
        if len(legs) >= max_legs:
            break
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


def multiple_combined_probability(legs: list[BetPick]) -> float | None:
    """Product of every leg's own model probability -- the model's own
    estimate of the whole multiple landing, *assuming the legs are
    independent* (picking at most one leg per fixture, enforced by
    ``pick_multiple_legs``, is what makes that assumption reasonable --
    two outcomes of the same match are never independent)."""
    if not legs:
        return None
    probability = 1.0
    for _, entry in legs:
        probability *= entry.probability
    return probability


def pick_best_single_bet(
    games: list[MatchedGame],
    min_probability: float = 0.0,
    min_value_ratio: float = 1.0,
    exclude_fixture_ids: set[str] | None = None,
) -> BetPick | None:
    """Deterministically pick the single BEST value bet across every
    game and market: the entry with the highest ``value_ratio`` that
    clears both ``min_probability`` and ``min_value_ratio``. Returns
    ``None`` when nothing qualifies rather than falling back to a worse
    pick -- an empty slot in the daily plan is more honest than forcing
    a bet that doesn't actually meet the bar that day.

    ``exclude_fixture_ids``, when given, skips fixtures already used
    elsewhere in the same day's plan (e.g. a leg already picked for the
    multiple) -- so the day's three stakes spread risk across different
    matches instead of the plan doubling up on the very same outcome.
    """
    candidates = [
        (game, entry)
        for game in games
        for entry in game.value_bets
        if entry.odd is not None
        and entry.value_ratio is not None
        and entry.probability >= min_probability
        and entry.value_ratio >= min_value_ratio
        and (exclude_fixture_ids is None or game.fixture.id not in exclude_fixture_ids)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[1].value_ratio)


def pick_best_band_single(
    games: list[MatchedGame],
    min_probability: float,
    max_probability: float | None,
    min_odd: float,
    max_odd: float,
    odd_bounds_inclusive: bool = True,
    coverable_markets: set[str] | None = None,
    exclude_fixture_ids: set[str] | None = None,
) -> BetPick | None:
    """Deterministically pick the single best-value entry within one
    probability/odd band (see ``top_probability_bets_today``) -- the
    band-restricted counterpart to ``pick_best_single_bet`` above, used
    for a stake that should come from a specific confidence band (e.g.
    "60%-69%, odd 1.5-2.2") rather than the single best bet anywhere.
    """
    candidates = top_probability_bets_today(
        games,
        min_probability=min_probability,
        max_probability=max_probability,
        min_odd=min_odd,
        max_odd=max_odd,
        odd_bounds_inclusive=odd_bounds_inclusive,
        coverable_markets=coverable_markets,
    )
    if exclude_fixture_ids:
        candidates = [(g, e) for g, e in candidates if g.fixture.id not in exclude_fixture_ids]
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[1].value_ratio or 0.0)
