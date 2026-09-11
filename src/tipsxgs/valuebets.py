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

from .markets import full_label
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
    ``value_ratio`` descending -- the "top opportunities today" view."""
    pairs = [
        (game, entry)
        for game in games
        for entry in game.value_bets
        if entry.is_value_bet
    ]
    pairs.sort(key=lambda p: p[1].value_ratio, reverse=True)
    return pairs[:limit]
