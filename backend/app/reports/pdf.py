"""PDF report for a saved scenario (squad-builder team or club-improvement plan).

One A4 page: the plan's key figures, the XI on a pitch, the signings (club plans), the
requirements it was found with, and the full XI as a table. Drawn with ReportLab; fonts are
Archivo (SIL Open Font License, see fonts/OFL.txt), which covers Balkan and Turkish letters.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from app.optimization.model import SLOTS

# --- look (the site's design tokens) -----------------------------------------------------------
BOARD, CHALK, INK = HexColor("#22343C"), HexColor("#EEF2EF"), HexColor("#1C2A30")
SOFT, FAINT, MARKER = HexColor("#4C5D63"), HexColor("#55656A"), HexColor("#F2C230")
RULE, SUNK = HexColor("#CAD4CF"), HexColor("#E4EAE6")

FONT_DIR = Path(__file__).with_name("fonts")
REG, SEMI, BOLD, DISPLAY = "Archivo", "Archivo-SemiBold", "Archivo-Bold", "Archivo-CondensedExtraBold"
_FILES = {REG: "Archivo-Regular.ttf", SEMI: "Archivo-SemiBold.ttf", BOLD: "Archivo-Bold.ttf",
          DISPLAY: "ArchivoCondensed-ExtraBold.ttf"}


def _register_fonts() -> None:
    for name, file in _FILES.items():
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))


ROLE_NAMES = {"GK": "Goalkeeper", "CB": "Centre-back", "FB": "Full-back", "CM": "Central midfielder",
              "AW": "Attacking / wide", "ST": "Striker"}

# where each slot sits on the pitch (x, y in % of width/height, attack upwards); same as the site
_BACK4 = {"GK": (50, 90), "LB": (14, 70), "LCB": (37, 75), "RCB": (63, 75), "RB": (86, 70)}
_BACK3 = {"GK": (50, 90), "LCB": (26, 74), "CB": (50, 76), "RCB": (74, 74)}
SLOT_XY = {
    "4-3-3": {**_BACK4, "LCM": (27, 50), "CM": (50, 54), "RCM": (73, 50), "LW": (18, 26), "ST": (50, 19), "RW": (82, 26)},
    "4-2-3-1": {**_BACK4, "LDM": (37, 57), "RDM": (63, 57), "LAM": (19, 36), "CAM": (50, 38), "RAM": (81, 36), "ST": (50, 18)},
    "4-4-2": {**_BACK4, "LM": (13, 45), "LCM": (38, 51), "RCM": (62, 51), "RM": (87, 45), "LST": (38, 21), "RST": (62, 21)},
    "3-5-2": {**_BACK3, "LWB": (10, 49), "LCM": (31, 52), "CM": (50, 56), "RCM": (69, 52), "RWB": (90, 49),
              "LST": (38, 21), "RST": (62, 21)},
    "3-4-3": {**_BACK3, "LWB": (11, 50), "LCM": (38, 54), "RCM": (62, 54), "RWB": (89, 50), "LW": (20, 26),
              "ST": (50, 19), "RW": (80, 26)},
}


# --- small helpers -------------------------------------------------------------------------------
def eur(v: int | float | None) -> str:
    if v is None:
        return "–"
    if v >= 1_000_000:
        m = v / 1_000_000
        return f"€{m:.0f}m" if m >= 10 or m == int(m) else f"€{m:.1f}m"
    if v >= 1_000:
        return f"€{v / 1000:.0f}k"
    return f"€{v:.0f}"


def signed(v: float) -> str:
    return f"{'+' if v > 0 else ''}{v:.1f}"


def surname(name: str) -> str:
    parts = name.split()
    return " ".join(parts[1:]) if len(parts) > 1 else name


def fit(text: str, font: str, size: float, width: float) -> str:
    """The text, shortened with an ellipsis if it is wider than `width`."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def replacements(current: list[dict], nxt: list[dict]) -> dict[int, dict | None]:
    """Which current starter each signing replaces (same rule as the site)."""
    next_ids = {p["player_id"] for p in nxt}
    dropped = sorted((p for p in current if p["player_id"] not in next_ids), key=lambda p: p["score"])
    out: dict[int, dict | None] = {}
    for s in sorted((p for p in nxt if p.get("signing")), key=lambda p: -p["score"]):
        i = next((k for k, d in enumerate(dropped) if d["role"] == s["role"]), None)
        out[s["player_id"]] = dropped.pop(i) if i is not None else None
    return out


