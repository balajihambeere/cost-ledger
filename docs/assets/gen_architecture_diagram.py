"""Generates docs/assets/architecture-diagram.svg from the icon-package SVGs
in docs/assets/icons/. Icon content is INLINED directly into the composed
SVG (not referenced via <image href>) — SVGs loaded through an <img> tag
(which is how markdown renderers, including VS Code's preview, embed them)
run in "image mode": they render as a static picture and are not permitted
to fetch further external resources, so nested <image href="other.svg">
references silently fail to load. Inlining is the fix, and it also makes
the file fully self-contained (portable to GitHub, browsers, anywhere).

Text floor: 16px minimum everywhere (accessibility) — no caption, mono
label, or legend entry below that, which is why this canvas is larger and
looser than a first draft would be.

Run: python3 gen_architecture_diagram.py
"""

import re

W, H = 1560, 1180
BG = "#ffffff"
SURFACE = "#ffffff"
SURFACE_RAISED = "#f4f4f5"
BORDER = "#d4d4d8"
TEXT = "#18181b"
MUTED = "#52525b"
MUTED_2 = "#71717a"
ACCENT = "#4338ca"
BADGE_INDIGO = "#e0e7ff"
CHIP_BG = "#e4e4e7"
GROUP_BORDER = "#a1a1aa"
MARKER_MUTED = "#71717a"
MARKER_ACCENT = "#4338ca"

MIN_SIZE = 16  # accessibility floor — never emit text smaller than this

parts = []
_icon_cache = {}


def load_icon(name):
    if name not in _icon_cache:
        with open(f"icons/{name}.svg", encoding="utf-8") as f:
            src = f.read()
        vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', src).groups()
        inner = re.search(r"<svg[^>]*>(.*)</svg>", src, re.S).group(1).strip()
        inner = re.sub(r"<title>.*?</title>\s*", "", inner, flags=re.S)
        _icon_cache[name] = (float(vb[0]), float(vb[1]), inner)
    return _icon_cache[name]


def box(x, y, w, h, fill=SURFACE, stroke=BORDER, rx=14, sw=1.5, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'
    )


def text(x, y, s, size=16, fill=TEXT, weight="600", anchor="start", family="sans", style=""):
    assert size >= MIN_SIZE, f"text {s!r} at {size}px is below the {MIN_SIZE}px accessibility floor"
    ff = (
        "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace"
        if family == "mono"
        else "-apple-system,Segoe UI,Helvetica,Arial,sans-serif"
    )
    parts.append(
        f'<text x="{x}" y="{y}" font-family="{ff}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" style="{style}">{s}</text>'
    )


def icon(name, x, y, size, badge_fill=None, pad=None):
    """Inlines the icon's own path content, scaled to fit an size x size
    box at (x, y). If badge_fill is set, draws a colored rounded-square
    behind it first (for the plain single-color 'general resource' icons);
    AWS service icons already carry their own colored background tile, so
    badge_fill is omitted for those."""
    vb_w, vb_h, inner = load_icon(name)
    if badge_fill:
        parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="10" fill="{badge_fill}"/>')
        if pad is None:
            pad = size * 0.2
        inner_size = size - pad * 2
        scale = inner_size / vb_w
        tx, ty = x + pad, y + pad
    else:
        scale = size / vb_w
        tx, ty = x, y
    parts.append(f'<g transform="translate({tx},{ty}) scale({scale})">{inner}</g>')


