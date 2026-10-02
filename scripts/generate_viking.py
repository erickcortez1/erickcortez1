#!/usr/bin/env python3
"""Generate an animated SVG over a real GitHub contribution calendar.

The offline --demo mode is for local preview and tests only. It is never used by CI.
Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from html import escape
import json
import math
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

USERNAME = "erickcortez1"
CELL = 10
STEP = 13
LEFT = 43
TOP = 46
DARK = "#0d1117"
EMPTY = "#161b22"
LEVELS = {
    "NONE": EMPTY,
    "FIRST_QUARTILE": "#0e4429",
    "SECOND_QUARTILE": "#006d32",
    "THIRD_QUARTILE": "#26a641",
    "FOURTH_QUARTILE": "#39d353",
}
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
QUERY = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks {
          contributionDays { date contributionCount contributionLevel }
        }
      }
    }
  }
}
"""


def align_weeks(weeks: list[list[dict]]) -> list[list[dict]]:
    """GraphQL omits off-range days in partial weeks; keep Sunday-first rows."""
    aligned = []
    for week in weeks:
        if not week:
            continue
        first = date.fromisoformat(week[0]["date"])
        sunday = first - timedelta(days=(first.weekday() + 1) % 7)
        by_date = {day["date"]: day for day in week}
        aligned.append([
            by_date.get((sunday + timedelta(days=r)).isoformat(), {
                "date": (sunday + timedelta(days=r)).isoformat(),
                "contributionCount": 0,
                "contributionLevel": "NONE",
            })
            for r in range(7)
        ])
    return aligned


