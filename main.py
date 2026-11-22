#!/usr/bin/env python3
"""The World in One Picture -- Sunday, 22 November 2026.

Draws one newspaper-style front page summing up the world's news of
Sunday 22 November 2026 and writes it to /output/entry.png (or to
$MAKEFUN_OUTPUT_DIR/entry.png when that is set).

Standard library only. No network, no randomness, no clock: run it
twice and the bytes are identical.

The page: the date in the masthead, then six stories from that day in a
2-by-3 grid. Each story has a drawn pictogram, a headline, one line of
reporting and the source it comes from. Every story below happened, or
was first reported, on 22 November 2026 (in some time zone), and every
claim on the page comes from the source named beside it.

Text is rendered with bitmap fonts read from font.b64 beside this file:
DejaVu Sans Bold at 40 and 28 px and DejaVu Sans at 18 px, rasterized
at authoring time into 1-bit glyphs by gen_font.py. The blob holds
three faces in order (date, head, body); each face starts with one byte
of cell height, then characters 32..126 in order, each stored as one
width byte followed by row-major bits, most significant bit first,
1 = ink.
"""

import base64
import math
import os
import struct
import zlib

_HERE = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ fonts

_DATE = 0  # DejaVu Sans Bold, 40 px -- masthead date
_HEAD = 1  # DejaVu Sans Bold, 28 px -- headlines
_BODY = 2  # DejaVu Sans, 18 px -- body, tags, sources
_TRACK = (3, 2, 1)  # extra pixels between glyphs, per face

_FONTS = None


def _fonts():
    global _FONTS
    if _FONTS is not None:
        return _FONTS
    with open(os.path.join(_HERE, "font.b64"), "rb") as handle:
        raw = zlib.decompress(base64.b64decode(handle.read()))
    if raw[:4] != b"NF22":
        raise ValueError("font.b64: bad magic")
    count = raw[4]
    pos = 5
    faces = []
    for _ in range(count):
        cell = raw[pos]
        pos += 1
        glyphs = []
        for _code in range(32, 127):
            width = raw[pos]
            pos += 1
            nbytes = (width * cell + 7) // 8
            glyphs.append((width, cell, raw[pos:pos + nbytes]))
            pos += nbytes
        faces.append(glyphs)
    _FONTS = faces
    return faces


def measure(text, face):
    """Pixel width of text in the given face."""
    glyphs = _fonts()[face]
    total = 0
    for char in text:
        code = ord(char)
        if 32 <= code <= 126:
            total += glyphs[code - 32][0] + _TRACK[face]
    return max(0, total - _TRACK[face])


def wrap(text, face, max_width):
    """Greedy word wrap; returns lines that each fit max_width."""
    lines = []
    current = ""
    for word in text.split(" "):
        trial = word if not current else current + " " + word
        if measure(trial, face) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


# -------------------------------------------------------------------- png

def _png_chunk(kind, data):
    block = struct.pack(">I", len(data)) + kind + data
    block += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return block


def write_png(path, width, height, pixels):
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        rows.extend(pixels[y * width * 3:(y + 1) * width * 3])
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = b"\x89PNG\r\n\x1a\n"
    blob += _png_chunk(b"IHDR", header)
    blob += _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    blob += _png_chunk(b"IEND", b"")
    with open(path, "wb") as handle:
        handle.write(blob)


# ----------------------------------------------------------------- canvas

PAPER = (250, 246, 238)
INK = (26, 32, 48)
CARD = (255, 253, 247)
MUTED = (110, 102, 88)
GOLD = (176, 141, 44)
CREAM = (250, 238, 210)
WHITE = (255, 255, 255)
AMBER = (245, 158, 11)
PALE = (253, 230, 138)


