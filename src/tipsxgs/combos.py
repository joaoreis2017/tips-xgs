"""Combo bets: two independent xGScore markets multiplied together.

Explicitly requested (2026-11-05): "dupla hipótese + total de golos" (1X/12/X2
crossed with over/under at every line xGScore reports) and "resultado + total
de golos" (casa/fora -- deliberately *not* empate -- crossed with the same
lines). xGScore never reports these combos directly, but since the two
underlying markets are independent, the combined probability is just their
product.

Betclic *does* sell matching markets for real money, but getting their odds
requires code this project doesn't have yet (the page only reveals them
after a client-side interaction our scraper doesn't perform -- see
docs/CALIBRATION.md's "Resultado/Golos" discussion). Rather than block on
that, this intentionally produces probability-only ``ValueBetEntry`` rows
(``odd``/``value_ratio`` always ``None``) for the user to match against a
real odd by hand -- a separate, clearly-labelled view, not merged into
``MatchedGame.value_bets`` (which stays exactly as it already was: every
other section of the dashboard is unaffected).
"""

from __future__ import annotations

import re

from .models import MatchedGame, ValueBetEntry

_OVER_UNDER_LINE_RE = re.compile(r"^over_under_(?P<line>\d+(?:\.\d+)?)$")

_DOUBLE_CHANCE_SHORT: dict[str, str] = {"1x": "1X", "12": "12", "x2": "X2"}
_RESULT_SHORT: dict[str, str] = {"home": "Casa", "away": "Fora"}
_DIRECTION_LABEL: dict[str, str] = {"over": "Mais de", "under": "Menos de"}


def compute_combo_entries(game: MatchedGame) -> list[ValueBetEntry]:
    """Every "dupla hipótese + golos" / "resultado + golos" combo this
    game's xGScore probabilities can produce, sorted by probability
    descending. Returns ``[]`` when the prediction is missing either the
    double_chance/1x2 side or any over_under_<line> side (nothing to
    multiply).
    """
    if game.prediction is None:
        return []
    markets = game.prediction.markets

    double_chance = markets.get("double_chance", {})
    result = markets.get("1x2", {})
    if not double_chance and not result:
        return []

    lines: list[tuple[str, dict[str, float]]] = []
    for market, outcomes in markets.items():
        m = _OVER_UNDER_LINE_RE.match(market)
        if m and outcomes:
            lines.append((m.group("line"), outcomes))
    lines.sort(key=lambda pair: float(pair[0]))

    entries: list[ValueBetEntry] = []
    for line, totals in lines:
        for direction, total_prob in totals.items():
            direction_label = _DIRECTION_LABEL.get(direction)
            if direction_label is None:
                continue  # not "over"/"under" -- ignore anything unexpected

            for dc_outcome, dc_prob in double_chance.items():
                short = _DOUBLE_CHANCE_SHORT.get(dc_outcome)
                if short is None:
                    continue
                entries.append(
                    ValueBetEntry(
                        market=f"double_chance_total_{line}",
                        outcome=f"{dc_outcome}_{direction}",
                        label=f"{short} & {direction_label} {line}",
                        probability=dc_prob * total_prob,
                    )
                )

            # Deliberately home/away only -- "resultado + golos" excludes
            # the draw (see module docstring).
            for side in ("home", "away"):
                side_prob = result.get(side)
                if side_prob is None:
                    continue
                entries.append(
                    ValueBetEntry(
                        market=f"result_total_{line}",
                        outcome=f"{side}_{direction}",
                        label=f"{_RESULT_SHORT[side]} & {direction_label} {line}",
                        probability=side_prob * total_prob,
                    )
                )

    entries.sort(key=lambda e: e.probability, reverse=True)
    return entries
