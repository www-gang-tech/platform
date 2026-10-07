#!/usr/bin/env python3
"""Render the HOW_IT_WORKS ascii diagram to PNG.

Text is laid out on a forced character grid; box-drawing characters are drawn
as vector line segments rather than glyphs so corners and joins are seamless.
"""
import re
from PIL import Image, ImageDraw, ImageFont

SRC = "/Users/danielhirunrusme/Documents/gang-platform/docs/architecture/HOW_IT_WORKS.md"
OUT_DIR = "/Users/danielhirunrusme/Documents/gang-platform/docs/architecture"

MENLO = "/System/Library/Fonts/Menlo.ttc"
SIZE = 22
PAD = 60
GUTTER = 10          # character cells between columns
STROKE = 2

C_BG = (255, 255, 255)
C_BOX = (171, 178, 188)
C_TEXT = (34, 37, 42)
C_TITLE = (8, 9, 11)
C_DIM = (122, 128, 137)
C_RULE = (228, 231, 235)

regular = ImageFont.truetype(MENLO, SIZE, index=0)
bold = ImageFont.truetype(MENLO, SIZE, index=1)
CW = regular.getlength("M")
CH = round(SIZE * 1.21)

# which half-segments each box char connects: (left, right, up, down)
SEGMENTS = {
    "─": (1, 1, 0, 0), "│": (0, 0, 1, 1),
    "┌": (0, 1, 0, 1), "┐": (1, 0, 0, 1),
    "└": (0, 1, 1, 0), "┘": (1, 0, 1, 0),
    "├": (0, 1, 1, 1), "┤": (1, 0, 1, 1),
    "┬": (1, 1, 0, 1), "┴": (1, 1, 1, 0),
    "┼": (1, 1, 1, 1),
}
TRIANGLES = {"▼", "▶"}

md = open(SRC, encoding="utf-8").read()
lines = re.search(r"```\n(.*?)\n```", md, re.S).group(1).split("\n")

TITLE_RE = re.compile(r"^\(\d\)")


def bold_line(line):
    s = line.strip().strip("│").strip()
    return bool(TITLE_RE.match(s)) or s.startswith(("FOR PEOPLE", "FOR MACHINES"))


def draw_grid(d, rows, ox, oy):
    for r, line in enumerate(rows):
        y = oy + r * CH
        use_bold = bold_line(line)
        for c, ch in enumerate(line):
            if ch == " ":
                continue
            x = ox + c * CW
            cx, cy = x + CW / 2, y + CH / 2

            if ch in SEGMENTS:
                left, right, up, down = SEGMENTS[ch]
                if left:
                    d.line([(x, cy), (cx, cy)], fill=C_BOX, width=STROKE)
                if right:
                    d.line([(cx, cy), (x + CW, cy)], fill=C_BOX, width=STROKE)
                if up:
                    d.line([(cx, y), (cx, cy)], fill=C_BOX, width=STROKE)
                if down:
                    d.line([(cx, cy), (cx, y + CH)], fill=C_BOX, width=STROKE)
            elif ch in TRIANGLES:
                h, w = CH * 0.30, CW * 0.46
                if ch == "▼":
                    pts = [(cx - w, cy - h), (cx + w, cy - h), (cx, cy + h)]
                else:
                    pts = [(cx - w, cy - h), (cx - w, cy + h), (cx + w, cy)]
                d.polygon(pts, fill=C_BOX)
            else:
                d.text((x, y), ch,
                       font=bold if use_bold else regular,
                       fill=C_TITLE if use_bold else C_TEXT)


def render(columns, path, caption):
    col_w = max(len(l) for col in columns for l in col)
    rows_n = max(len(col) for col in columns)
    n = len(columns)

    width = int(PAD * 2 + n * col_w * CW + (n - 1) * GUTTER * CW)
    height = int(PAD * 2 + rows_n * CH + CH * 2)

    img = Image.new("RGB", (width, height), C_BG)
    d = ImageDraw.Draw(img)

    for i, col in enumerate(columns):
        ox = PAD + i * (col_w + GUTTER) * CW
        draw_grid(d, col, ox, PAD)
        if i:
            rx = PAD + (i * (col_w + GUTTER) - GUTTER / 2) * CW
            d.line([(rx, PAD), (rx, PAD + rows_n * CH)], fill=C_RULE, width=2)

    d.text((PAD, height - PAD / 2 - CH), caption, font=regular, fill=C_DIM)
    img.save(path)
    print(f"{path}  {width}x{height}")


render([lines], f"{OUT_DIR}/how-it-works.png",
       "GANG Platform — system architecture, end to end")

arrows = [i for i, l in enumerate(lines) if l.strip() == "▼"]
split = min(arrows, key=lambda i: abs(i - len(lines) / 2))
left, right = lines[:split + 1], lines[split + 1:]
pad_to = max(len(left), len(right))
left += [""] * (pad_to - len(left))
right += [""] * (pad_to - len(right))

render([left, right], f"{OUT_DIR}/how-it-works-wide.png",
       "GANG Platform — system architecture, end to end   (left column first, then right)")
