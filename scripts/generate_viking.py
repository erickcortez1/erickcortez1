#!/usr/bin/env python3
"""Generate an animated SVG over a real GitHub contribution calendar.

The offline --demo mode is for local preview and tests only. It is never used by CI.
Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import base64
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
TOP = 65
DARK = "#0d1117"
EMPTY = "#161b22"
LEVELS = {
    "NONE": EMPTY,
    "FIRST_QUARTILE": "#0e4429",
    "SECOND_QUARTILE": "#006d32",
    "THIRD_QUARTILE": "#26a641",
    "FOURTH_QUARTILE": "#39d353",
}
SPRITE_FILES = (
    "idle_1", "idle_2", "walk_1", "walk_2", "walk_3", "walk_4",
    "attack_1", "attack_2", "attack_3", "attack_4", "impact", "break",
)
SPRITES_DIR = Path(__file__).resolve().parents[1] / "assets" / "viking"
SPRITE_SCALE = 40 / 48  # 48 px lógicos renderizados em 40 px no SVG.
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


def choose_targets(weeks: list[list[dict]], limit: int = 10) -> list[tuple[int, int]]:
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
    """Percurso em zigue-zague com pivô no centro dos 40 px do personagem."""
    if not targets:
        return [], 8.0, [], []
    points = []
    attacks = []
    facing = []
    t = 0.0
    start_col, start_r = targets[0]
    first_x = LEFT + STEP * start_col
    initial_x = max(LEFT - 14, first_x - 54)
    initial_y = TOP + STEP * start_r - 29
    points.append((0.0, initial_x, initial_y))
    last_x, last_y = initial_x, initial_y
    last_face = 1
    facing.append((0.0, "1 1"))
    for col, r in targets:
        cx, cy = LEFT + STEP * col + CELL / 2, TOP + STEP * r + CELL / 2
        direction = 1 if cx >= last_x else -1
        # A lâmina chega ao centro da célula, e o corpo para ao lado do alvo.
        x = cx - direction * 18
        y = cy - 34
        if last_face != direction:
            facing.append((max(0.0, t + 0.001), f"{direction} 1"))
        travel = max(0.5, min(3.7, math.hypot(x-last_x, y-last_y) / 155))
        t += travel
        points.append((t, x, y))
        attacks.append((t + 0.30, col, r))
        t += 0.96
        points.append((t, x, y))
        last_x, last_y, last_face = x, y, direction
    t += 0.7
    points.append((t, last_x + 30 * last_face, last_y))
    total = t + 0.65
    points.append((total, initial_x, initial_y))
    return points, total, attacks, facing


def image_defs() -> list[str]:
    """Embute os PNGs no SVG: o README não depende de imagens externas."""
    lines = ["<defs>"]
    for name in SPRITE_FILES:
        sprite_path = SPRITES_DIR / (name + ".png")
        raw = sprite_path.read_bytes()
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError(f"Sprite PNG inválido: {sprite_path}")
        width = int.from_bytes(raw[16:20], "big")
        height = int.from_bytes(raw[20:24], "big")
        if (width, height) != (48, 48):
            raise ValueError(f"Dimensão do sprite inválida ({width}x{height}): {sprite_path}")
        data = base64.b64encode(raw).decode("ascii")
        lines.append(
            f'<image id="frame-{name}" x="0" y="0" width="48" height="48" '
            f'href="data:image/png;base64,{data}" style="image-rendering:pixelated"/>'
        )
    lines.append("</defs>")
    return lines


def build_frame_schedule(points: list[tuple[float, float, float]],
                         attacks: list[tuple[float, int, int]], total: float):
    """Timeline exclusiva: exatamente uma pose do viking visível por vez."""
    result = []

    def push(start: float, end: float, name: str):
        if end > start + 0.00001:
            result.append((start, end, name))

    def walk(start: float, end: float):
        tick = 0
        while start < end - 0.00001:
            nxt = min(end, start + 0.12)
            push(start, nxt, f"walk_{1+tick % 4}")
            tick += 1
            start = nxt

    previous = 0.0
    for idx, (hit, _, _) in enumerate(attacks):
        arrived = points[1 + 2*idx][0]
        resume = points[2 + 2*idx][0]
        walk(previous, arrived)
        push(arrived, hit - 0.23, "idle_1")
        push(hit - 0.23, hit - 0.14, "attack_1")
        push(hit - 0.14, hit - 0.045, "attack_2")
        push(hit - 0.045, hit + 0.09, "attack_3")
        push(hit + 0.09, hit + 0.24, "attack_4")
        push(hit + 0.24, resume, "idle_2")
        previous = resume
    walk(previous, points[-2][0])
    push(points[-2][0], total, "idle_1")
    if not result:
        push(0.0, total, "idle_1")
    return result


def frame_animations(schedule, total: float) -> list[str]:
    """Troca imagens com SMIL discreto: sem JS, sem flicker e sem sprites externos."""
    names = SPRITE_FILES[:10]
    states = {name: [(0.0, "1" if schedule[0][2] == name else "0")] for name in names}
    for (_, _, current), (start, _, nxt) in zip(schedule, schedule[1:]):
        if current != nxt:
            states[current].append((start, "0"))
            states[nxt].append((start, "1"))
    result = []
    for name in names:
        # Frame volta ao estado inicial na virada do loop.
        states[name].append((total, states[name][0][1]))
        result.append(f'<use href="#frame-{name}" opacity="{states[name][0][1]}">')
        result.append(time_anim("opacity", states[name], total, calcMode="discrete"))
        result.append('</use>')
    return result


def effect_animation(name: str, cx: float, cy: float,
                     begin: float, end: float, total: float, scale: float) -> list[str]:
    size = 48 * scale
    return [
        f'<g transform="translate({cx-size/2:.2f} {cy-size/2:.2f}) scale({scale:.4f})">',
        f'<use href="#frame-{name}" opacity="0">',
        time_anim("opacity", [(0,"0"),(begin,"1"),(end,"0"),(total,"0")],
                  total,calcMode="discrete"),
        '</use></g>',
    ]


def make_svg(weeks: list[list[dict]], username: str = USERNAME, *, demo: bool = False) -> str:
    if not weeks or not all(isinstance(w, list) for w in weeks):
        raise ValueError("Calendário de contribuições inválido.")
    width = LEFT + STEP * len(weeks) + 18
    height = TOP + STEP * 7 + 19
    targets = choose_targets(weeks)
    points, total, attacks, facing = geometry(weeks, targets)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="Viking pixel art percorrendo o gráfico de contribuições de {escape(username)}">',
    ]
    lines.extend(image_defs())
    lines.extend([
        f'<rect width="100%" height="100%" rx="10" fill="{DARK}"/>',
        f'<text x="{LEFT}" y="16" font-size="10" font-family="Arial, sans-serif" fill="#8b949e">Contribuições de {escape(username)}</text>',
    ])
    if demo:
        lines.append(f'<text x="{width-10}" y="16" font-size="9" text-anchor="end" font-family="Arial, sans-serif" fill="#e3bb65">PRÉVIA DEMONSTRATIVA</text>')
    for r, label in ((1, "seg"), (3, "qua"), (5, "sex")):
        lines.append(f'<text x="6" y="{TOP + STEP*r + 9}" font-size="9" fill="#8b949e" font-family="Arial, sans-serif">{label}</text>')
    last_month = None
    for col, days in enumerate(weeks):
        if not days:
            continue
        first_date = date.fromisoformat(days[-1]["date"])
        if col == 0 or first_date.month != last_month:
            lines.append(f'<text x="{LEFT+STEP*col}" y="{TOP-27}" font-size="9" fill="#8b949e" font-family="Arial, sans-serif">{MONTHS[first_date.month-1]}</text>')
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
    # Efeitos separados: faísca, pedaços do bloco e partículas pixeladas.
    for hit, col, row in attacks:
        cx = LEFT+STEP*col + CELL/2
        cy = TOP+STEP*row + CELL/2
        lines.extend(effect_animation("impact",cx,cy,hit-0.045,hit+0.12,total,0.60))
        lines.extend(effect_animation("break",cx,cy,hit+0.12,hit+0.38,total,0.52))
        lines.append(f'<g transform="translate({cx:.2f} {cy:.2f})">')
        for dx, dy, color in ((-7,-5,"#82cfff"),(6,-6,"#d9f1ff"),(-5,7,"#65b7e6"),(7,6,"#f4d56d")):
            lines.append('<rect x="-1" y="-1" width="2" height="2" fill="%s">' % color)
            lines.append(time_anim("opacity", [(0,"0"),(hit+0.09,"0"),(hit+0.12,"1"),(hit+0.35,"0"),(total,"0")],total,calcMode="discrete"))
            lines.append(time_anim("transform", [(0,"0 0"),(hit+0.09,"0 0"),(hit+0.35,f"{dx} {dy}"),(total,"0 0")],total,transform=True,type="translate"))
            lines.append('</rect>')
        lines.append('</g>')
    if targets:
        coord_states = [(tm, f"{x:.2f} {y:.2f}") for tm,x,y in points]
        schedule = build_frame_schedule(points,attacks,total)
        lines.append(f'<g id="viking-motion" transform="translate({points[0][1]:.2f} {points[0][2]:.2f})">')
        lines.append(time_anim("transform", coord_states,total,transform=True,type="translate"))
        lines.append(time_anim("opacity", [(0,"1"),(total-0.4,"1"),(total-0.12,"0"),(total,"1")], total))
        lines.append('<g id="viking-facing">')
        lines.append(time_anim("transform", facing+[(total,facing[0][1])],total,transform=True,type="scale",calcMode="discrete"))
        # O flip lateral é feito em torno do centro do personagem.
        lines.append(f'<g transform="translate(-20 0) scale({SPRITE_SCALE:.8f})">')
        lines.extend(frame_animations(schedule,total))
        lines.extend(['</g>','</g>','</g>'])
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
        output.write_text(make_svg(weeks, args.username, demo=args.demo), encoding="utf-8")
        print(f"SVG gerado: {output} | {len(weeks)} semanas | modo: {'DEMO' if args.demo else 'REAL'}")
    except (RuntimeError, ValueError, OSError) as err:
        print(f"ERRO: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
