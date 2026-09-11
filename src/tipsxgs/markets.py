"""Canonical market/outcome taxonomy.

Both xGScore (probabilities) and Betclic (odds) use their own internal
naming for markets and outcomes. Rather than hardcoding site-specific
strings deep in the scraping code, every scraper normalizes whatever it
extracts into this canonical vocabulary using an *alias map* defined in
``config.yaml`` (see ``xgscore.market_aliases`` / ``betclic.market_aliases``).

That keeps calibration (matching real site output to canonical markets)
entirely in configuration -- no code changes needed when you inspect the
real pages and fill in the raw key names.

A canonical key is ``"<market>.<outcome>"``, e.g. ``"1x2.home"``,
``"btts.yes"``, ``"over_under_2.5.over"``, ``"correct_score.2-1"``.
"""

from __future__ import annotations

# Human readable (PT-PT) labels for known markets/outcomes. Anything not
# listed here still works -- it just falls back to a title-cased version of
# the raw key so new/unknown markets degrade gracefully instead of breaking.
MARKET_LABELS: dict[str, str] = {
    "1x2": "Resultado Final",
    "double_chance": "Dupla Hipótese",
    "btts": "Ambas Marcam",
    "over_under_0.5": "Mais/Menos de 0.5 Golos",
    "over_under_1.5": "Mais/Menos de 1.5 Golos",
    "over_under_2.5": "Mais/Menos de 2.5 Golos",
    "over_under_3.5": "Mais/Menos de 3.5 Golos",
    "over_under_4.5": "Mais/Menos de 4.5 Golos",
    "half_time_result": "Resultado ao Intervalo",
    "correct_score": "Resultado Exato",
    "team_to_score_first": "Primeiro a Marcar",
    "goals_odd_even": "Total de Golos Par/Ímpar",
    "clean_sheet_home": "Casa Não Sofre Golo",
    "clean_sheet_away": "Fora Não Sofre Golo",
    "total_goals_exact": "Número Exato de Golos",
    "asian_handicap": "Handicap Asiático",
}

OUTCOME_LABELS: dict[str, str] = {
    "home": "Casa",
    "draw": "Empate",
    "away": "Fora",
    "yes": "Sim",
    "no": "Não",
    "over": "Mais",
    "under": "Menos",
    "1x": "Casa ou Empate",
    "12": "Casa ou Fora",
    "x2": "Empate ou Fora",
    "odd": "Ímpar",
    "even": "Par",
    "none": "Nenhuma",
}


def market_label(market: str) -> str:
    return MARKET_LABELS.get(market, market.replace("_", " ").title())


def outcome_label(market: str, outcome: str) -> str:
    return OUTCOME_LABELS.get(outcome, outcome.replace("_", " ").title())


def full_label(market: str, outcome: str) -> str:
    return f"{market_label(market)} - {outcome_label(market, outcome)}"


def normalize_markets(
    raw: dict[str, float], alias_map: dict[str, str]
) -> dict[str, dict[str, float]]:
    """Turn ``{raw_key: value}`` into ``{market: {outcome: value}}``.

    ``alias_map`` maps a raw key exactly as scraped (a CSS-extracted field
    name, or a dotted JSON path resolved by the extractor) to a canonical
    ``"market.outcome"`` string, e.g.::

        {"prob_home_win": "1x2.home", "btts_yes_pct": "btts.yes"}

    Raw keys with no alias are dropped silently (they're usually page
    chrome / unrelated numbers) -- run ``scripts/inspect_site.py`` and
    extend the alias map in ``config.yaml`` if a market you care about is
    missing from the output.
    """
    out: dict[str, dict[str, float]] = {}
    for raw_key, value in raw.items():
        canonical = alias_map.get(raw_key)
        if not canonical or "." not in canonical:
            continue
        # rsplit, not split: the *market* half can itself contain a dot
        # (e.g. "over_under_2.5.over" -> market "over_under_2.5", outcome
        # "over") -- only the outcome (the last segment) never does.
        market, outcome = canonical.rsplit(".", 1)
        out.setdefault(market, {})[outcome] = value
    return out


def merge_markets(*market_maps: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    merged: dict[str, dict[str, float]] = {}
    for mm in market_maps:
        for market, outcomes in mm.items():
            merged.setdefault(market, {}).update(outcomes)
    return merged
