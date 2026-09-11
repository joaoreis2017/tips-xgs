"""Pair xGScore fixtures (+ their predictions) with Betclic odds offers.

Team names rarely match verbatim between two different sites (accents,
abbreviations, "FC" prefixes, etc.), so we fuzzy-match on the combined
"home vs away" string and require the kickoff date to line up (when both
sides have one) to avoid false positives between two same-named teams
playing on different days.
"""

from __future__ import annotations

import logging

from rapidfuzz import fuzz

from .models import Fixture, MatchedGame, OddsOffer, Prediction

logger = logging.getLogger(__name__)


def _pair_key(home: str, away: str) -> str:
    return f"{home.strip().lower()} vs {away.strip().lower()}"


def _score(fixture: Fixture, offer: OddsOffer) -> float:
    fixture_key = _pair_key(fixture.home_team, fixture.away_team)
    offer_key = _pair_key(offer.home_team, offer.away_team)

    same_order = fuzz.token_sort_ratio(fixture_key, offer_key)
    # Also try home/away swapped, in case one source lists them reversed
    # (rare, but cheap to guard against).
    swapped_key = _pair_key(offer.away_team, offer.home_team)
    swapped = fuzz.token_sort_ratio(fixture_key, swapped_key)
    score = max(same_order, swapped)

    if fixture.kickoff and offer.kickoff:
        if fixture.kickoff.date() == offer.kickoff.date():
            score += 5
        else:
            score -= 30  # different days: almost certainly not the same game

    return min(score, 100.0)


def match_fixtures_to_odds(
    fixtures: list[Fixture],
    predictions: dict[str, Prediction],
    odds_offers: list[OddsOffer],
    min_confidence: float = 80.0,
) -> list[MatchedGame]:
    """Return one :class:`MatchedGame` per fixture.

    Each Betclic offer is used at most once (greedy, highest score first)
    so two similarly-named fixtures don't both latch onto the same odds
    row. A fixture whose best candidate scores below ``min_confidence``
    is kept with ``odds=None`` -- it still shows up in the report (with
    just the probability ranking, no value bets) rather than being
    dropped silently.
    """
    remaining_offers = list(enumerate(odds_offers))
    candidates: list[tuple[float, int, Fixture]] = []
    for fixture in fixtures:
        for idx, offer in remaining_offers:
            candidates.append((_score(fixture, offer), idx, fixture))
    candidates.sort(key=lambda c: c[0], reverse=True)

    assigned_offer_for_fixture: dict[str, int] = {}
    used_offer_idx: set[int] = set()
    for score, idx, fixture in candidates:
        if score < min_confidence:
            continue
        if fixture.id in assigned_offer_for_fixture or idx in used_offer_idx:
            continue
        assigned_offer_for_fixture[fixture.id] = idx
        used_offer_idx.add(idx)

    games = []
    for fixture in fixtures:
        offer_idx = assigned_offer_for_fixture.get(fixture.id)
        offer = odds_offers[offer_idx] if offer_idx is not None else None
        confidence = _score(fixture, offer) if offer else None
        if offer is None:
            logger.info("no Betclic odds matched for %s", fixture.label)
        games.append(
            MatchedGame(
                fixture=fixture,
                prediction=predictions.get(fixture.id),
                odds=offer,
                match_confidence=confidence,
            )
        )
    return games
