"""Render the daily HTML dashboard from a list of :class:`MatchedGame`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import MatchedGame
from .valuebets import top_probability_bets_today, top_value_bets_today

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _fmt_kickoff(dt: datetime | None) -> str | None:
    return dt.strftime("%H:%M") if dt else None


def build_context(
    day: date,
    games: list[MatchedGame],
    demo: bool = False,
    min_probability: float = 0.5,
    betclic_markets: set[str] | None = None,
    high_probability_min: float = 0.70,
    mid_probability_min: float = 0.60,
    mid_probability_max: float = 0.69,
    high_odd_min: float = 1.25,
    high_odd_max: float = 1.45,
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

    top = top_value_bets_today(games, limit=20)
    top_ctx = [
        {
            "game_slug": g.fixture.slug,
            "game_label": g.fixture.label,
            "label": entry.label,
            "probability": entry.probability,
            "odd": entry.odd,
            "value_ratio": entry.value_ratio,
        }
        for g, entry in top
    ]

    # Odds-optional counterparts to top_value_bets_today above: every
    # game xGScore has predictions for, not only the ones paired with a
    # Betclic offer -- odd/value_ratio just come back None for a game
    # with no matched odds, rendered as "—" in the template. No limit --
    # explicitly requested: every event across every game should show,
    # not a top-N slice that squeezes out most games once there are
    # dozens of them. `betclic_markets` (see pipeline.py) additionally
    # drops odd-less entries for markets Betclic has no extraction rule
    # for at all (handicap, per-team totals, ...) -- those can never get
    # a real odd, so left in they just flood this probability-sorted list
    # with permanently-unbettable, usually-trivial (near 100%) lines.
    #
    # Explicitly requested split (previously one combined list): a
    # high-confidence band (>= high_probability_min) and a separate
    # mid-confidence band (mid_probability_min..mid_probability_max),
    # each its own panel -- see valuebets.top_probability_bets_today's
    # docstring for the inclusive, displayed-whole-percent bucketing.
    def _band_ctx(
        min_probability: float,
        max_probability: float | None,
        min_odd: float | None = None,
        max_odd: float | None = None,
    ) -> list[dict]:
        pairs = top_probability_bets_today(
            games,
            min_probability=min_probability,
            max_probability=max_probability,
            min_odd=min_odd,
            max_odd=max_odd,
            limit=None,
            coverable_markets=betclic_markets,
        )
        return [
            {
                "game_slug": g.fixture.slug,
                "game_label": g.fixture.label,
                "label": entry.label,
                "probability": entry.probability,
                "odd": entry.odd,
                "value_ratio": entry.value_ratio,
            }
            for g, entry in pairs
        ]

    # High band ONLY, explicitly requested: also needs a matched odd
    # strictly between high_odd_min/high_odd_max -- the mid band has no
    # odd-range equivalent, it stays odds-optional.
    high_probability_bets = _band_ctx(high_probability_min, None, high_odd_min, high_odd_max)
    mid_probability_bets = _band_ctx(mid_probability_min, mid_probability_max)

    return {
        "date_str": day.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "games": game_ctx,
        "top_value_bets": top_ctx,
        "high_probability_bets": high_probability_bets,
        "mid_probability_bets": mid_probability_bets,
        "demo": demo,
        "min_probability": min_probability,
        "high_probability_min": high_probability_min,
        "mid_probability_min": mid_probability_min,
        "mid_probability_max": mid_probability_max,
        "high_odd_min": high_odd_min,
        "high_odd_max": high_odd_max,
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
    mid_probability_min: float = 0.60,
    mid_probability_max: float = 0.69,
    high_odd_min: float = 1.25,
    high_odd_max: float = 1.45,
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
            mid_probability_min=mid_probability_min,
            mid_probability_max=mid_probability_max,
            high_odd_min=high_odd_min,
            high_odd_max=high_odd_max,
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
    days = sorted(
        (p.name for p in reports_dir.glob("*/index.html")),
        reverse=True,
    )
    items = "\n".join(f'<li><a href="{d}/">{d}</a></li>' for d in days) or "<li>Ainda sem dados.</li>"
    html = f"""<!doctype html>
<html lang="pt-PT"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tips xGScore + Betclic</title>
<meta http-equiv="refresh" content="0; url={days[0]}/" />
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
