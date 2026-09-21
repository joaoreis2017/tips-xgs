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


# A period-abbreviated token's letters (minus the dot) must be at least
# this long before we'll treat it as a stand-in for a longer word on the
# other side -- see _expand_abbreviated_tokens. Below this length ("c.",
# "r.", "k.", ...) far too many unrelated words share the same first
# letter or two, so the check would stop being a reliable abbreviation
# signal and start being a coincidence generator.
_MIN_ABBREVIATION_STEM_LEN = 3


def _expand_abbreviated_tokens(a: str, b: str) -> tuple[str, str]:
    """Rewrite any period-abbreviated token in ``a`` or ``b`` (e.g.
    "indep.", "dep.") into its full counterpart from the *other* string,
    when that counterpart is a genuine, unique prefix match -- e.g.
    "indep." + "independiente" -> both become "independiente" before the
    fuzzy scorers below ever see them.

    Real case (2026-09-21): "Barracas C. vs Indep. R." (xGScore) against
    "Barracas Central vs Independiente Rivadavia" (Betclic) scored only
    68 via token_sort/token_set_ratio -- clearly the same match, but
    below any sane min_confidence, because those scorers compare
    abbreviated and fully-spelled tokens as if they were just two
    unrelated words. Expanding "indep." -> "independiente" alone lifts
    token_set_ratio from ~63 to ~89.

    Deliberately narrow, unlike the briefly-tried (and reverted, see
    below) ``fuzz.WRatio``: a token only expands when it ends with "."
    AND its stem is >= ``_MIN_ABBREVIATION_STEM_LEN`` chars AND exactly
    one token on the other side starts with that stem -- a real
    abbreviation essentially never collides with an unrelated team's
    name under those three conditions together, so this can't turn two
    genuinely different fixtures into a false-positive match the way
    WRatio did.
    """

    def _expand(tokens: list[str], other_tokens: list[str]) -> str:
        expanded = []
        for tok in tokens:
            stem = tok[:-1]
            if tok.endswith(".") and len(stem) >= _MIN_ABBREVIATION_STEM_LEN:
                matches = [o for o in other_tokens if o != tok and o.startswith(stem)]
                expanded.append(matches[0] if len(matches) == 1 else tok)
            else:
                expanded.append(tok)
        return " ".join(expanded)

    a_tokens, b_tokens = a.split(), b.split()
    return _expand(a_tokens, b_tokens), _expand(b_tokens, a_tokens)


def _score(fixture: Fixture, offer: OddsOffer) -> float:
    fixture_key = _pair_key(fixture.home_team, fixture.away_team)
    offer_key = _pair_key(offer.home_team, offer.away_team)
    exp_fixture, exp_offer = _expand_abbreviated_tokens(fixture_key, offer_key)

    same_order = fuzz.token_sort_ratio(exp_fixture, exp_offer)
    # Also try home/away swapped, in case one source lists them reversed
    # (rare, but cheap to guard against).
    swapped_key = _pair_key(offer.away_team, offer.home_team)
    exp_fixture_swap, exp_swapped = _expand_abbreviated_tokens(fixture_key, swapped_key)
    swapped = fuzz.token_sort_ratio(exp_fixture_swap, exp_swapped)
    # token_set_ratio ignores extra/missing tokens instead of penalizing
    # them like token_sort_ratio does -- e.g. "Victoria G." vs "Vitoria
    # Guimaraes", or one source adding a "FC"/"CF"/city-name token the
    # other drops. It compares token *sets*, so home/away order doesn't
    # matter and a single call already covers both orders. Only helps
    # borderline abbreviation cases (we take the max), never hurts a
    # pair that already scored well on token_sort_ratio.
    token_set = fuzz.token_set_ratio(exp_fixture, exp_offer)
    # REVERTED (2026-09-14): briefly added fuzz.WRatio here too (rapidfuzz's
    # own blend of ratio/partial_ratio/token_sort/token_set) to fix a real
    # case -- "Dep. Riestra vs Lanus" against "Deportivo Riestra vs
    # Atletico Lanus" scored only 68 on token_sort/token_set, 85.5 on
    # WRatio. Reverted the same day: a live run's own data showed WRatio
    # scoring "Torino vs Roma" 85.5 against the *completely unrelated*
    # "Dynamo K. vs Epitsentr" (and several other genuinely different
    # fixtures) -- WRatio's partial_ratio-heavy blend for short,
    # length-mismatched strings produces false positives too often to
    # trust here. FIXED (2026-09-21) via the narrower
    # _expand_abbreviated_tokens above instead, which handles this exact
    # case (and the Barracas one) without WRatio's false-positive risk.
    score = max(same_order, swapped, token_set)

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

    # Best score seen for each fixture, even below threshold -- purely so
    # the log line below can tell "Betclic just doesn't have this game
    # today" (no candidate came close) apart from "it's there, but under
    # a different-enough name" (a close-but-rejected candidate), without
    # needing a second run with extra logging to find out which.
    best_for_fixture: dict[str, tuple[float, OddsOffer]] = {}
    for score, idx, fixture in candidates:
        current = best_for_fixture.get(fixture.id)
        if current is None or score > current[0]:
            best_for_fixture[fixture.id] = (score, odds_offers[idx])

    games = []
    for fixture in fixtures:
        offer_idx = assigned_offer_for_fixture.get(fixture.id)
        offer = odds_offers[offer_idx] if offer_idx is not None else None
        confidence = _score(fixture, offer) if offer else None
        if offer is None:
            best = best_for_fixture.get(fixture.id)
            if best is None:
                logger.info("no Betclic odds matched for %s (no Betclic offers scraped at all)", fixture.label)
            else:
                best_score, best_offer = best
                logger.info(
                    "no Betclic odds matched for %s (closest candidate: %s - %s, score %.0f < min_confidence %.0f)",
                    fixture.label,
                    best_offer.home_team,
                    best_offer.away_team,
                    best_score,
                    min_confidence,
                )
        games.append(
            MatchedGame(
                fixture=fixture,
                prediction=predictions.get(fixture.id),
                odds=offer,
                match_confidence=confidence,
            )
        )
    return games
