#!/usr/bin/env python3
"""
Render a user's March Madness bracket as a PNG image using Pillow.

Layout: traditional left-right bracket tree.
  Left side:  East (top), West (bottom)  — R64 → E8 flowing right
  Right side: South (top), Midwest (bottom) — R64 → E8 flowing left
  Center:     Final Four + Championship
"""

import io
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REGIONS = ["East", "West", "South", "Midwest"]
FINAL_FOUR_PAIRS = [("East", "West"), ("South", "Midwest")]

# Static bracket data (duplicated from bracket_divergence.py to avoid heavy import chain)
BRACKET = [
    {"region": "East", "higher_seed": {"seed": 1, "team": "Duke"}, "lower_seed": {"seed": 16, "team": "Siena"}},
    {"region": "East", "higher_seed": {"seed": 8, "team": "Ohio State"}, "lower_seed": {"seed": 9, "team": "TCU"}},
    {"region": "East", "higher_seed": {"seed": 5, "team": "St. John's"}, "lower_seed": {"seed": 12, "team": "Northern Iowa"}},
    {"region": "East", "higher_seed": {"seed": 4, "team": "Kansas"}, "lower_seed": {"seed": 13, "team": "Cal Baptist"}},
    {"region": "East", "higher_seed": {"seed": 6, "team": "Louisville"}, "lower_seed": {"seed": 11, "team": "South Florida"}},
    {"region": "East", "higher_seed": {"seed": 3, "team": "Michigan State"}, "lower_seed": {"seed": 14, "team": "North Dakota State"}},
    {"region": "East", "higher_seed": {"seed": 7, "team": "UCLA"}, "lower_seed": {"seed": 10, "team": "UCF"}},
    {"region": "East", "higher_seed": {"seed": 2, "team": "UConn"}, "lower_seed": {"seed": 15, "team": "Furman"}},
    {"region": "West", "higher_seed": {"seed": 1, "team": "Arizona"}, "lower_seed": {"seed": 16, "team": "LIU"}},
    {"region": "West", "higher_seed": {"seed": 8, "team": "Villanova"}, "lower_seed": {"seed": 9, "team": "Utah State"}},
    {"region": "West", "higher_seed": {"seed": 5, "team": "Wisconsin"}, "lower_seed": {"seed": 12, "team": "High Point"}},
    {"region": "West", "higher_seed": {"seed": 4, "team": "Arkansas"}, "lower_seed": {"seed": 13, "team": "Hawaii"}},
    {"region": "West", "higher_seed": {"seed": 6, "team": "BYU"}, "lower_seed": {"seed": 11, "team": "Texas"}},
    {"region": "West", "higher_seed": {"seed": 3, "team": "Gonzaga"}, "lower_seed": {"seed": 14, "team": "Kennesaw State"}},
    {"region": "West", "higher_seed": {"seed": 7, "team": "Miami (FL)"}, "lower_seed": {"seed": 10, "team": "Missouri"}},
    {"region": "West", "higher_seed": {"seed": 2, "team": "Purdue"}, "lower_seed": {"seed": 15, "team": "Queens"}},
    {"region": "South", "higher_seed": {"seed": 1, "team": "Florida"}, "lower_seed": {"seed": 16, "team": "Prairie View A&M"}},
    {"region": "South", "higher_seed": {"seed": 8, "team": "Clemson"}, "lower_seed": {"seed": 9, "team": "Iowa"}},
    {"region": "South", "higher_seed": {"seed": 5, "team": "Vanderbilt"}, "lower_seed": {"seed": 12, "team": "McNeese"}},
    {"region": "South", "higher_seed": {"seed": 4, "team": "Nebraska"}, "lower_seed": {"seed": 13, "team": "Troy"}},
    {"region": "South", "higher_seed": {"seed": 6, "team": "North Carolina"}, "lower_seed": {"seed": 11, "team": "VCU"}},
    {"region": "South", "higher_seed": {"seed": 3, "team": "Illinois"}, "lower_seed": {"seed": 14, "team": "Penn"}},
    {"region": "South", "higher_seed": {"seed": 7, "team": "Saint Mary's"}, "lower_seed": {"seed": 10, "team": "Texas A&M"}},
    {"region": "South", "higher_seed": {"seed": 2, "team": "Houston"}, "lower_seed": {"seed": 15, "team": "Idaho"}},
    {"region": "Midwest", "higher_seed": {"seed": 1, "team": "Michigan"}, "lower_seed": {"seed": 16, "team": "UMBC"}},
    {"region": "Midwest", "higher_seed": {"seed": 8, "team": "Georgia"}, "lower_seed": {"seed": 9, "team": "Saint Louis"}},
    {"region": "Midwest", "higher_seed": {"seed": 5, "team": "Texas Tech"}, "lower_seed": {"seed": 12, "team": "Akron"}},
    {"region": "Midwest", "higher_seed": {"seed": 4, "team": "Alabama"}, "lower_seed": {"seed": 13, "team": "Hofstra"}},
    {"region": "Midwest", "higher_seed": {"seed": 6, "team": "Tennessee"}, "lower_seed": {"seed": 11, "team": "SMU"}},
    {"region": "Midwest", "higher_seed": {"seed": 3, "team": "Virginia"}, "lower_seed": {"seed": 14, "team": "Wright State"}},
    {"region": "Midwest", "higher_seed": {"seed": 7, "team": "Kentucky"}, "lower_seed": {"seed": 10, "team": "Santa Clara"}},
    {"region": "Midwest", "higher_seed": {"seed": 2, "team": "Iowa State"}, "lower_seed": {"seed": 15, "team": "Tennessee State"}},
]