def requirement_lines(req: dict, mode: str, league_names: dict[int, str]) -> list[str]:
    """The settings a plan was found with, in plain words."""
    lines = [f"Formation {req['formation']}, budget {eur(req['budget_eur'])}"]
    if mode == "improve":
        lines.append(f"At most {req.get('max_signings', 2)} signings")
        if req.get("signing_roles"):
            lines.append("Signings only as: " + ", ".join(ROLE_NAMES.get(r, r).lower() for r in req["signing_roles"]))
        if req.get("locked_player_ids"):
            lines.append(f"{len(req['locked_player_ids'])} own player(s) locked in the XI")
        if req.get("left_player_ids"):
            lines.append(f"{len(req['left_player_ids'])} player(s) marked as having left")
    a, b = req.get("age_min"), req.get("age_max")
    if a or b:
        lines.append(f"Age {a} to {b}" if a and b else f"Age {a} or older" if a else f"Age {b} or younger")
    if req.get("max_price_eur"):
        lines.append(f"Highest price {eur(req['max_price_eur'])}")
    if req.get("league_ids"):
        lines.append("Leagues: " + ", ".join(league_names.get(i, f"league {i}") for i in req["league_ids"]))
    if req.get("nationalities"):
        lines.append("Nationality: " + ", ".join(req["nationalities"]))
    mins, nxt = req.get("min_minutes", 900), req.get("min_minutes_next", 900)
    lines.append(f"At least {mins:,} league minutes in 2024/25" + (f" and {nxt:,} in 2025/26" if nxt else ""))
    lines.append("Scores adjusted for league strength" if req.get("score") == "adjusted" else "Scores within each league")
    return lines


# --- drawing -------------------------------------------------------------------------------------
W, H = A4
M = 40  # page margin


class _Page:
    def __init__(self, c: Canvas):
        self.c = c

    def text(self, x, y, s, font=REG, size=9, color=INK, align="left", alpha=1.0):
        c = self.c
        c.setFont(font, size)
        c.setFillColor(color)
        c.setFillAlpha(alpha)
        {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](x, y, s)
        c.setFillAlpha(1)

    def para(self, x, y, s, width, font=REG, size=8, color=SOFT, leading=None) -> float:
        """Wrapped text from the top line at y; returns the y below it."""
        leading = leading or size * 1.35
        for line in simpleSplit(s, font, size, width):
            self.text(x, y, line, font, size, color)
            y -= leading
        return y


