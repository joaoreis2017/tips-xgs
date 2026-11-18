"""Render the daily HTML dashboard from a list of :class:`MatchedGame`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .calibration import DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE, CalibrationBucket
from .combos import compute_combo_entries
from .markets import full_label, market_family
from .models import MatchedGame
from .valuebets import (
    BetPick,
    compute_real_rate_value_bets,
    multiple_combined_odd,
    multiple_combined_probability,
    pick_band_bets,
    pick_multiple_legs,
)

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _fmt_kickoff(dt: datetime | None) -> str | None:
    return dt.strftime("%H:%M") if dt else None


def _pick_ctx(pick: BetPick | None) -> dict | None:
    if pick is None:
        return None
    game, entry = pick
    return {
        "game_slug": game.fixture.slug,
        "game_label": game.fixture.label,
        "label": entry.label,
        "probability": entry.probability,
        "odd": entry.odd,
        "value_ratio": entry.value_ratio,
        "calibrated_probability": entry.calibrated_probability,
        "calibration_sample_size": entry.calibration_sample_size,
    }


def build_context(
    day: date,
    games: list[MatchedGame],
    demo: bool = False,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.80,
    high_odd_min: float = 1.20,
    high_odd_max: float = 1.49,
    mid_probability_min: float = 0.70,
    mid_probability_max: float | None = None,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    min_value_ratio: float = 1.0,
    multiple_stake: float = 0.50,
    mid_single_stake: float = 1.00,
    has_calibration: bool = False,
    has_real_report: bool = False,
) -> dict:
    game_ctx = []
    for g in games:
        # CHANGED (2026-09-14, explicitly requested a third time): earlier
        # iterations showed every event clearing min_probability regardless
        # of whether Betclic had a matching odd (odd/valor rendered as
        # "—") -- now reversed back to odds-required, since a "— " row
        # (e.g. a "Menos de 5.5" line Betclic simply doesn't offer) isn't
        # worth showing at all. Unlike the earlier behavior, this is now
        # the same odds-required filter top_value_bets_today already
        # applies, just without its value_ratio>threshold requirement --
        # every event with a real Betclic odd shows, not only the ones
        # that clear the value-bet bar.
        events = [
            e for e in g.events_by_probability if e.probability > min_probability and e.odd is not None
        ]
        # Distinct from "events is empty" below: this says whether
        # scraping actually got *any* xGScore probabilities for this game
        # at all, regardless of the min_probability filter above -- an
        # empty `events` table has two very different causes ("nothing
        # was scraped, go check CALIBRATION.md" vs. "plenty was scraped,
        # it's just filtered out because nothing cleared the probability
        # threshold") and the template needs to tell them apart.
        has_predictions = bool(g.prediction and g.prediction.markets)
        game_ctx.append(
            {
                "slug": g.fixture.slug,
                "league": g.fixture.league,
                "home_team": g.fixture.home_team,
                "away_team": g.fixture.away_team,
                "kickoff": _fmt_kickoff(g.fixture.kickoff),
                "preview_url": g.fixture.preview_url,
                "has_predictions": has_predictions,
                "match_confidence": g.match_confidence,
                "events": events,
                "value_bets": g.value_bets_ranked,
                "combo_entries": compute_combo_entries(g),
            }
        )

    # Daily bet plan -- three sections, each a complete, independent list
    # of every candidate within its own already-configured
    # probability/odd band, sorted by probability descending. Explicitly
    # requested (2026-09-29): previously each section narrowed itself
    # down to one single "best" pick -- that narrowing was removed, not
    # the bands/parameters themselves.
    multiple_legs = pick_multiple_legs(
        games,
        min_probability=high_probability_min,
        min_odd=high_odd_min,
        max_odd=high_odd_max,
        min_value_ratio=min_value_ratio,
        coverable_markets=betclic_markets,
    )
    mid_bets = pick_band_bets(
        games,
        min_probability=mid_probability_min,
        max_probability=mid_probability_max,
        min_odd=mid_odd_min,
        max_odd=mid_odd_max,
        odd_bounds_inclusive=True,
        min_value_ratio=min_value_ratio,
        coverable_markets=betclic_markets,
    )

    return {
        "date_str": day.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "games": game_ctx,
        "demo": demo,
        "min_probability": min_probability,
        "multiple_legs": [_pick_ctx(leg) for leg in multiple_legs],
        "multiple_combined_odd": multiple_combined_odd(multiple_legs),
        "multiple_combined_probability": multiple_combined_probability(multiple_legs),
        "multiple_stake": multiple_stake,
        "high_probability_min": high_probability_min,
        "high_odd_min": high_odd_min,
        "high_odd_max": high_odd_max,
        "min_value_ratio": min_value_ratio,
        "mid_bets": [_pick_ctx(m) for m in mid_bets],
        "mid_single_stake": mid_single_stake,
        "mid_probability_min": mid_probability_min,
        "mid_probability_max": mid_probability_max,
        "mid_odd_min": mid_odd_min,
        "mid_odd_max": mid_odd_max,
        "has_calibration": has_calibration,
        "has_real_report": has_real_report,
    }


def render_dashboard(
    day: date,
    games: list[MatchedGame],
    reports_dir: Path,
    value_bet_threshold: float = 1.0,
    demo: bool = False,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.80,
    high_odd_min: float = 1.20,
    high_odd_max: float = 1.49,
    mid_probability_min: float = 0.70,
    mid_probability_max: float | None = None,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    min_value_ratio: float = 1.0,
    multiple_stake: float = 0.50,
    mid_single_stake: float = 1.00,
    has_real_report: bool = False,
) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(
        **build_context(
            day,
            games,
            demo=demo,
            min_probability=min_probability,
            betclic_markets=betclic_markets,
            high_probability_min=high_probability_min,
            high_odd_min=high_odd_min,
            high_odd_max=high_odd_max,
            mid_probability_min=mid_probability_min,
            mid_probability_max=mid_probability_max,
            mid_odd_min=mid_odd_min,
            mid_odd_max=mid_odd_max,
            min_value_ratio=min_value_ratio,
            multiple_stake=multiple_stake,
            mid_single_stake=mid_single_stake,
            has_calibration=(reports_dir / "calibration.html").exists(),
            has_real_report=has_real_report,
        )
    )

    day_dir = reports_dir / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def render_index(reports_dir: Path) -> Path:
    """Write a small landing page at ``reports_dir/index.html`` linking to
    every day that has a rendered dashboard, newest first.

    Used so a GitHub Pages deploy of ``reports_dir`` has a sensible root
    page instead of a 404.
    """
    # p.parent.name, NOT p.name -- p is the matched *file*
    # (".../<day>/index.html"), so p.name is always the literal string
    # "index.html" for every match; p.parent.name is the day directory
    # ("2026-09-26") we actually want. Real bug (2026-09-26): every entry
    # in `days` came out as "index.html", so the redirect below pointed
    # at the relative path "index.html/" -- a directory that doesn't
    # exist on GitHub Pages -- 404ing the site's own root page.
    days = sorted(
        (p.parent.name for p in reports_dir.glob("*/index.html")),
        reverse=True,
    )
    items = "\n".join(f'<li><a href="{d}/">{d}</a></li>' for d in days) or "<li>Ainda sem dados.</li>"
    redirect = f'<meta http-equiv="refresh" content="0; url={days[0]}/" />' if days else ""
    calibration_link = (
        '<p><a href="calibration.html">📈 Calibração do modelo</a></p>'
        if (reports_dir / "calibration.html").exists()
        else ""
    )
    html = f"""<!doctype html>