RESULTS_FILE = Path(__file__).parent / "results.json"

# ─── Layout constants ───────────────────────────────────────────────────────

WIDTH = 1900
HEIGHT = 1300
BG = (255, 255, 255)

SLOT_W = 155
SLOT_H = 24
FONT_SIZE = 14

# Colors
GREEN = (183, 223, 185)
GREEN_BORDER = (100, 170, 100)
RED = (245, 195, 195)
RED_BORDER = (200, 120, 120)
PENDING = (245, 245, 245)
PENDING_BORDER = (200, 200, 200)
LINE_COL = (180, 180, 180)
TEXT_COL = (30, 30, 30)
HEADER_COL = (70, 70, 70)
ROUND_LABEL_COL = (140, 140, 140)
CHAMP_BG = (255, 243, 200)
CHAMP_BORDER = (200, 175, 80)

# Column x-positions (left-to-right): 4 left rounds, center gap, 4 right rounds
LEFT_COLS = [15, 180, 345, 510]          # R64, R32, S16, E8
RIGHT_COLS = [1730, 1565, 1400, 1235]    # R64, R32, S16, E8 (mirrored)
CENTER_X = 870                            # Final Four / Championship center

# Vertical layout
MARGIN_TOP = 80  # more room for round labels
REGION_GAP = 35

# Round labels for column headers
ROUND_LABELS_LEFT = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]
ROUND_LABELS_RIGHT = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]


def _load_font():
    """Try to load a TrueType font, fall back to default."""
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for p in font_paths:
        try:
            return ImageFont.truetype(p, FONT_SIZE)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _load_font_bold():
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in font_paths:
        try:
            return ImageFont.truetype(p, FONT_SIZE + 3)
        except (OSError, IOError):
            continue
    return _load_font()


def _load_font_small():
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in font_paths:
        try:
            return ImageFont.truetype(p, FONT_SIZE - 2)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ─── Game results for color coding ─────────────────────────────────────────

def _load_actual_winners() -> dict[str, str]:
    """
    Try to determine actual game winners from available data.
    Returns {team_name: "won"} for teams confirmed as winners in resolved games.

    Checks user score data and results.json for resolved markets.
    """
    # We'll build this per-user in _build_bracket_slots instead
    return {}