def _pitch(p: _Page, x: float, y: float, w: float, players: list[dict], formation: str, own: set[int] | None):
    """The XI on a chalk board; (x, y) is the bottom-left corner, height is 1.5 x width."""
    c, h = p.c, w * 1.5
    c.setFillColor(BOARD)
    c.roundRect(x, y, w, h, 6, stroke=0, fill=1)
    sx, sy = w / 100, h / 150

    def X(u):
        return x + u * sx

    def Y(v):
        return y + h - v * sy

    c.setStrokeColor(CHALK)
    c.setStrokeAlpha(0.5)
    c.setLineWidth(0.6)
    c.rect(X(3), Y(147), 94 * sx, 144 * sy)
    c.line(X(3), Y(75), X(97), Y(75))
    c.circle(X(50), Y(75), 12.6 * sx)
    for top in (3, 123.4):
        c.rect(X(20.4), Y(top + 23.6), 59.2 * sx, 23.6 * sy)
    c.rect(X(36.5), Y(10.9), 27 * sx, 7.9 * sy)
    c.rect(X(36.5), Y(147), 27 * sx, 7.9 * sy)
    c.setStrokeAlpha(1)

    xy = SLOT_XY.get(formation, {})
    rows: dict[str, list[dict]] = {}
    if not all(pl["slot"] in xy for pl in players):  # unknown formation: one row per role
        for pl in players:
            rows.setdefault(pl["role"], []).append(pl)
        row_y = {"GK": 90, "CB": 74, "FB": 64, "CM": 51, "AW": 34, "ST": 19}
        xy = {}
        for role, group in rows.items():
            for i, pl in enumerate(group):
                xy[pl["slot"] + str(pl["player_id"])] = ((i + 1) / (len(group) + 1) * 100, row_y[role])
    r = w * 0.058
    for pl in players:
        u, v = xy.get(pl["slot"]) or xy.get(pl["slot"] + str(pl["player_id"]), (50, 50))
        cx, cy = x + u / 100 * w, y + h - v / 100 * h   # slot positions are % of width and height
        new = bool(pl.get("signing"))
        c.setFillColor(BOARD)
        c.setStrokeColor(MARKER if new else CHALK)
        c.setLineWidth(2 if new else 0.9)
        c.circle(cx, cy, r, stroke=1, fill=1)
        p.text(cx, cy - 3.6, f"{pl['score']:.0f}", BOLD, 10.5, CHALK, "center")
        p.text(cx, cy - r - 9, fit(surname(pl["name"]), SEMI, 7.2, w * 0.26), SEMI, 7.2, CHALK, "center")
        sub = "Own player" if own is not None and pl["player_id"] in own else eur(pl["price_eur"])
        p.text(cx, cy - r - 17.5, sub, REG, 6.2, CHALK, "center", alpha=0.75)


def _figure(p: _Page, x: float, y: float, big: str, label: str, size: float = 26):
    p.text(x, y, big, DISPLAY, size, INK)
    p.text(x, y - 13, label, REG, 8, SOFT)


def _table(p: _Page, y: float, players: list[dict], formation: str, own: set[int] | None, adjusted: bool) -> float:
    cols = [("Pos.", 30, "left"), ("Player", 118, "left"), ("Age", 24, "right"),
            ("Club and league, 2024/25", 150, "left"), ("Min. 24/25", 46, "right"),
            ("Reliability", 48, "left"), ("Score", 30, "right"), ("Price", 37, "right")]
    x0 = M
    c = p.c
    order = [s for s, _ in SLOTS.get(formation, [])]
    players = sorted(players, key=lambda pl: order.index(pl["slot"]) if pl["slot"] in order else 99)
    # header
    x = x0
    for name, w, align in cols:
        p.text(x + (w if align == "right" else 0), y, name, SEMI, 7.5, FAINT, align)
        x += w + 4
    y -= 5
    c.setStrokeColor(RULE)
    c.setLineWidth(0.6)
    c.line(M, y, W - M, y)
    row_h = 16.5
    for pl in players:
        y -= row_h
        if pl.get("signing"):
            c.setFillColor(MARKER)
            c.rect(M, y - 4.5, 2.5, row_h - 1, stroke=0, fill=1)
        tag = " (new)" if pl.get("signing") else ""
        values = [
            pl["slot"],
            fit(pl["name"], SEMI, 8.5, 116 - pdfmetrics.stringWidth(tag, REG, 7.5)),
            str(pl["age"]) if pl.get("age") is not None else "–",
            fit(f"{pl['club_2024_25']} ({pl['league']})", REG, 8, 148),
            f"{pl['minutes_2024_25']:,}",
            pl["reliability"].capitalize(),
            f"{pl['score']:.1f}",
            "Own" if own is not None and pl["player_id"] in own else eur(pl["price_eur"]),
        ]
        x = x0
        for k, ((_, w, align), val) in enumerate(zip(cols, values)):
            font = SEMI if k in (1, 6) else REG
            size = 8.5 if k in (1, 6) else 8
            if k == 0:
                p.text(x + 5, y, val, font, size, SOFT)
            else:
                p.text(x + (w if align == "right" else 0), y, val, font, size, INK, align)
            if k == 1 and tag:
                p.text(x + pdfmetrics.stringWidth(val, SEMI, 8.5), y, tag, REG, 7.5, SOFT)
            x += w + 4
        c.setStrokeColor(RULE)
        c.setLineWidth(0.3)
        c.line(M, y - 5, W - M, y - 5)
    note = ("Scores 0–100, adjusted for league strength. " if adjusted else "Scores 0–100, compared within each league. ")
    p.text(M, y - 17, note + "Prices are Transfermarkt market values, not transfer fees.", REG, 7, FAINT)
    return y - 17