<html lang="pt-PT"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tips xGScore + Betclic</title>
{redirect}
<style>
  body{{background:#f7f7f8;color:#1b1c1f;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;max-width:480px;margin:60px auto;padding:0 16px;}}
  @media (prefers-color-scheme: dark){{body{{background:#15161a;color:#eef0f3;}}}}
  a{{color:#2f6fed;}}
  ul{{padding-left:1.2em;}}
</style></head>
<body>
  <h1>⚽ Tips xGScore + Betclic</h1>
  <p>{"A redirecionar para o dia mais recente..." if days else ""}</p>
  <ul>{items}</ul>
  {calibration_link}
</body></html>"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def _real_pick_ctx(pick: BetPick | None) -> dict | None:
    if pick is None:
        return None
    game, entry = pick
    return {
        "game_slug": game.fixture.slug,
        "game_label": game.fixture.label,
        "label": entry.label,
        "real_probability": entry.calibrated_probability,
        "model_probability": entry.probability,
        "sample_size": entry.calibration_sample_size,
        "is_confirmed": (entry.calibration_sample_size or 0) >= DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE,
        "odd": entry.odd,
        "value_ratio": entry.value_ratio,
    }


def build_real_context(
    day: date,
    games: list[MatchedGame],
    calibration_buckets: list,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.80,
    high_odd_min: float = 1.20,
    high_odd_max: float = 1.49,
    mid_probability_min: float = 0.70,
    mid_probability_max: float | None = None,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    min_value_ratio: float = 1.0,
    multiple_stake: float = 0.50,
    mid_single_stake: float = 1.00,
    has_calibration: bool = False,
    multiple_leg_cap: int | None = None,
) -> dict:
    """Same two daily-bet-plan sections as ``build_context`` (same
    configured probability/odd bands, so the two pages are an apples-to-
    apples comparison), but every selection/ranking criterion is the
    REAL observed hit rate (``ValueBetEntry.calibrated_probability``,
    computed here with NO minimum sample size -- see
    ``compute_real_rate_value_bets``) instead of the model's own
    probability. Explicitly requested (2026-11-17): an entry with no
    historical sample at all for its exact market+outcome+band is
    skipped outright (there's no real rate to rank it by yet), while one
    with *any* sample is kept and flagged ``is_confirmed`` once it's
    reached ``DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE`` -- so this page
    naturally grows in coverage over time as more bands accumulate
    history, rather than waiting for everything to clear 30 games at
    once.

    ``multiple_leg_cap`` (explicitly requested 2026-11-18, after
    backtesting 5 days of accumulated history -- see
    ``config.AppConfig.report_real_multiple_leg_cap``): keeps only the
    best ``multiple_leg_cap`` legs (by real rate, already-applied
    tiebreak included) of the otherwise-qualifying multiple, instead of
    every leg that clears the band. A multiple needs ALL its legs to
    hit, so each extra leg multiplies the chance of losing -- capping it
    was, by a wide margin, the single biggest lever found for the real-
    rate multiple's own backtested consistency. ``None`` (the default)
    keeps every qualifying leg, unchanged from before this was added.

    Also builds ``game_breakdown`` (explicitly requested, 2026-11-17,
    "tal como no outro" -- mirroring the dashboard's own per-game
    "Acontecimentos por probabilidade" table): one entry per game that
    has at least one outcome whose REAL rate clears ``min_probability``
    AND has a matched Betclic odd (same odds-required rule
    ``build_context`` already applies there), sorted by real rate
    descending within each game -- not just the two already-configured
    bet-plan bands above, every qualifying outcome of every game.
    """
    real_entries_by_fixture = {
        g.fixture.id: compute_real_rate_value_bets(g, calibration_buckets) for g in games
    }

    def entries_of(g: MatchedGame) -> list:
        return real_entries_by_fixture[g.fixture.id]

    def probability_of(e) -> float | None:
        return e.calibrated_probability

    # Explicitly requested (2026-11-18): a real case where three entries
    # tied at exactly the same real rate, and the one that won a
    # capped/shared slot did so purely by accident of fixture order.
    # While a band hasn't reached the 30-game production threshold, more
    # accumulated sample is the more trustworthy tie-break; only once
    # sample size *also* ties (as it commonly will between same-day bets
    # sharing one band) does the model's own probability decide.
    def tiebreak_of(e) -> tuple:
        return (e.calibration_sample_size or 0, e.probability)

    multiple_legs = pick_multiple_legs(
        games,
        min_probability=high_probability_min,
        min_odd=high_odd_min,
        max_odd=high_odd_max,
        min_value_ratio=min_value_ratio,
        coverable_markets=betclic_markets,
        probability_of=probability_of,
        entries_of=entries_of,
        tiebreak_of=tiebreak_of,
    )
    if multiple_leg_cap is not None:
        multiple_legs = multiple_legs[:multiple_leg_cap]
    mid_bets = pick_band_bets(
        games,
        min_probability=mid_probability_min,
        max_probability=mid_probability_max,
        min_odd=mid_odd_min,
        max_odd=mid_odd_max,
        odd_bounds_inclusive=True,
        min_value_ratio=min_value_ratio,
        coverable_markets=betclic_markets,
        probability_of=probability_of,
        entries_of=entries_of,
        tiebreak_of=tiebreak_of,
    )

    game_breakdown = []
    for g in games:
        qualifying = [
            e
            for e in real_entries_by_fixture[g.fixture.id]
            if e.calibrated_probability is not None and e.calibrated_probability > min_probability and e.odd is not None
        ]
        if not qualifying:
            continue
        qualifying.sort(key=lambda e: (e.calibrated_probability, e.calibration_sample_size or 0, e.probability), reverse=True)
        game_breakdown.append(
            {
                "slug": g.fixture.slug,
                "label": g.fixture.label,
                "events": [_real_pick_ctx((g, e)) for e in qualifying],
            }
        )

    return {
        "date_str": day.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "min_sample_size": DEFAULT_MIN_CALIBRATION_SAMPLE_SIZE,
        "min_probability": min_probability,
        "game_breakdown": game_breakdown,
        "multiple_leg_cap": multiple_leg_cap,
        "multiple_legs": [_real_pick_ctx(leg) for leg in multiple_legs],
        "multiple_combined_odd": multiple_combined_odd(multiple_legs),
        "multiple_combined_probability": multiple_combined_probability(multiple_legs, probability_of=probability_of),
        "multiple_stake": multiple_stake,
        "high_probability_min": high_probability_min,
        "high_odd_min": high_odd_min,
        "high_odd_max": high_odd_max,
        "min_value_ratio": min_value_ratio,
        "mid_bets": [_real_pick_ctx(m) for m in mid_bets],
        "mid_single_stake": mid_single_stake,
        "mid_probability_min": mid_probability_min,
        "mid_probability_max": mid_probability_max,
        "mid_odd_min": mid_odd_min,
        "mid_odd_max": mid_odd_max,
        "has_calibration": has_calibration,
    }


def render_real_report(
    day: date,
    games: list[MatchedGame],
    calibration_buckets: list,
    reports_dir: Path,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.80,
    high_odd_min: float = 1.20,
    high_odd_max: float = 1.49,
    mid_probability_min: float = 0.70,
    mid_probability_max: float | None = None,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    min_value_ratio: float = 1.0,
    multiple_stake: float = 0.50,
    mid_single_stake: float = 1.00,
    multiple_leg_cap: int | None = None,
) -> Path:
    """Render ``reports_dir/<day>/real.html`` -- the "apostas por taxa
    real" counterpart of that day's dashboard (see ``build_real_context``
    for what's different)."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("real.html.j2")
    html = template.render(
        **build_real_context(
            day,
            games,
            calibration_buckets,
            min_probability=min_probability,
            betclic_markets=betclic_markets,
            high_probability_min=high_probability_min,
            high_odd_min=high_odd_min,
            high_odd_max=high_odd_max,
            mid_probability_min=mid_probability_min,
            mid_probability_max=mid_probability_max,
            mid_odd_min=mid_odd_min,
            mid_odd_max=mid_odd_max,
            min_value_ratio=min_value_ratio,
            multiple_stake=multiple_stake,
            mid_single_stake=mid_single_stake,
            has_calibration=(reports_dir / "calibration.html").exists(),
            multiple_leg_cap=multiple_leg_cap,
        )
    )

    day_dir = reports_dir / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "real.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


# "Well calibrated" means the actual hit rate lands close to the
# probability the model itself predicted -- within this many percentage
# points either way. Outside it, the bucket is flagged as the model
# being over- or under-confident for that market/band.
_CALIBRATION_GOOD_TOLERANCE = 0.07


def _calibration_bucket_ctx(bucket: CalibrationBucket) -> dict:
    gap = bucket.actual_hit_rate - bucket.avg_predicted_probability
    if abs(gap) <= _CALIBRATION_GOOD_TOLERANCE:
        verdict = "good"
    elif gap < 0:
        verdict = "over"  # model predicted higher than what actually happened
    else:
        verdict = "under"  # model predicted lower than what actually happened
    return {
        "probability_bucket": bucket.probability_bucket,
        "count": bucket.count,
        "hits": bucket.hits,
        "actual_hit_rate": bucket.actual_hit_rate,
        "avg_predicted_probability": bucket.avg_predicted_probability,
        "verdict": verdict,
    }


def build_calibration_context(buckets: list[CalibrationBucket], total_games: int) -> dict:
    # Grouped by (exact market, outcome) -- explicitly requested
    # (2026-11-14, then taken further): kept fully separate, e.g. home
    # wins never pooled with away wins, over never pooled with under,
    # home_total's own over/under never pooled with away_total's,
    # double_chance's "1x" never pooled with "x2" (its "12" is excluded
    # entirely upstream, in calibration.py) -- AND, on top of that,
    # over_under_1.5 never pooled with over_under_2.5/3.5/4.5/5.5 (nor
    # home_total_<line>/away_total_<line> with their own other lines):
    # see calibration.py's module docstring for why pooling different
    # lines together would hide real per-line differences. Preserves
    # compute_calibration's own order (per group, highest-confidence
    # band first) -- deliberately NOT also reporting one hit-rate
    # pooled across every band: see calibration.py's module docstring
    # for why that would be a mathematical constant carrying no real
    # signal for most markets here, rather than a measure of skill.
    groups: dict[tuple[str, str], list[dict]] = {}
    for b in buckets:
        groups.setdefault((b.market, b.outcome), []).append(_calibration_bucket_ctx(b))

    markets = [
        {
            "market": market,
            "outcome": outcome,
            "family": market_family(market),
            "label": full_label(market, outcome),
            "sample_size": sum(b["count"] for b in group_buckets),
            "buckets": group_buckets,
        }
        for (market, outcome), group_buckets in groups.items()
    ]

    # Explicitly requested (2026-11-17): the page was "muito desorganizada"
    # with dozens of always-open per-(market,outcome) tables and no way to
    # see the big picture. Regrouped here into a two-level structure --
    # one entry per market *family* (over_under, handicap_home, 1x2, ...),
    # each holding its own member markets/outcomes plus a verdict tally
    # across every one of its bands -- so the template can show a compact
    # summary table first and push the full detail into closed-by-default
    # sections instead of a wall of open tables.
    families: dict[str, list[dict]] = {}
    for m in markets:
        families.setdefault(m["family"], []).append(m)

    family_list = []
    for family, members in families.items():
        verdict_counts = {"good": 0, "over": 0, "under": 0}
        for m in members:
            for b in m["buckets"]:
                verdict_counts[b["verdict"]] += 1
        family_list.append(
            {
                "name": family,
                "sample_size": sum(m["sample_size"] for m in members),
                "band_count": sum(len(m["buckets"]) for m in members),
                "verdict_counts": verdict_counts,
                "markets": members,
            }
        )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_games": total_games,
        "families": family_list,
    }


def render_calibration_report(buckets: list[CalibrationBucket], total_games: int, reports_dir: Path) -> Path:
    """Render ``reports_dir/calibration.html`` -- the browser-viewable
    counterpart of ``python -m tipsxgs calibrate``'s text output (see
    ``cli.calibrate``), so the same per-market, per-probability-band
    hit-rate breakdown is reachable from the dashboard, not just the
    terminal."""
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("calibration.html.j2")
    html = template.render(**build_calibration_context(buckets, total_games))

    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "calibration.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