class Canvas:
    """A plain RGB pixel buffer with small drawing helpers."""

    def __init__(self, width, height, background):
        self.w = width
        self.h = height
        self.px = bytearray(width * height * 3)
        self.rect(0, 0, width, height, background)

    def dot(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i], self.px[i + 1], self.px[i + 2] = color

    def rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(color) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + (x1 - x0) * 3] = row

    def border(self, x, y, w, h, color, thick=1):
        self.rect(x, y, w, thick, color)
        self.rect(x, y + h - thick, w, thick, color)
        self.rect(x, y, thick, h, color)
        self.rect(x + w - thick, y, thick, h, color)

    def hline(self, x0, x1, y, color, thick=1):
        self.rect(x0, y, x1 - x0, thick, color)

    def vline(self, x, y0, y1, color, thick=1):
        self.rect(x, y0, thick, y1 - y0, color)

    def line(self, x0, y0, x1, y1, color, thick=1):
        # Bresenham, thick pixels wide.
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        half = thick // 2
        while True:
            for a in range(-half, half + 1):
                for b in range(-half, half + 1):
                    self.dot(x0 + a, y0 + b, color)
            if x0 == x1 and y0 == y1:
                break
            step = 2 * err
            if step >= dy:
                err += dy
                x0 += sx
            if step <= dx:
                err += dx
                y0 += sy

    def disc(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                    self.dot(xx, yy, color)

    def ring(self, cx, cy, r, color, thick=2):
        for yy in range(cy - r - 1, cy + r + 2):
            for xx in range(cx - r - 1, cx + r + 2):
                d2 = (xx - cx) ** 2 + (yy - cy) ** 2
                if (r - thick) ** 2 <= d2 <= r * r:
                    self.dot(xx, yy, color)

    def fill_poly(self, points, color):
        # Scanline fill for a simple polygon.
        ys = [p[1] for p in points]
        top = max(0, min(ys))
        bottom = min(self.h, max(ys) + 1)
        for y in range(top, bottom):
            nodes = []
            n = len(points)
            for k in range(n):
                x0, y0 = points[k]
                x1, y1 = points[(k + 1) % n]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    nodes.append(int(x0 + (y - y0) * (x1 - x0) / (y1 - y0)))
            nodes.sort()
            for k in range(0, len(nodes) - 1, 2):
                for x in range(nodes[k], nodes[k + 1] + 1):
                    self.dot(x, y, color)

    def starburst(self, cx, cy, r, color, rays=8, thick=3):
        for k in range(rays):
            ang = k * 2 * math.pi / rays
            self.line(cx, cy,
                      cx + int(r * math.cos(ang)),
                      cy + int(r * math.sin(ang)), color, thick)
        self.disc(cx, cy, max(3, r // 4), color)

    def glyph(self, x, y, glyph, color):
        width, height, bits = glyph
        for yy in range(height):
            for xx in range(width):
                bit = (bits[(yy * width + xx) // 8] >>
                       (7 - (yy * width + xx) % 8)) & 1
                if bit:
                    self.dot(x + xx, y + yy, color)

    def text(self, x, y, s, face, color):
        glyphs = _fonts()[face]
        cx = x
        for char in s:
            code = ord(char)
            if 32 <= code <= 126:
                g = glyphs[code - 32]
                self.glyph(cx, y, g, color)
                cx += g[0] + _TRACK[face]
        return cx - x

    def text_centered(self, cx, y, s, face, color):
        return self.text(cx - measure(s, face) // 2, y, s, face, color)


# ------------------------------------------------------------- pictograms

def pic_gulf(c, x, y, w, h):
    # Refinery at night: chimneys, tanks, a flame burst, interceptor arcs.
    base = y + h - 12
    # Two flat-top storage tanks, light grey with a pale cap and highlight.
    for tx in (x + 26, x + 64):
        c.rect(tx, base - 40, 34, 40, (148, 163, 184))
        c.rect(tx - 2, base - 44, 38, 4, (226, 232, 240))
        c.vline(tx + 8, base - 38, base - 4, (226, 232, 240), 2)
    for kx, kh in ((x + 118, 58), (x + 142, 74), (x + 166, 48)):
        c.rect(kx, base - kh, 14, kh, (30, 41, 59))
        c.rect(kx - 2, base - kh - 4, 18, 4, (30, 41, 59))
    c.starburst(x + 149, base - 84, 17, AMBER, rays=8, thick=3)
    for ax, ay, bx, by in ((x + 210, y + 88, x + 262, y + 30),
                           (x + 228, y + 92, x + 282, y + 44)):
        c.line(ax, ay, bx, by, PALE, 2)
        c.disc(bx, by, 4, PALE)
    for sx, sy in ((x + 240, y + 22), (x + 205, y + 18)):
        c.disc(sx, sy, 3, (200, 200, 200))


def pic_cop(c, x, y, w, h):
    # A globe with meridians, a green leaf riding over it, and a small sun.
    cx, cy = x + w // 2 - 18, y + h // 2 + 6
    r = 44
    c.disc(cx, cy, r, (125, 211, 252))
    c.ring(cx, cy, r, WHITE, 3)
    c.ring(cx, cy, r - 14, WHITE, 2)
    c.line(cx - r, cy, cx + r, cy, WHITE, 2)
    c.line(cx, cy - r, cx, cy + r, WHITE, 2)
    for k in (-1, 1):
        c.line(cx + k * 24, cy - 36, cx + k * 24, cy + 36, WHITE, 2)
    # Leaf: two arcs meeting at a stalk.
    lx, ly = cx + 44, cy - 34
    c.fill_poly([(lx, ly), (lx + 34, ly - 22), (lx + 44, ly + 6),
                 (lx + 12, ly + 14)], (34, 139, 60))
    c.line(lx, ly + 12, lx + 40, ly - 8, (22, 101, 52), 2)
    c.disc(x + w - 34, y + 26, 9, AMBER)
    c.starburst(x + w - 34, y + 26, 15, AMBER, rays=6, thick=2)


def pic_quake(c, x, y, w, h):
    # Mountain ridge, a zigzag crack through the ground, seismograph line.
    base = y + h - 14
    c.fill_poly([(x + 8, base), (x + 70, y + 26), (x + 118, base - 22),
                 (x + 168, y + 40), (x + 226, y + 18), (x + 292, base)],
                (196, 172, 138))
    c.disc(x + 66, y + 22, 5, WHITE)
    c.disc(x + 222, y + 14, 5, WHITE)
    crack = [(x + 20, base - 4), (x + 60, base + 2), (x + 96, base - 8),
             (x + 140, base + 4), (x + 186, base - 6), (x + 236, base + 2),
             (x + 288, base - 4)]
    for a, b in zip(crack, crack[1:]):
        c.line(a[0], a[1], b[0], b[1], INK, 4)
    # Magnitude badge, top right, clear of the tag chip at top left.
    c.rect(x + w - 78, y + 10, 68, 28, (30, 41, 59))
    c.text(x + w - 66, y + 15, "M 6.7", _BODY, WHITE)


def pic_storm(c, x, y, w, h):
    # A black storm cloud, a funnel reaching the ground, rain slashes.
    cx = x + w // 2
    c.disc(cx - 52, y + 34, 22, (30, 41, 59))
    c.disc(cx - 18, y + 26, 28, (30, 41, 59))
    c.disc(cx + 22, y + 34, 22, (30, 41, 59))
    c.rect(cx - 74, y + 34, 148, 18, (30, 41, 59))
    top = 66
    steps = 5
    for k in range(steps):
        w_top = 64 - k * 10
        yy = y + top + k * 9
        c.rect(cx - w_top // 2, yy, w_top, 9, (226, 232, 240))
    c.rect(cx - 52, y + h - 14, 104, 6, (226, 232, 240))
    for sx in (x + 22, x + 52, x + w - 58, x + w - 28):
        for sy in (y + 62, y + 84):
            c.line(sx, sy, sx - 7, sy + 12, (125, 211, 252), 2)


def pic_chip(c, x, y, w, h):
    # A chip with pins beside falling bars and a down arrow.
    cx, cy = x + 78, y + h // 2 + 2
    for k in range(-1, 2):
        c.rect(cx - 30, cy + k * 20 - 2, 60, 4, CREAM)
        c.rect(cx + k * 20 - 2, cy - 30, 4, 60, CREAM)
    c.rect(cx - 26, cy - 26, 52, 52, (15, 23, 42))
    c.rect(cx - 14, cy - 14, 28, 28, AMBER)
    c.text(cx - 8, cy - 9, "AI", _BODY, INK)
    base = y + h - 20
    bars = [74, 56, 38, 20]
    bx = x + 168
    for k, bh in enumerate(bars):
        c.rect(bx + k * 30, base - bh, 22, bh, CREAM)
    c.line(bx - 8, base - 84, bx + 118, base - 26, AMBER, 5)
    tip_x, tip_y = bx + 118, base - 26
    dx, dy = 126, 58
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    px, py = -uy, ux
    c.fill_poly([(tip_x, tip_y),
                 (tip_x - int(20 * ux) + int(8 * px),
                  tip_y - int(20 * uy) + int(8 * py)),
                 (tip_x - int(20 * ux) - int(8 * px),
                  tip_y - int(20 * uy) - int(8 * py))], AMBER)
    c.hline(bx - 12, bx + 126, base, CREAM, 3)


def pic_march(c, x, y, w, h):
    # A crowd: heads and shoulders, one placard held high, a megaphone.
    base = y + h - 12
    for k, hx in enumerate((x + 34, x + 78, x + 122, x + 166, x + 210)):
        c.disc(hx, base - 44, 15, (250, 238, 210) if k % 2 else CREAM)
        c.fill_poly([(hx - 22, base), (hx - 16, base - 34),
                     (hx + 16, base - 34), (hx + 22, base)],
                    (250, 238, 210) if k % 2 else CREAM)
    c.rect(x + 236, y + 18, 4, 62, (120, 84, 52))
    c.rect(x + 226, y + 8, 62, 34, WHITE)
    c.border(x + 226, y + 8, 62, 34, INK, 2)
    c.line(x + 234, y + 30, x + 280, y + 30, INK, 2)
    c.fill_poly([(x + 258, y + 66), (x + 286, y + 56), (x + 286, y + 76)],
                AMBER)
    c.rect(x + 244, y + 60, 16, 10, AMBER)


PICS = {
    "gulf": pic_gulf,
    "cop": pic_cop,
    "quake": pic_quake,
    "storm": pic_storm,
    "chip": pic_chip,
    "march": pic_march,
}

# ---------------------------------------------------------------- stories

NAVY = (31, 58, 95)
FOREST = (34, 110, 60)
UMBER = (92, 74, 52)
STEEL = (30, 64, 110)
WINE = (150, 30, 60)
INDIGO = (62, 60, 140)

STORIES = [
    dict(tag="GULF WAR", color=(139, 28, 28), pic="gulf",
         head="Iran Hits Bahrain Plant as Gulf War Widens",
         body="Bahrain says an Iranian strike set fire to an industrial site; other attacks were stopped.",
         src="SOURCE: REUTERS"),
    dict(tag="CLIMATE", color=FOREST, pic="cop",
         head="COP31 Nears Deal After Overtime",
         body="Antalya talks run past their Friday deadline; a new text goes to nearly 200 nations on Sunday.",
         src="SOURCE: REUTERS"),
    dict(tag="EARTHQUAKE", color=UMBER, pic="quake",
         head="Magnitude 6.7 Quake Shakes Peru",
         body="The tremor hits the Andes near Junin and is felt in Lima; no casualties are reported.",
         src="SOURCE: AP"),
    dict(tag="WEATHER", color=STEEL, pic="storm",
         head="Supercell Storm Flattens Brazil Town",
         body="Four dead and 162 hurt in Tupancireta; winds of 114 km/h tear roofs off 8,000 homes.",
         src="SOURCE: AFP"),
    dict(tag="BUSINESS", color=WINE, pic="chip",
         head="SEC Probes Nvidia's Accounting",
         body="Shares fall 14% on Friday as regulators scrutinise the chip giant's books amid CEO turmoil.",
         src="SOURCE: REUTERS"),
    dict(tag="FRANCE", color=INDIGO, pic="march",
         head="French Protests Enter Sixth Weekend",
         body="Turnout falls to 82,500 in cost-of-living marches, giving the government some respite.",
         src="SOURCE: REUTERS"),
]

W, H = 1024, 1024


def build():
    c = Canvas(W, H, PAPER)
    c.border(12, 12, W - 24, H - 24, INK, 3)
    # Masthead.
    c.text_centered(W // 2, 36, "THE WORLD IN ONE PICTURE", _BODY, MUTED)
    c.text_centered(W // 2, 62, "SUNDAY, 22 NOVEMBER 2026", _DATE, INK)
    c.hline(30, W - 30, 120, INK, 3)
    c.hline(30, W - 30, 126, GOLD, 1)
    # Grid: 2 rows x 3 columns.
    gx, gy = 30, 146
    cw, ch, gap = 312, 392, 14
    for idx, s in enumerate(STORIES):
        row, col = divmod(idx, 3)
        x = gx + col * (cw + gap)
        y = gy + row * (ch + gap)
        c.rect(x, y, cw, ch, CARD)
        c.border(x, y, cw, ch, (216, 205, 184), 2)
        # Pictogram band.
        band = 118
        c.rect(x + 2, y + 2, cw - 4, band, s["color"])
        PICS[s["pic"]](c, x + 2, y + 2, cw - 4, band)
        # Tag on a darker chip so the picture never crowds it.
        dark = tuple(max(0, v - 30) for v in s["color"])
        tag_w = measure(s["tag"], _BODY)
        c.rect(x + 10, y + 10, tag_w + 16, 28, dark)
        c.text(x + 18, y + 15, s["tag"], _BODY, WHITE)
        # Headline, up to 3 lines.
        ty = y + band + 16
        for line in wrap(s["head"], _HEAD, cw - 28)[:3]:
            c.text(x + 14, ty, line, _HEAD, INK)
            ty += 34
        # One line of reporting, up to 3 lines.
        ty += 8
        for line in wrap(s["body"], _BODY, cw - 28)[:3]:
            c.text(x + 14, ty, line, _BODY, (68, 64, 56))
            ty += 23
        # Source, pinned to the card's foot.
        c.text(x + 14, y + ch - 30, s["src"], _BODY, s["color"])
    # Footer.
    c.text_centered(W // 2, 958, "All events: Sunday 22 November 2026",
                    _BODY, MUTED)
    c.text_centered(W // 2, 984, "Sources: Reuters, AP, AFP",
                    _BODY, MUTED)
    return c


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    page = build()
    write_png(os.path.join(out_dir, "entry.png"), W, H, page.px)


if __name__ == "__main__":
    main()
