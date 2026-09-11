"""Render the daily HTML dashboard from a list of :class:`MatchedGame`."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import MatchedGame
from .valuebets import top_value_bets_today

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _fmt_kickoff(dt: datetime | None) -> str | None:
    return dt.strftime("%H:%M") if dt else None


def build_context(day: date, games: list[MatchedGame], demo: bool = False) -> dict:
    game_ctx = []
    for g in games:
        game_ctx.append(
            {
                "slug": g.fixture.slug,
                "league": g.fixture.league,
                "home_team": g.fixture.home_team,
                "away_team": g.fixture.away_team,
                "kickoff": _fmt_kickoff(g.fixture.kickoff),
                "preview_url": g.fixture.preview_url,
                "match_confidence": g.match_confidence,
                "events": g.events_by_probability,
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

    return {
        "date_str": day.isoformat(),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "games": game_ctx,
        "top_value_bets": top_ctx,
        "demo": demo,
    }


def render_dashboard(day: date, games: list[MatchedGame], reports_dir: Path, value_bet_threshold: float = 1.0, demo: bool = False) -> Path:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html.j2")
    html = template.render(**build_context(day, games, demo=demo))

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