def scenario_pdf(s: dict, league_names: dict[int, str] | None = None, generated: datetime | None = None) -> bytes:
    """Render a saved scenario (as returned by GET /scenarios/{id}) to PDF bytes."""
    _register_fonts()
    league_names = league_names or {}
    buf = BytesIO()
    c = Canvas(buf, pagesize=A4, pageCompression=1)
    c.setTitle(s["name"])
    c.setAuthor("ScoutIQ")
    c.setSubject("ScoutIQ scenario report")
    p = _Page(c)
    req, res, mode = s["request"], s["result"], s["mode"]
    improve = mode == "improve"
    formation = req["formation"]
    saved = s["created_at"] if isinstance(s["created_at"], datetime) else datetime.fromisoformat(str(s["created_at"]))

    # header band
    top = H - M
    c.setFillColor(BOARD)
    c.roundRect(M, top - 74, W - 2 * M, 74, 6, stroke=0, fill=1)
    size = 24
    while size > 15 and pdfmetrics.stringWidth(s["name"], DISPLAY, size) > W - 2 * M - 110:
        size -= 1
    p.text(M + 18, top - 36, fit(s["name"], DISPLAY, size, W - 2 * M - 110), DISPLAY, size, CHALK)
    kind = (f"Club plan for {s['club_name']}" if s.get("club_name") else "Club plan") if improve else "Squad-builder team"
    p.text(M + 18, top - 55, f"{kind}, {formation}. Saved {saved.day} {saved:%b %Y}.", REG, 9, CHALK, alpha=0.8)
    p.text(W - M - 18, top - 36, "ScoutIQ", BOLD, 13, CHALK, "right")
    p.text(W - M - 18, top - 50, "Scouting report", REG, 7.5, CHALK, "right", alpha=0.7)

    team = res.get("team")
    y = top - 74 - 40
    if not team:
        p.text(M, y, "No plan was possible with these requirements." if improve
               else "No team was possible with these requirements.", BOLD, 13, INK)
        y -= 18
        diag = res.get("diagnosis") or {}
        if diag.get("reason"):
            reason = diag["reason"]
            y = p.para(M, y, reason[:1].upper() + reason[1:] + ("" if reason.endswith(".") else "."), W - 2 * M, REG, 9.5, SOFT)
        for sug in diag.get("suggestions", []):
            change = sug["change"][:1].upper() + sug["change"][1:]
            y = p.para(M + 10, y - 2, f"– {change}: total score {sug['total_score']:.1f}, cost {eur(sug['cost_eur'])}",
                       W - 2 * M - 10, REG, 9, INK)
        y -= 14
        p.text(M, y, "Requirements", SEMI, 10, INK)
        for line in requirement_lines(req, mode, league_names):
            y -= 13
            p.text(M, y, line, REG, 8.5, SOFT)
        _footer(p, generated)
        c.save()
        return buf.getvalue()

    players = team["players"]
    own = set(req.get("owned_player_ids", [])) if improve else None
    signings = [pl for pl in players if pl.get("signing")]

    # key figures
    if improve and res.get("current"):
        cur = res["current"]["total_score"]
        _figure(p, M, y, signed(team["total_score"] - cur), f"XI total score, {cur:.1f} to {team['total_score']:.1f}")
    else:
        _figure(p, M, y, f"{team['total_score']:.1f}", "XI total score (11 players)")
    _figure(p, M + 185, y, eur(team["cost_eur"]), f"spent of {eur(res['budget_eur'])} budget", 20)
    if improve:
        _figure(p, M + 330, y, str(len(signings)), f"signing{'s' if len(signings) != 1 else ''} "
                f"(at most {req.get('max_signings', 2)})", 20)
    else:
        ages = [pl["age"] for pl in players if pl.get("age") is not None]
        if ages:
            _figure(p, M + 330, y, f"{sum(ages) / len(ages):.1f}", "average age", 20)

    # pitch (left) and side column (right)
    pitch_w = 228
    pitch_top = y - 34
    _pitch(p, M, pitch_top - pitch_w * 1.5, pitch_w, players, formation, own)
    sx = M + pitch_w + 22
    sw = W - M - sx
    sy = pitch_top - 10
    if improve:
        p.text(sx, sy, "Signings", BOLD, 11, INK)
        sy -= 16
        if not signings:
            sy = p.para(sx, sy, "No affordable signing is better than the current starters: this is the best XI as it is.",
                        sw, REG, 8.5, SOFT)
        repl = replacements(res["current"]["players"], players) if res.get("current") else {}
        for pl in sorted(signings, key=lambda q: -q["score"]):
            r = repl.get(pl["player_id"])
            p.text(sx, sy, fit(pl["name"], SEMI, 9.5, sw - 70), SEMI, 9.5, INK)
            p.text(sx + sw, sy, f"{pl['score']:.1f}", BOLD, 9.5, INK, "right")
            sy -= 11
            p.text(sx, sy, fit(f"{ROLE_NAMES.get(pl['role'], pl['role'])}, {pl.get('age') or '–'}, "
                               f"{pl['club_2024_25']}", REG, 7.5, sw - 40), REG, 7.5, SOFT)
            p.text(sx + sw, sy, eur(pl["price_eur"]), REG, 7.5, SOFT, "right")
            sy -= 10
            p.text(sx, sy, fit(f"Replaces {r['name']} ({r['score']:.1f}), {signed(pl['score'] - r['score'])}" if r
                               else "Fills an empty place in the XI", REG, 7.5, sw), REG, 7.5, FAINT)
            sy -= 15
        sy -= 4
    p.text(sx, sy, "Found with", BOLD, 11, INK)
    sy -= 15
    for line in requirement_lines(req, mode, league_names):
        sy = p.para(sx, sy, line, sw, REG, 8, SOFT, leading=10.5)
    alts = len(res.get("alternatives") or [])
    if alts:
        sy = p.para(sx, sy - 6, f"{alts} alternative {'plan' if improve else 'team'}{'s' if alts != 1 else ''} with a "
                    "similar score were also found; open the scenario in ScoutIQ to see them.", sw, REG, 8, SOFT, 10.5)
    if res.get("notes"):
        sy -= 8
        p.text(sx, sy, "Notes", BOLD, 11, INK)
        sy -= 14
        floor = pitch_top - pitch_w * 1.5
        for n in res["notes"]:
            if sy < floor + 10:
                break
            sy = p.para(sx, sy, n, sw, REG, 7.5, SOFT, leading=9.8) - 3

    # XI table
    ty = pitch_top - pitch_w * 1.5 - 26
    p.text(M, ty, "The starting XI", BOLD, 11, INK)
    _table(p, ty - 18, players, formation, own, req.get("score") == "adjusted")
    _footer(p, generated)
    c.save()
    return buf.getvalue()


def _footer(p: _Page, generated: datetime | None) -> None:
    g = generated or datetime.now()
    when = f"{g.day} {g:%b %Y, %H:%M}"
    p.c.setStrokeColor(RULE)
    p.c.setLineWidth(0.5)
    p.c.line(M, 34, W - M, 34)
    p.text(M, 24, f"Generated by ScoutIQ on {when}. Statistics: API-Football, 2024/25 season. Market values: Transfermarkt, "
                  "up to June 2026.", REG, 6.5, FAINT)
    p.text(M, 15, "Academic project, non-commercial use. Scores are a model of past performance, not a guarantee; "
                  "market values are estimates, not asking prices.", REG, 6.5, FAINT)