def arrow(x1, y1, x2, y2, color=MUTED_2, width=2.5, marker="arrow", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    parts.append(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="{width}" marker-end="url(#{marker})"{d}/>'
    )


def elbow(x1, y1, x2, y2, color=MUTED_2, width=2.5, marker="arrow"):
    midy = (y1 + y2) / 2
    parts.append(
        f'<path d="M {x1} {y1} L {x1} {midy} L {x2} {midy} L {x2} {y2}" '
        f'fill="none" stroke="{color}" stroke-width="{width}" marker-end="url(#{marker})"/>'
    )


# ---- defs ----
parts.append(
    """<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#71717a"/>
  </marker>
  <marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
    <path d="M 0 0 L 10 5 L 0 10 z" fill="#4338ca"/>
  </marker>
</defs>"""
)

# ---- background ----
parts.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="{BG}"/>')

# ---- title ----
text(48, 56, "Cost Ledger — System Architecture", size=26, weight="700")
text(48, 84, "Every AI call is forced through one shared wrapper before it ever reaches Bedrock.", size=16, fill=MUTED, weight="400")

# ================= Row 1: external callers =================
SYS_X, SYS_Y, SYS_W, SYS_H = 48, 130, 460, 170
box(SYS_X, SYS_Y, SYS_W, SYS_H)
icon("generic-application", SYS_X + 24, SYS_Y + 24, 52, badge_fill=BADGE_INDIGO)
text(SYS_X + 96, SYS_Y + 44, "6 simulated systems", size=19)
text(SYS_X + 96, SYS_Y + 72, "assistant · logistics · bridge", size=16, fill=MUTED, weight="400")
text(SYS_X + 96, SYS_Y + 96, "support · safety · monitoring", size=16, fill=MUTED, weight="400")
text(SYS_X + 24, SYS_Y + SYS_H - 22, "→ POST /v1/calls", size=16, fill=MUTED_2, weight="500", family="mono")
text(SYS_X + 24, SYS_Y + SYS_H - 2, "  (X-API-Key per system)", size=16, fill=MUTED_2, weight="500", family="mono")

DASH_X, DASH_Y, DASH_W, DASH_H = 1052, 130, 460, 170
box(DASH_X, DASH_Y, DASH_W, DASH_H)
icon("client", DASH_X + 24, DASH_Y + 24, 52, badge_fill=BADGE_INDIGO)
text(DASH_X + 96, DASH_Y + 44, "Next.js dashboard", size=19)
text(DASH_X + 96, DASH_Y + 72, "Ledger · Budget ·", size=16, fill=MUTED, weight="400")
text(DASH_X + 96, DASH_Y + 96, "Customer lookup", size=16, fill=MUTED, weight="400")
text(DASH_X + 24, DASH_Y + DASH_H - 22, "→ /v1/ledger, /v1/budget,", size=16, fill=MUTED_2, weight="500", family="mono")
text(DASH_X + 24, DASH_Y + DASH_H - 2, "  /v1/identity  (JWT bearer)", size=16, fill=MUTED_2, weight="500", family="mono")

# ================= Row 2: API service (dashed group boundary) =================
GROUP_X, GROUP_Y, GROUP_W, GROUP_H = 48, 350, 1464, 730
box(GROUP_X, GROUP_Y, GROUP_W, GROUP_H, fill="none", stroke=GROUP_BORDER, rx=20, sw=1.5, dash="7,7")
text(GROUP_X + 24, GROUP_Y - 18, "cost-ledger stack — docker compose", size=16, fill=MUTED_2, weight="600", family="mono")

API_X, API_Y, API_W, API_H = 100, 388, 940, 340
box(API_X, API_Y, API_W, API_H, fill=SURFACE_RAISED)
icon("fargate", API_X + 24, API_Y + 24, 48)
text(API_X + 88, API_Y + 42, "api service — services/api  (FastAPI)", size=19)
text(API_X + 88, API_Y + 68, "ledger_core.wrapper.call_model() — the ONLY path to Bedrock", size=16, fill=MUTED, weight="500", family="mono")

steps = [
    ("authenticated-user", "1. Resolve identity", "identity.py — local ID → canonical ID"),
    ("shield", "2. Check budget ceiling", "budget.py — atomic Redis reservation"),
    (None, "3. Call the model", "bedrock_client.py — Converse + requestMetadata  →"),
    ("logs", "4. Record to ledger", "AttributedCall — append-only, per decision_id"),
]
step_y0 = API_Y + 116
step_gap = 52
for i, (ic, title, sub) in enumerate(steps):
    sy = step_y0 + i * step_gap
    if ic:
        icon(ic, API_X + 24, sy - 22, 30, badge_fill=CHIP_BG, pad=5)
    else:
        parts.append(f'<circle cx="{API_X + 39}" cy="{sy - 7}" r="5" fill="{ACCENT}"/>')
    text(API_X + 72, sy, title, size=17, weight="600")
    text(API_X + 340, sy, sub, size=16, fill=MUTED_2, weight="400", family="mono")

text(API_X + 24, API_Y + API_H - 20, "also serves /v1/ledger, /v1/budget, /v1/identity, /v1/reconciliation for reporting and admin", size=16, fill=MUTED_2, weight="400")

# Bedrock — external AWS service, kept outside the dashed compose boundary.
BR_X, BR_Y, BR_W, BR_H = 1236, 388, 280, 220
box(BR_X, BR_Y, BR_W, BR_H)
icon("bedrock", BR_X + (BR_W - 64) / 2, BR_Y + 28, 64)
text(BR_X + BR_W / 2, BR_Y + 126, "AWS Bedrock", size=19, anchor="middle")
text(BR_X + BR_W / 2, BR_Y + 152, "BedrockClient", size=16, fill=MUTED, weight="500", anchor="middle", family="mono")
text(BR_X + BR_W / 2, BR_Y + 176, "(real | mock)", size=16, fill=MUTED_2, weight="400", anchor="middle")

# systems -> API, dashboard -> API
elbow(SYS_X + SYS_W / 2, SYS_Y + SYS_H, API_X + 170, API_Y, marker="arrow")
elbow(DASH_X + DASH_W / 2, DASH_Y + DASH_H, API_X + API_W - 170, API_Y, marker="arrow")

# API step 3 -> Bedrock, and the usage-token reply
step3_y = step_y0 + 2 * step_gap
arrow(API_X + API_W, step3_y - 8, BR_X, step3_y - 28, color=ACCENT, width=3, marker="arrow-accent")
arrow(BR_X, step3_y + 34, API_X + API_W, step3_y + 22, color=MUTED_2, width=2, marker="arrow")
text((API_X + API_W + BR_X) / 2, step3_y - 38, "call", size=16, fill=ACCENT, weight="700", anchor="middle")
text((API_X + API_W + BR_X) / 2, step3_y + 54, "usage tokens", size=16, fill=MUTED_2, weight="500", anchor="middle")

# ================= Row 3: stores =================
PG_X, PG_Y, PG_W, PG_H = 160, 800, 420, 210
box(PG_X, PG_Y, PG_W, PG_H, fill=SURFACE_RAISED)
icon("rds", PG_X + 24, PG_Y + 24, 52)
text(PG_X + 96, PG_Y + 44, "PostgreSQL", size=19)
text(PG_X + 96, PG_Y + 68, "the Ledger", size=16, fill=MUTED, weight="500")
text(PG_X + 24, PG_Y + 112, "attributed_calls · budget_events", size=16, fill=MUTED_2, family="mono", weight="400")
text(PG_X + 24, PG_Y + 136, "decision_type_configs · customer_*", size=16, fill=MUTED_2, family="mono", weight="400")
text(PG_X + 24, PG_Y + 170, "append-only, never updated", size=16, fill=MUTED_2, weight="400", style="font-style:italic")

RD_X, RD_Y, RD_W, RD_H = 700, 800, 420, 210
box(RD_X, RD_Y, RD_W, RD_H, fill=SURFACE_RAISED)
icon("elasticache", RD_X + 24, RD_Y + 24, 52)
text(RD_X + 96, RD_Y + 44, "Redis", size=19)
text(RD_X + 96, RD_Y + 68, "budget running totals", size=16, fill=MUTED, weight="500")
text(RD_X + 24, RD_Y + 112, "budget:{system}:{decision_type}", size=16, fill=MUTED_2, family="mono", weight="400")
text(RD_X + 24, RD_Y + 136, "  :{date} — INCRBYFLOAT", size=16, fill=MUTED_2, family="mono", weight="400")
text(RD_X + 24, RD_Y + 170, "atomic reserve, then true-up", size=16, fill=MUTED_2, weight="400", style="font-style:italic")

elbow(API_X + 240, API_Y + API_H, PG_X + PG_W / 2, PG_Y, marker="arrow")
text(API_X + 250, API_Y + API_H + 30, "writes", size=16, fill=MUTED_2, weight="500")
elbow(API_X + API_W - 240, API_Y + API_H, RD_X + RD_W / 2, RD_Y, marker="arrow")
text(API_X + API_W - 360, API_Y + API_H + 30, "read / incr", size=16, fill=MUTED_2, weight="500")

# ================= Row 4: reconciliation =================
REC_X, REC_Y, REC_W, REC_H = 380, 1040, 520, 200
box(REC_X, REC_Y, REC_W, REC_H, fill=SURFACE_RAISED)
icon("gear", REC_X + 24, REC_Y + 24, 48, badge_fill=CHIP_BG, pad=8)
text(REC_X + 88, REC_Y + 42, "reconciliation job", size=19)
text(REC_X + 88, REC_Y + 66, "services/reconciliation", size=16, fill=MUTED, weight="500", family="mono")
text(REC_X + 24, REC_Y + 108, "in: attributed_calls + invoice CSV", size=16, fill=MUTED_2, weight="400")
text(REC_X + 24, REC_Y + 132, "    (model / usage-type grain)", size=16, fill=MUTED_2, weight="400")
text(REC_X + 24, REC_Y + 164, "out: reconciliation_runs — estimate vs. actual, gap %", size=16, fill=MUTED_2, weight="400")

elbow(PG_X + PG_W / 2, PG_Y + PG_H, REC_X + REC_W / 2, REC_Y, marker="arrow")

# ---- legend ----
LX, LY = 1236, 800
text(LX, LY, "Legend", size=16, fill=MUTED, weight="700")
parts.append(f'<line x1="{LX}" y1="{LY+28}" x2="{LX+32}" y2="{LY+28}" stroke="{ACCENT}" stroke-width="3" marker-end="url(#arrow-accent)"/>')
text(LX + 44, LY + 34, "only path to Bedrock", size=16, fill=MUTED, weight="400")
parts.append(f'<line x1="{LX}" y1="{LY+62}" x2="{LX+32}" y2="{LY+62}" stroke="{MUTED_2}" stroke-width="2.5" marker-end="url(#arrow)"/>')
text(LX + 44, LY + 68, "data flow", size=16, fill=MUTED, weight="400")
box(LX, LY + 88, 32, 22, fill="none", stroke=GROUP_BORDER, rx=5, dash="5,5")
text(LX + 44, LY + 104, "this deployment", size=16, fill=MUTED, weight="400")
text(LX + 44, LY + 126, "(Docker Compose)", size=16, fill=MUTED, weight="400")

svg = (
    f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">\n' + "\n".join(parts) + "\n</svg>\n"
)

with open("architecture-diagram.svg", "w") as f:
    f.write(svg)

print("wrote architecture-diagram.svg,", len(svg), "bytes,", len(_icon_cache), "icons inlined")
