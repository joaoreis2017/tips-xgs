"""Render the daily HTML dashboard from a list of :class:`MatchedGame`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import MatchedGame
from .valuebets import (
    BetPick,
    multiple_combined_odd,
    multiple_combined_probability,
    pick_best_band_single,
    pick_best_single_bet,
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
    }


def build_context(
    day: date,
    games: list[MatchedGame],
    demo: bool = False,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.70,
    high_odd_min: float = 1.25,
    high_odd_max: float = 1.45,
    mid_probability_min: float = 0.60,
    mid_probability_max: float = 0.69,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    multiple_max_legs: int = 4,
    value_single_min_probability: float = 0.45,
    value_single_min_value_ratio: float = 1.10,
    multiple_stake: float = 0.50,
    value_single_stake: float = 0.50,
    mid_single_stake: float = 1.00,
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
            }
        )

    # Deterministic daily bet plan -- explicitly requested: no candidate
    # lists left for the user to choose from, the model picks exactly
    # what to bet for each of the day's three stakes. Fixtures already
    # used earlier in the plan are excluded from later picks (multiple
    # legs first, then the value single, then the mid single) so the
    # three stakes spread risk across different matches rather than the
    # plan doubling up on the same outcome.
    multiple_legs = pick_multiple_legs(
        games,
        min_probability=high_probability_min,
        min_odd=high_odd_min,
        max_odd=high_odd_max,
        max_legs=multiple_max_legs,
        coverable_markets=betclic_markets,
    )
    used_fixture_ids = {g.fixture.id for g, _ in multiple_legs}

    value_single = pick_best_single_bet(
        games,
        min_probability=value_single_min_probability,
        min_value_ratio=value_single_min_value_ratio,
        exclude_fixture_ids=used_fixture_ids,
    )
    if value_single is not None:
        used_fixture_ids = used_fixture_ids | {value_single[0].fixture.id}

    mid_single = pick_best_band_single(
        games,
        min_probability=mid_probability_min,
        max_probability=mid_probability_max,
        min_odd=mid_odd_min,
        max_odd=mid_odd_max,
        odd_bounds_inclusive=True,
        coverable_markets=betclic_markets,
        exclude_fixture_ids=used_fixture_ids,
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
        "multiple_max_legs": multiple_max_legs,
        "multiple_stake": multiple_stake,
        "high_probability_min": high_probability_min,
        "high_odd_min": high_odd_min,
        "high_odd_max": high_odd_max,
        "value_single": _pick_ctx(value_single),
        "value_single_stake": value_single_stake,
        "value_single_min_probability": value_single_min_probability,
        "value_single_min_value_ratio": value_single_min_value_ratio,
        "mid_single": _pick_ctx(mid_single),
        "mid_single_stake": mid_single_stake,
        "mid_probability_min": mid_probability_min,
        "mid_probability_max": mid_probability_max,
        "mid_odd_min": mid_odd_min,
        "mid_odd_max": mid_odd_max,
    }


def render_dashboard(
    day: date,
    games: list[MatchedGame],
    reports_dir: Path,
    value_bet_threshold: float = 1.0,
    demo: bool = False,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.70,
    high_odd_min: float = 1.25,
    high_odd_max: float = 1.45,
    mid_probability_min: float = 0.60,
    mid_probability_max: float = 0.69,
    mid_odd_min: float = 1.5,
    mid_odd_max: float = 2.2,
    multiple_max_legs: int = 4,
    value_single_min_probability: float = 0.45,
    value_single_min_value_ratio: float = 1.10,
    multiple_stake: float = 0.50,
    value_single_stake: float = 0.50,
    mid_single_stake: float = 1.00,
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
            multiple_max_legs=multiple_max_legs,
            value_single_min_probability=value_single_min_probability,
            value_single_min_value_ratio=value_single_min_value_ratio,
            multiple_stake=multiple_stake,
            value_single_stake=value_single_stake,
            mid_single_stake=mid_single_stake,
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
</body></html>"""
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / "index.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