def fetch_weeks(username: str, token: str) -> list[list[dict]]:
    if not token:
        raise ValueError("GITHUB_TOKEN ausente. Use --demo somente para a visualização local.")
    payload = json.dumps({"query": QUERY, "variables": {"login": username}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "viking-contribution-graph",
            "Accept": "application/vnd.github+json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.load(response)
    except (urllib.error.URLError, ValueError) as err:
        raise RuntimeError(f"Falha ao consultar o GitHub GraphQL: {err}") from err
    if result.get("errors"):
        details = "; ".join(item.get("message", "erro desconhecido") for item in result["errors"])
        raise RuntimeError(f"GitHub GraphQL rejeitou a consulta: {details}")
    try:
        weeks = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        if not weeks:
            raise ValueError("calendário vazio")
        return align_weeks([w["contributionDays"] for w in weeks])
    except (KeyError, TypeError, ValueError) as err:
        raise RuntimeError(f"Formato inesperado do calendário do GitHub: {err}") from err


def demo_weeks() -> list[list[dict]]:
    """Deterministic sample shaped like a contribution calendar (not real data)."""
    today = date.today()
    sunday = today - timedelta(days=(today.weekday() + 1) % 7 + 52 * 7)
    result = []
    for w in range(53):
        week = []
        for r in range(7):
            d = sunday + timedelta(days=7 * w + r)
            value = 0 if (w * 7 + r * 11) % 9 > 1 else (w + r) % 4 + 1
            level = ("NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE")[value]
            week.append({"date": d.isoformat(), "contributionCount": value, "contributionLevel": level})
        result.append(week)
    return result


def normalized(val: float, total: float) -> str:
    return f"{max(0, min(1, val / total)):.6f}"


def time_anim(attr: str, states: list[tuple[float, str]], total: float, *, transform: bool = False, **attrs) -> str:
    """Create one loop-wide SMIL animation. KeyTimes must be strictly ordered."""
    valid = []
    last = -1.0
    for t, v in sorted(states):
        t = max(0.0, min(total, t))
        if t <= last:
            t = min(total, last + 0.0001)
        valid.append((t, v))
        last = t
    if valid[0][0] != 0:
        valid.insert(0, (0.0, valid[0][1]))
    if valid[-1][0] != total:
        valid.append((total, valid[-1][1]))
    tag = "animateTransform" if transform else "animate"
    extra = " ".join(f'{key}="{escape(str(value))}"' for key, value in attrs.items())
    return (
        f'<{tag} attributeName="{escape(attr)}" {extra} '
        f'values="{escape(";".join(v for _, v in valid))}" '
        f'keyTimes="{";".join(normalized(t, total) for t, _ in valid)}" '
        f'dur="{total:.2f}s" repeatCount="indefinite"/>'
    )


def choose_targets(weeks: list[list[dict]], limit: int = 16) -> list[tuple[int, int]]:
    """Select non-empty contributions, spaced through a serpentine row traversal."""
    filled = []
    for r in range(7):
        col_range = range(len(weeks)) if r % 2 == 0 else range(len(weeks) - 1, -1, -1)
        for col in col_range:
            if r < len(weeks[col]) and weeks[col][r].get("contributionCount", 0) > 0:
                filled.append((col, r))
    if len(filled) <= limit:
        return filled
    indexes = sorted({round(i * (len(filled) - 1) / (limit - 1)) for i in range(limit)})
    return [filled[i] for i in indexes]


def geometry(weeks: list[list[dict]], targets: list[tuple[int, int]]):
    """Waypoints keep the warrior near the contribution cell he's attacking."""
    if not targets:
        return [], 8.0, [], []
    points = []
    attacks = []
    facing = []
    t = 0.0
    start_col, start_r = targets[0]
    initial_x = max(LEFT - 22, LEFT + STEP * start_col - 48)
    initial_y = TOP + STEP * start_r - 7
    points.append((0.0, initial_x, initial_y))
    last_x, last_y = initial_x, initial_y
    last_face = 1
    facing.append((0.0, "1 1"))
    for col, r in targets:
        cx = LEFT + STEP * col
        cy = TOP + STEP * r
        direction = 1 if cx >= (last_x + 22 if last_face == 1 else last_x - 22) else -1
        x = cx - 22 if direction == 1 else cx + 22
        y = cy - 7
        if last_face != direction:
            # Face changes are discrete; the character's next movement remains continuous.
            facing.append((max(0.0, t + 0.001), f"{direction} 1"))
        travel = max(0.65, min(2.25, math.hypot(x - last_x, y - last_y) / 150))
        t += travel
        points.append((t, x, y))
        # Short pause, axe swing, particles, then return to walking.
        attacks.append((t + 0.28, col, r))
        t += 0.93
        points.append((t, x, y))
        last_x, last_y, last_face = x, y, direction
    t += 0.6
    points.append((t, last_x + 27 * last_face, last_y))
    total = t + 0.8
    points.append((total, initial_x, initial_y))
    return points, total, attacks, facing


def sprite() -> str:
    """Temporary 24x26 pixel-art silhouette. Replace only this function for final art."""
    return '''<g id="viking-sprite" shape-rendering="crispEdges">
      <!-- blue cloak, boots, leather armor, horned helmet, beard, shield -->
      <g id="cloak">
        <rect x="3" y="8" width="6" height="15" fill="#164d82"/>
        <rect x="1" y="14" width="5" height="8" fill="#256fa8"/>
        <animateTransform attributeName="transform" type="translate" values="0 0;1 0;0 0" dur="0.65s" repeatCount="indefinite"/>
      </g>
      <g id="boots">
        <rect x="8" y="20" width="5" height="5" fill="#603e2a"/>
        <rect x="15" y="20" width="5" height="5" fill="#603e2a"/>
        <rect x="7" y="24" width="7" height="3" fill="#879db1"/>
        <rect x="15" y="24" width="7" height="3" fill="#879db1"/>
        <animateTransform attributeName="transform" type="translate" values="0 0;0 1;0 0" dur="0.52s" repeatCount="indefinite"/>
      </g>
      <rect x="7" y="10" width="13" height="12" fill="#52687e"/>
      <rect x="8" y="17" width="12" height="4" fill="#805339"/>
      <rect x="7" y="10" width="14" height="3" fill="#c7dce7"/>
      <rect x="11" y="3" width="9" height="9" fill="#d3a477"/>
      <rect x="12" y="9" width="8" height="8" fill="#89502d"/>
      <rect x="16" y="7" width="2" height="2" fill="#172231"/>
      <rect x="10" y="3" width="12" height="4" fill="#4786b5"/>
      <rect x="9" y="0" width="3" height="5" fill="#e6d8b7"/>
      <rect x="20" y="0" width="3" height="5" fill="#e6d8b7"/>
      <rect x="15" y="2" width="3" height="5" fill="#84c6e5"/>
      <rect x="6" y="12" width="6" height="9" rx="1" fill="#9ab8c9"/>
      <rect x="7" y="14" width="4" height="5" fill="#34618b"/>
      <rect x="8" y="15" width="2" height="3" fill="#65b7e6"/>
      <g id="axe" transform="rotate(0 20 12)">
        <rect x="20" y="5" width="2" height="13" fill="#95623e"/>
        <rect x="18" y="2" width="9" height="7" fill="#a9d6e6"/>
        <rect x="24" y="1" width="6" height="9" fill="#4c9dc8"/>
        <rect x="27" y="3" width="3" height="5" fill="#a7e6ef"/>
        <!-- AXE_ANIMATION -->
      </g>
    </g>'''


def make_svg(weeks: list[list[dict]], username: str = USERNAME) -> str:
    if not weeks or not all(isinstance(w, list) for w in weeks):
        raise ValueError("Calendário de contribuições inválido.")
    width = LEFT + STEP * len(weeks) + 18
    height = TOP + STEP * 7 + 19
    targets = choose_targets(weeks)
    points, total, attacks, facing = geometry(weeks, targets)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="Viking pixel art percorrendo o gráfico de contribuições de {escape(username)}">',
        f'<rect width="100%" height="100%" rx="10" fill="{DARK}"/>',
        f'<text x="{LEFT}" y="16" font-size="10" font-family="Arial, sans-serif" fill="#8b949e">Contribuições de {escape(username)}</text>',
    ]
    for r, label in ((1, "seg"), (3, "qua"), (5, "sex")):
        lines.append(f'<text x="6" y="{TOP + STEP*r + 9}" font-size="9" fill="#8b949e" font-family="Arial, sans-serif">{label}</text>')
    last_month = None
    for col, days in enumerate(weeks):
        if not days:
            continue
        first_date = date.fromisoformat(days[-1]["date"])
        if col == 0 or first_date.month != last_month:
            lines.append(f'<text x="{LEFT+STEP*col}" y="{TOP-9}" font-size="9" fill="#8b949e" font-family="Arial, sans-serif">{MONTHS[first_date.month-1]}</text>')
        last_month = first_date.month
        for row, day in enumerate(days):
            color = LEVELS.get(day.get("contributionLevel"), EMPTY)
            x, y = LEFT+STEP*col, TOP+STEP*row
            lines.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="1.8" fill="{EMPTY}"/>')
            if day.get("contributionCount", 0):
                lines.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="1.8" fill="{color}">')
                hit = next((tm for tm, c, r in attacks if c == col and r == row), None)
                if hit is not None:
                    lines.append(time_anim("opacity", [(0,"1"), (hit,"1"), (hit+0.16,"0"), (total-0.15,"0"), (total,"1")],total))
                lines.append('</rect>')
    # Display attack particles at the selected target cells.
    for hit, col, row in attacks:
        cx = LEFT+STEP*col + 5
        cy = TOP+STEP*row + 5
        lines.append(f'<g transform="translate({cx} {cy})">')
        for dx, dy, color in ((-8,-5,"#82cfff"),(7,-6,"#f4d56d"),(-5,7,"#65b7e6"),(8,6,"#d9f1ff")):
            lines.append(f'<rect x="-1" y="-1" width="3" height="3" fill="{color}">')
            lines.append(time_anim("opacity", [(0,"0"),(hit,"0"),(hit+0.08,"1"),(hit+0.37,"0"),(total,"0")],total))
            lines.append(time_anim("transform", [(0,"0 0"),(hit,"0 0"),(hit+0.35,f"{dx} {dy}"),(total,"0 0")],total,transform=True,type="translate"))
            lines.append('</rect>')
        lines.append('</g>')
    if targets:
        coord_states = [(tm, f"{x:.2f} {y:.2f}") for tm,x,y in points]
        lines.append(f'<g id="viking-motion" transform="translate({points[0][1]:.2f} {points[0][2]:.2f})">')
        lines.append(time_anim("transform", coord_states,total,transform=True,type="translate"))
        lines.append('<g id="viking-facing">')
        lines.append(time_anim("transform", facing+[(total,facing[0][1])],total,transform=True,type="scale",calcMode="discrete"))
        axe_states = [(0.0,"0 20 12")]
        for hit,_,_ in attacks:
            axe_states.extend(((hit-0.28,"0 20 12"),(hit-0.06,"-45 20 12"),(hit+0.08,"36 20 12"),(hit+0.33,"0 20 12")))
        axe_states.append((total,"0 20 12"))
        rendered = sprite().replace("<!-- AXE_ANIMATION -->",time_anim("transform",axe_states,total,transform=True,type="rotate"))
        lines.append(rendered)
        lines.extend(['</g>', '</g>'])
    else:
        lines.append('<text x="43" y="146" fill="#8b949e" font-size="10">Sem contribuições públicas no período.</text>')
    lines.append('</svg>')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Viking Contribution Graph as an animated SVG.")
    parser.add_argument("--username", default=USERNAME)
    parser.add_argument("--output", default="assets/viking-contributions.svg")
    parser.add_argument("--demo", action="store_true", help="Local test data. NEVER use for publication.")
    args = parser.parse_args()
    try:
        weeks = demo_weeks() if args.demo else fetch_weeks(args.username, os.getenv("GITHUB_TOKEN", ""))
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(make_svg(weeks, args.username), encoding="utf-8")
        print(f"SVG gerado: {output} | {len(weeks)} semanas | modo: {'DEMO' if args.demo else 'REAL'}")
    except (RuntimeError, ValueError, OSError) as err:
        print(f"ERRO: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