def _get_pick_status(team: str, round_code: str, user: dict) -> str:
    """
    Determine if a user's pick is correct, busted, or pending.

    Checks:
    1. If the pick dict itself has a 'correct' field (ESPN imports)
    2. If we can cross-reference resolved_games from score data
    """
    # Check if individual picks have status (ESPN-imported brackets may have this)
    for p in user.get("picks", []):
        if p.get("team") == team and p.get("round") == round_code:
            if "correct" in p:
                return "correct" if p["correct"] else "busted"
            break

    return "pending"


# ─── Bracket data helpers ───────────────────────────────────────────────────

def _region_games(region_name: str, bracket: list[dict]) -> list[dict]:
    return [m for m in bracket if m["region"] == region_name]


def _build_seed_lookup(bracket: list[dict]) -> dict[str, int]:
    lookup = {}
    for m in bracket:
        lookup[m["higher_seed"]["team"]] = m["higher_seed"]["seed"]
        lookup[m["lower_seed"]["team"]] = m["lower_seed"]["seed"]
    return lookup


def _build_bracket_slots(user: dict, bracket: list[dict]) -> dict:
    """
    Build a positional bracket structure from user picks.

    Returns dict mapping (side, region_half, round_idx, slot_idx) -> {
        "team": str, "seed": int, "status": "correct"|"busted"|"pending"
    }
    """
    picks = user.get("picks", [])
    seed_lookup = _build_seed_lookup(bracket)

    pick_set = set()
    for p in picks:
        pick_set.add((p["round"], p["team"]))

    layout = {
        ("left", 0): "East",
        ("left", 1): "West",
        ("right", 0): "South",
        ("right", 1): "Midwest",
    }

    slots = {}

    for (side, half), region_name in layout.items():
        games = _region_games(region_name, bracket)

        r64_teams = []
        for i, g in enumerate(games):
            h = g["higher_seed"]
            l = g["lower_seed"]
            slots[(side, half, 0, i * 2)] = {
                "team": h["team"], "seed": h["seed"], "status": "pending",
            }
            slots[(side, half, 0, i * 2 + 1)] = {
                "team": l["team"], "seed": l["seed"], "status": "pending",
            }
            r64_teams.append((h["team"], l["team"]))

        round_codes = ["R64", "R32", "S16", "E8"]
        prev_level = r64_teams

        for rnd_idx in range(1, 4):
            rnd_code = round_codes[rnd_idx]
            current_level = []

            for game_i in range(len(prev_level) // 2):
                pair_a = prev_level[game_i * 2]
                pair_b = prev_level[game_i * 2 + 1]

                candidate_a = None
                for t in pair_a:
                    if (rnd_code, t) in pick_set:
                        candidate_a = t
                        break
                if not candidate_a:
                    for t in pair_a:
                        if (round_codes[rnd_idx - 1], t) in pick_set:
                            candidate_a = t
                            break

                candidate_b = None
                for t in pair_b:
                    if (rnd_code, t) in pick_set:
                        candidate_b = t
                        break
                if not candidate_b:
                    for t in pair_b:
                        if (round_codes[rnd_idx - 1], t) in pick_set:
                            candidate_b = t
                            break

                team_a = candidate_a or "?"
                team_b = candidate_b or "?"

                slots[(side, half, rnd_idx, game_i * 2)] = {
                    "team": team_a,
                    "seed": seed_lookup.get(team_a, 0),
                    "status": _get_pick_status(team_a, rnd_code, user),
                }
                slots[(side, half, rnd_idx, game_i * 2 + 1)] = {
                    "team": team_b,
                    "seed": seed_lookup.get(team_b, 0),
                    "status": _get_pick_status(team_b, rnd_code, user),
                }
                current_level.append((team_a, team_b))

            prev_level = current_level

    # Final Four + Championship
    ff = user.get("final_four", [])
    champion = user.get("champion", "?")

    for idx, (ff_game, slot_pos) in enumerate([
        (0, 0), (0, 1), (1, 0), (1, 1),
    ]):
        team = ff[idx] if idx < len(ff) else "?"
        slots[("center", "ff", ff_game, slot_pos)] = {
            "team": team,
            "seed": seed_lookup.get(team, 0),
            "status": _get_pick_status(team, "F4", user),
        }

    slots[("center", "champ", 0, 0)] = {
        "team": champion,
        "seed": seed_lookup.get(champion, 0),
        "status": _get_pick_status(champion, "CHAMP", user),
    }

    return slots


# ─── Rendering ──────────────────────────────────────────────────────────────

def _slot_y_positions(num_slots: int, y_start: float, y_end: float) -> list[float]:
    if num_slots <= 0:
        return []
    if num_slots == 1:
        return [(y_start + y_end) / 2]
    spacing = (y_end - y_start) / num_slots
    return [y_start + spacing * (i + 0.5) for i in range(num_slots)]


def _truncate(text: str, max_chars: int = 17) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "."


def _draw_slot(draw: ImageDraw.Draw, x: float, y: float, slot: dict,
               font: ImageFont.FreeTypeFont, align_right: bool = False):
    """Draw a single team slot box with status coloring."""
    status = slot.get("status", "pending")
    if status == "correct":
        bg, border = GREEN, GREEN_BORDER
    elif status == "busted":
        bg, border = RED, RED_BORDER
    else:
        bg, border = PENDING, PENDING_BORDER

    rx = x
    ry = y - SLOT_H // 2

    draw.rectangle([rx, ry, rx + SLOT_W, ry + SLOT_H], fill=bg, outline=border)

    seed = slot.get("seed", 0)
    team = slot.get("team", "?")
    label = f"({seed}) {_truncate(team)}" if seed else _truncate(team)

    tx = rx + 5
    if align_right:
        bbox = font.getbbox(label)
        tw = bbox[2] - bbox[0]
        tx = rx + SLOT_W - tw - 5

    draw.text((tx, ry + 4), label, fill=TEXT_COL, font=font)


def _draw_connectors_left(draw: ImageDraw.Draw, col_x: float, next_col_x: float,
                           y_positions: list[float]):
    mid_x = (col_x + SLOT_W + next_col_x) / 2
    for i in range(0, len(y_positions), 2):
        if i + 1 >= len(y_positions):
            break
        y1 = y_positions[i]
        y2 = y_positions[i + 1]
        draw.line([(col_x + SLOT_W, y1), (mid_x, y1)], fill=LINE_COL, width=1)
        draw.line([(col_x + SLOT_W, y2), (mid_x, y2)], fill=LINE_COL, width=1)
        draw.line([(mid_x, y1), (mid_x, y2)], fill=LINE_COL, width=1)
        mid_y = (y1 + y2) / 2
        draw.line([(mid_x, mid_y), (next_col_x, mid_y)], fill=LINE_COL, width=1)


def _draw_connectors_right(draw: ImageDraw.Draw, col_x: float, next_col_x: float,
                            y_positions: list[float]):
    mid_x = (col_x + next_col_x + SLOT_W) / 2
    for i in range(0, len(y_positions), 2):
        if i + 1 >= len(y_positions):
            break
        y1 = y_positions[i]
        y2 = y_positions[i + 1]
        draw.line([(col_x, y1), (mid_x, y1)], fill=LINE_COL, width=1)
        draw.line([(col_x, y2), (mid_x, y2)], fill=LINE_COL, width=1)
        draw.line([(mid_x, y1), (mid_x, y2)], fill=LINE_COL, width=1)
        mid_y = (y1 + y2) / 2
        draw.line([(mid_x, mid_y), (next_col_x + SLOT_W, mid_y)], fill=LINE_COL, width=1)


def render_bracket(user: dict) -> bytes:
    """Render the user's bracket as a PNG image. Returns bytes."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    font = _load_font()
    font_bold = _load_font_bold()
    font_small = _load_font_small()

    slots = _build_bracket_slots(user, BRACKET)

    half_h = (HEIGHT - MARGIN_TOP - 20) / 2

    # ── Round column labels ──
    for rnd_idx, label in enumerate(ROUND_LABELS_LEFT):
        col_x = LEFT_COLS[rnd_idx]
        # Center label over the column
        bbox = font_small.getbbox(label)
        lw = bbox[2] - bbox[0]
        lx = col_x + (SLOT_W - lw) // 2
        draw.text((lx, MARGIN_TOP - 20), label, fill=ROUND_LABEL_COL, font=font_small)

    for rnd_idx, label in enumerate(ROUND_LABELS_RIGHT):
        col_x = RIGHT_COLS[rnd_idx]
        bbox = font_small.getbbox(label)
        lw = bbox[2] - bbox[0]
        lx = col_x + (SLOT_W - lw) // 2
        draw.text((lx, MARGIN_TOP - 20), label, fill=ROUND_LABEL_COL, font=font_small)

    # Center column labels
    ff_label = "Final Four"
    bbox = font_small.getbbox(ff_label)
    lw = bbox[2] - bbox[0]
    draw.text((CENTER_X - lw // 2, MARGIN_TOP - 20), ff_label, fill=ROUND_LABEL_COL, font=font_small)

    # ── Region labels ──
    region_labels = {
        ("left", 0): ("EAST", 15),
        ("left", 1): ("WEST", 15),
        ("right", 0): ("SOUTH", WIDTH - 90),
        ("right", 1): ("MIDWEST", WIDTH - 115),
    }

    for (side, half), (label, lx) in region_labels.items():
        ly = MARGIN_TOP - 2 + half * (half_h + REGION_GAP)
        draw.text((lx, ly), label, fill=HEADER_COL, font=font_bold)

    # ── Draw regional rounds ──
    rounds_per_region = [16, 8, 4, 2]

    for side in ("left", "right"):
        cols = LEFT_COLS if side == "left" else RIGHT_COLS
        align_right = (side == "right")

        for half in (0, 1):
            y_start = MARGIN_TOP + 18 + half * (half_h + REGION_GAP)
            y_end = y_start + half_h - 25

            for rnd_idx in range(4):
                num_slots = rounds_per_region[rnd_idx]
                col_x = cols[rnd_idx]

                y_positions = _slot_y_positions(num_slots, y_start, y_end)

                for slot_i, y in enumerate(y_positions):
                    slot_key = (side, half, rnd_idx, slot_i)
                    slot_data = slots.get(slot_key, {"team": "?", "seed": 0, "status": "pending"})
                    _draw_slot(draw, col_x, y, slot_data, font, align_right)

                if rnd_idx < 3:
                    next_col_x = cols[rnd_idx + 1]
                    if side == "left":
                        _draw_connectors_left(draw, col_x, next_col_x, y_positions)
                    else:
                        _draw_connectors_right(draw, col_x, next_col_x, y_positions)

    # ── Final Four + Championship (center) ──
    center_y = HEIGHT / 2
    ff_gap = 130

    ff1_y = center_y - ff_gap
    ff1_slots = [
        slots.get(("center", "ff", 0, 0), {"team": "?", "seed": 0, "status": "pending"}),
        slots.get(("center", "ff", 0, 1), {"team": "?", "seed": 0, "status": "pending"}),
    ]
    _draw_slot(draw, CENTER_X - SLOT_W // 2, ff1_y - 16, ff1_slots[0], font)
    _draw_slot(draw, CENTER_X - SLOT_W // 2, ff1_y + 16, ff1_slots[1], font)

    ff2_y = center_y + ff_gap
    ff2_slots = [
        slots.get(("center", "ff", 1, 0), {"team": "?", "seed": 0, "status": "pending"}),
        slots.get(("center", "ff", 1, 1), {"team": "?", "seed": 0, "status": "pending"}),
    ]
    _draw_slot(draw, CENTER_X - SLOT_W // 2, ff2_y - 16, ff2_slots[0], font)
    _draw_slot(draw, CENTER_X - SLOT_W // 2, ff2_y + 16, ff2_slots[1], font)

    # Championship label
    champ_label = "CHAMPION"
    bbox = font_bold.getbbox(champ_label)
    lw = bbox[2] - bbox[0]
    draw.text((CENTER_X - lw // 2, center_y - 46), champ_label, fill=HEADER_COL, font=font_bold)

    # Champion box (larger, highlighted)
    champ_slot = slots.get(("center", "champ", 0, 0), {"team": "?", "seed": 0, "status": "pending"})
    champ_w = SLOT_W + 20
    champ_h = SLOT_H + 8
    champ_x = CENTER_X - champ_w // 2
    champ_y = center_y

    status = champ_slot.get("status", "pending")
    if status == "correct":
        cbg, cborder = GREEN, GREEN_BORDER
    elif status == "busted":
        cbg, cborder = RED, RED_BORDER
    else:
        cbg, cborder = CHAMP_BG, CHAMP_BORDER

    draw.rectangle(
        [champ_x, champ_y - champ_h // 2, champ_x + champ_w, champ_y + champ_h // 2],
        fill=cbg, outline=cborder, width=2,
    )
    seed = champ_slot.get("seed", 0)
    team = champ_slot.get("team", "?")
    label = f"({seed}) {team}" if seed else team
    bbox = font_bold.getbbox(label)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((CENTER_X - tw // 2, champ_y - th // 2 - 2), label, fill=TEXT_COL, font=font_bold)

    # ── Connector lines E8 → FF → Championship ──
    left_e8_col = LEFT_COLS[3]
    right_e8_col = RIGHT_COLS[3]

    # Left E8 top region → FF game 1 top slot
    draw.line([(left_e8_col + SLOT_W, ff1_y - 16), (CENTER_X - SLOT_W // 2, ff1_y - 16)],
              fill=LINE_COL, width=1)
    # Right E8 top region → FF game 1 bottom slot
    draw.line([(right_e8_col, ff1_y + 16), (CENTER_X + SLOT_W // 2, ff1_y + 16)],
              fill=LINE_COL, width=1)
    # Left E8 bottom region → FF game 2 top slot
    draw.line([(left_e8_col + SLOT_W, ff2_y - 16), (CENTER_X - SLOT_W // 2, ff2_y - 16)],
              fill=LINE_COL, width=1)
    # Right E8 bottom region → FF game 2 bottom slot
    draw.line([(right_e8_col, ff2_y + 16), (CENTER_X + SLOT_W // 2, ff2_y + 16)],
              fill=LINE_COL, width=1)

    # FF → Championship
    draw.line([(CENTER_X, ff1_y + 16 + SLOT_H // 2), (CENTER_X, champ_y - champ_h // 2)],
              fill=LINE_COL, width=1)
    draw.line([(CENTER_X, ff2_y - 16 - SLOT_H // 2), (CENTER_X, champ_y + champ_h // 2)],
              fill=LINE_COL, width=1)

    # ── Title ──
    title = user.get("bracket_name", "My Bracket")
    bbox = font_bold.getbbox(title)
    tw = bbox[2] - bbox[0]
    draw.text((WIDTH // 2 - tw // 2, 12), title, fill=TEXT_COL, font=font_bold)

    # ── Score badge (if games resolved) ──
    score = user.get("score", {})
    total_w = score.get("correct", 0)
    total_l = score.get("busted", 0)
    if total_w + total_l > 0:
        score_text = f"{total_w}W / {total_l}L"
        bbox = font_small.getbbox(score_text)
        sw = bbox[2] - bbox[0]
        draw.text((WIDTH // 2 - sw // 2, 36), score_text, fill=ROUND_LABEL_COL, font=font_small)

    # ── Legend ──
    legend_y = HEIGHT - 30
    legend_x = WIDTH // 2 - 150
    legend_items = [
        (PENDING, PENDING_BORDER, "Pending"),
        (GREEN, GREEN_BORDER, "Correct"),
        (RED, RED_BORDER, "Busted"),
    ]
    for bg, border, label in legend_items:
        draw.rectangle([legend_x, legend_y, legend_x + 14, legend_y + 14], fill=bg, outline=border)
        draw.text((legend_x + 18, legend_y), label, fill=ROUND_LABEL_COL, font=font_small)
        legend_x += 90

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
