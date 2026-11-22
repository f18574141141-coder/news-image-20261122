#!/usr/bin/env python3
"""Draw one newspaper-style image summing up the world news of
Sunday 22 November 2026 and write it to <MAKEFUN_OUTPUT_DIR>/entry.png.

Standard library only, no network, fully deterministic: the same input
files always produce the same PNG bytes. The picture is drawn on a plain
RGB framebuffer with hand-rolled primitives (rectangles, lines, circles,
scanline polygons), text comes from the bitmap font bundle in font.b64,
and the PNG file is encoded by hand with zlib.
"""
import base64
import json
import math
import os
import struct
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "out")
SIZE = 1024

# ---------------------------------------------------------------- palette
PAPER = (246, 241, 229)
INK = (26, 26, 34)
MUTED = (96, 88, 76)
CARD = (255, 253, 247)
CARD_LINE = (198, 188, 168)
CHIP = (26, 26, 34)
CHIP_TEXT = (255, 253, 247)

RED = (142, 31, 31)
RED_DARK = (96, 18, 18)
GREEN = (31, 107, 58)
GREEN_DARK = (18, 66, 36)
BROWN = (107, 74, 42)
TAN = (216, 186, 138)
SLATE = (44, 62, 87)
NAVY = (31, 42, 92)
PURPLE = (74, 45, 107)
SKY = (168, 208, 232)
FLAME = (245, 140, 40)
GOLD = (232, 178, 44)
WHITE = (255, 255, 255)
BLACK = (10, 10, 14)


# ------------------------------------------------------------------- font
def load_fonts():
    """Decode font.b64 into {face: {'ascent': int, 'glyphs': {cp: [...]}}}."""
    with open(os.path.join(HERE, "font.b64"), "r", encoding="ascii") as fh:
        bundle = json.loads(base64.b64decode(fh.read()))
    fonts = {}
    for name, face in bundle.items():
        glyphs = {}
        for cp, spec in face["glyphs"].items():
            adv, w, h, top, blob = spec
            raw = base64.b64decode(blob) if blob else b""
            glyphs[int(cp)] = (adv, w, h, top, raw)
        fonts[name] = {"ascent": face["ascent"], "glyphs": glyphs}
    return fonts


FONTS = load_fonts()


def text_width(text, face):
    total = 0
    for ch in text:
        spec = FONTS[face]["glyphs"].get(ord(ch))
        if spec is None:
            continue
        total += spec[0]
    return total


def wrap_text(text, face, max_width):
    """Greedy word wrap; returns a list of lines that fit max_width."""
    lines = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            trial = word if not line else line + " " + word
            if text_width(trial, face) <= max_width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
    return lines


# ------------------------------------------------------------------ canvas
class Canvas:
    """A plain RGB framebuffer with small drawing primitives."""

    def __init__(self, width, height, color):
        self.w = width
        self.h = height
        self.px = bytearray(color * (width * height))
        self.clip = None  # (x0, y0, x1, y1) or None

    def set_clip(self, x, y, w, h):
        self.clip = (x, y, x + w, y + h)

    def clear_clip(self):
        self.clip = None

    def _idx(self, x, y):
        return (y * self.w + x) * 3

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            if self.clip is not None:
                cx0, cy0, cx1, cy1 = self.clip
                if not (cx0 <= x < cx1 and cy0 <= y < cy1):
                    return
            i = self._idx(x, y)
            self.px[i], self.px[i + 1], self.px[i + 2] = color

    def rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        if self.clip is not None:
            cx0, cy0, cx1, cy1 = self.clip
            x0 = max(x0, cx0)
            y0 = max(y0, cy0)
            x1 = min(x1, cx1)
            y1 = min(y1, cy1)
        for yy in range(y0, y1):
            base = (yy * self.w + x0) * 3
            for xx in range(x0, x1):
                i = base + (xx - x0) * 3
                self.px[i], self.px[i + 1], self.px[i + 2] = color

    def hline(self, x, y, w, color):
        self.rect(x, y, w, 1, color)

    def vline(self, x, y, h, color):
        self.rect(x, y, 1, h, color)

    def frame(self, x, y, w, h, color, thick=1):
        self.rect(x, y, w, thick, color)
        self.rect(x, y + h - thick, w, thick, color)
        self.rect(x, y, thick, h, color)
        self.rect(x + w - thick, y, thick, h, color)

    def line(self, x0, y0, x1, y1, color):
        """Bresenham line, 1 px wide."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.set(x0, y0, color)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def thick_line(self, x0, y0, x1, y1, color, thick):
        r = thick // 2
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for s in range(steps + 1):
            x = x0 + (x1 - x0) * s // steps
            y = y0 + (y1 - y0) * s // steps
            self.rect(x - r, y - r, thick, thick, color)

    def disc(self, cx, cy, r, color):
        for yy in range(cy - r, cy + r + 1):
            dy = yy - cy
            half = int((r * r - dy * dy) ** 0.5) if abs(dy) <= r else -1
            if half >= 0:
                self.rect(cx - half, yy, half * 2 + 1, 1, color)

    def ring(self, cx, cy, r, color, thick=2):
        for yy in range(cy - r, cy + r + 1):
            dy = yy - cy
            if abs(dy) > r:
                continue
            half = int((r * r - dy * dy) ** 0.5)
            inner = int(((r - thick) ** 2 - dy * dy) ** 0.5) \
                if abs(dy) <= r - thick else -1
            self.rect(cx - half, yy, half - max(inner, 0) + 1, 1, color)
            self.rect(cx + max(inner, 0), yy, half - max(inner, 0) + 1, 1, color)

    def poly(self, points, color):
        """Scanline fill of a simple polygon."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        for yy in range(max(0, min(ys)), min(self.h, max(ys) + 1)):
            xs = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if (y0 <= yy < y1) or (y1 <= yy < y0):
                    xs.append(x0 + (yy - y0) * (x1 - x0) // (y1 - y0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self.rect(xs[k], yy, xs[k + 1] - xs[k] + 1, 1, color)

    # ------------------------------------------------------------- text
    def glyph(self, x, y_top, spec, color):
        adv, w, h, _top, raw = spec
        if w == 0 or h == 0:
            return
        stride = (w + 7) // 8
        for yy in range(h):
            for xx in range(w):
                byte = raw[yy * stride + xx // 8]
                if byte & (0x80 >> (xx % 8)):
                    self.set(x + xx, y_top + yy, color)

    def text(self, x, y_baseline, string, face, color):
        """Draw a single line; y_baseline is the text baseline."""
        cx = x
        for ch in string:
            spec = FONTS[face]["glyphs"].get(ord(ch))
            if spec is None:
                continue
            adv, w, h, top, _raw = spec
            self.glyph(cx, y_baseline + top, spec, color)
            cx += adv
        return cx

    def tracked(self, x, y_baseline, string, face, color, tracking):
        """Draw with extra space between letters (masthead kicker)."""
        cx = x
        for ch in string:
            spec = FONTS[face]["glyphs"].get(ord(ch))
            if spec is None:
                continue
            adv, w, h, top, _raw = spec
            self.glyph(cx, y_baseline + top, spec, color)
            cx += adv + tracking
        return cx - tracking

    def para(self, x, y_baseline, lines, face, color, leading):
        y = y_baseline
        for line in lines:
            self.text(x, y, line, face, color)
            y += leading
        return y


# -------------------------------------------------------------- pictograms
# Each scene is drawn inside the box (x, y, w, h) with flat shapes only.

def scene_gulf(c, x, y, w, h):
    """Burning industrial plant at night: tanks, flare stack, smoke."""
    c.rect(x, y, w, h, RED_DARK)
    # night sky band with a few stars
    for sx, sy in [(18, 14), (52, 26), (96, 10), (150, 22), (210, 12),
                   (260, 28), (300, 16)]:
        c.disc(x + sx % w, y + sy, 2, GOLD)
    ground = y + h - 42
    c.rect(x, ground, w, 42, (58, 12, 12))
    # storage tanks: squat cylinders with domed tops
    for tx, tw in [(22, 74), (112, 74), (208, 60)]:
        c.rect(x + tx, ground - 62, tw, 62, (168, 170, 176))
        c.rect(x + tx, ground - 62, tw, 8, (120, 122, 128))
        c.poly([(x + tx, ground - 62), (x + tx + tw // 2, ground - 78),
                (x + tx + tw, ground - 62)], (140, 142, 148))
        c.vline(x + tx + tw // 2, ground - 62, 62, (120, 122, 128))
    # flare stack with flame
    sx = x + w - 52
    c.rect(sx, ground - 118, 14, 118, (30, 30, 34))
    c.poly([(sx - 8, ground - 118), (sx + 7, ground - 158),
            (sx + 22, ground - 118)], FLAME)
    c.poly([(sx - 2, ground - 118), (sx + 7, ground - 140),
            (sx + 16, ground - 118)], GOLD)
    # fire licking from the middle tank
    fx = x + 150
    c.poly([(fx - 16, ground - 62), (fx, ground - 108),
            (fx + 16, ground - 62)], FLAME)
    c.poly([(fx - 8, ground - 62), (fx, ground - 88),
            (fx + 8, ground - 62)], GOLD)
    # smoke puffs drifting up
    for px, py, pr in [(150, 46, 16), (176, 30, 20), (206, 48, 14),
                       (250, 26, 12)]:
        c.disc(x + px, y + py, pr, (74, 66, 66))
    # sparks
    for px, py in [(120, 70), (190, 56), (232, 84), (96, 96)]:
        c.disc(x + px, y + py, 3, GOLD)


def scene_climate(c, x, y, w, h):
    """Globe over green hills, a rising sun and a sprouting leaf."""
    c.rect(x, y, w, h, GREEN)
    c.rect(x, y + h - 34, w, 34, GREEN_DARK)
    # rising sun
    sun_x, sun_y = x + w - 44, y + 36
    c.disc(sun_x, sun_y, 20, GOLD)
    for k in range(8):
        ang = k * 0.785
        c.thick_line(sun_x + int(26 * math.cos(ang)),
                     sun_y + int(26 * math.sin(ang)),
                     sun_x + int(34 * math.cos(ang)),
                     sun_y + int(34 * math.sin(ang)), GOLD, 3)
    # globe
    gx, gy, gr = x + w // 2 - 14, y + h // 2 + 4, 62
    c.disc(gx, gy, gr, SKY)
    c.ring(gx, gy, gr, WHITE, 3)
    c.ring(gx, gy, gr - 14, WHITE, 2)
    c.hline(gx - gr, gy, gr * 2, WHITE)
    c.vline(gx, gy - gr, gr * 2, WHITE)
    # land blobs on the globe
    c.disc(gx - 24, gy - 18, 14, (74, 148, 92))
    c.disc(gx + 20, gy + 16, 16, (74, 148, 92))
    c.disc(gx + 26, gy - 24, 9, (74, 148, 92))
    # sprout in the foreground
    bx, by = x + 34, y + h - 34
    c.thick_line(bx, by, bx, by - 34, (214, 232, 190), 4)
    c.poly([(bx, by - 34), (bx - 26, by - 52), (bx - 2, by - 26)],
           (120, 190, 110))
    c.poly([(bx, by - 34), (bx + 26, by - 54), (bx + 2, by - 26)],
           (150, 210, 130))


def scene_quake(c, x, y, w, h):
    """Andes ridge split by a crack, with a seismograph trace."""
    c.rect(x, y, w, h, BROWN)
    c.disc(x + w - 40, y + 26, 16, (240, 232, 210))
    # two mountain ridges
    c.poly([(x, y + h), (x + 70, y + 42), (x + 150, y + h)], TAN)
    c.poly([(x + 110, y + h), (x + 210, y + 18), (x + w, y + h)],
           (198, 168, 120))
    # snow caps
    c.poly([(x + 58, y + 58), (x + 70, y + 42), (x + 84, y + 60),
            (x + 76, y + 66), (x + 66, y + 60)], WHITE)
    c.poly([(x + 196, y + 38), (x + 210, y + 18), (x + 226, y + 40),
            (x + 216, y + 46), (x + 204, y + 40)], WHITE)
    # the crack running down the big peak
    crack = [(210, 18), (204, 48), (214, 78), (202, 108), (212, 138),
             (200, 168), (208, 198)]
    for i in range(len(crack) - 1):
        c.thick_line(x + crack[i][0], y + crack[i][1],
                     x + crack[i + 1][0], y + crack[i + 1][1], BLACK, 4)
    # seismograph strip along the bottom
    sy = y + h - 26
    c.rect(x, sy - 14, w, 28, (30, 22, 16))
    trace = [(0, 0), (30, 0), (44, -10), (58, 8), (72, -14), (86, 10),
             (100, -6), (118, 0), (150, 0), (164, -8), (178, 6),
             (196, 0), (230, 0), (244, -12), (258, 12), (272, -4),
             (290, 0), (w, 0)]
    for i in range(len(trace) - 1):
        c.thick_line(x + trace[i][0], sy + trace[i][1],
                     x + trace[i + 1][0], sy + trace[i + 1][1], GOLD, 2)


def scene_storm(c, x, y, w, h):
    """Supercell: black cloud bank, lightning, driving rain."""
    c.rect(x, y, w, h, SLATE)
    c.rect(x, y + h - 30, w, 30, (24, 34, 48))
    # cloud bank: overlapping dark discs
    for cx, cy, cr in [(40, 44, 30), (90, 30, 36), (150, 46, 32),
                       (210, 32, 34), (262, 48, 28)]:
        c.disc(x + cx, y + cy, cr, (18, 26, 40))
    c.rect(x, y + 58, w, 10, (18, 26, 40))
    # lightning bolt, scaled to the band height
    bolt = [(150, 62), (128, 108), (146, 108), (122, 168),
            (168, 104), (148, 104), (172, 62)]
    c.poly([(x + px, y + py * h // 200) for px, py in bolt], GOLD)
    # rain streaks slanting in the wind
    for rx in range(14, w, 26):
        c.thick_line(x + rx, y + h // 2, x + rx - 16,
                     y + (h * 2) // 3, SKY, 2)
        c.thick_line(x + rx + 8, y + (h * 7) // 10, x + rx - 8,
                     y + (h * 17) // 20, SKY, 2)
    # a roofline being torn off, bottom right
    c.poly([(x + w - 92, y + h - 30), (x + w - 46, y + h - 62),
            (x + w - 6, y + h - 30)], (120, 84, 60))
    c.rect(x + w - 84, y + h - 30, 72, 4, (90, 60, 44))


def scene_nvidia(c, x, y, w, h):
    """Share-price bars that climb then plunge, under a magnifier."""
    c.rect(x, y, w, h, NAVY)
    base = y + h - 34
    c.rect(x, base, w, 4, (120, 130, 170))
    # climbing bars, then the plunge (heights scaled to the band)
    bars = [26, 44, 38, 62, 58, 84, 78, 104, 30, 18]
    bw = 22
    gap = 6
    bx = x + 16
    for i, bh in enumerate(bars):
        bh = bh * (h - 46) // 104
        color = (86, 190, 120) if i < 8 else (224, 84, 84)
        c.rect(bx, base - bh, bw, bh, color)
        bx += bw + gap
    # red down arrow over the plunge
    ax = x + w - 78
    c.thick_line(ax, y + 22, ax + 26, y + 62, (224, 84, 84), 5)
    c.poly([(ax + 26, y + 62), (ax + 10, y + 48), (ax + 42, y + 48)],
           (224, 84, 84))
    # magnifier over the bars
    mx, my = x + 62, y + 44
    c.ring(mx, my, 26, WHITE, 4)
    c.thick_line(mx + 18, my + 18, mx + 36, my + 36, WHITE, 5)
    c.text(mx - 8, my + 6, "?", "head", WHITE)


def scene_france(c, x, y, w, h):
    """Street march: a crowd of heads and shoulders, placards held high."""
    c.rect(x, y, w, h, PURPLE)
    c.rect(x, y + h - 26, w, 26, (46, 26, 66))
    # placards on sticks, held above the crowd
    for px, py, pw, ph in [(24, 12, 52, 30), (120, 6, 52, 30),
                           (216, 14, 52, 30)]:
        c.thick_line(x + px + pw // 2, y + py + ph, x + px + pw // 2,
                     y + h - 26, (210, 200, 180), 3)
        c.rect(x + px, y + py, pw, ph, (240, 232, 210))
        c.hline(x + px + 8, y + py + 10, pw - 16, INK)
        c.hline(x + px + 8, y + py + 20, pw - 16, INK)
    # crowd: two rows of heads and shoulders, anchored to the band bottom
    skin = [(232, 196, 160), (198, 152, 110), (150, 108, 82),
            (240, 214, 180)]
    shirts = [(214, 84, 84), (84, 140, 214), (232, 178, 44),
              (120, 190, 110), (214, 120, 84)]
    for row, ry in enumerate([h - 68, h - 42]):
        for i in range(7):
            hx = x + 22 + i * 40 + (row * 18)
            c.disc(hx, y + ry, 12, skin[(i + row) % len(skin)])
            c.rect(hx - 15, y + ry + 12, 30, 22, shirts[(i + row) % len(shirts)])


# ----------------------------------------------------------------- stories
# (tag, headline, deck, source, scene painter, accent colour)
STORIES = [
    ("GULF WAR",
     "Iran Hits Bahrain Plant as Gulf War Widens",
     "Bahrain says an Iranian strike set fire to an industrial site; "
     "other attacks were stopped.",
     "REUTERS", scene_gulf, RED),
    ("CLIMATE",
     "COP31 Nears Deal After Overtime",
     "Antalya talks run past their Friday deadline; a new text goes to "
     "nearly 200 nations.",
     "REUTERS", scene_climate, GREEN),
    ("EARTHQUAKE",
     "Magnitude 6.7 Quake Shakes Peru",
     "The tremor hits the Andes near Junín and is felt in Lima; "
     "no casualties are reported.",
     "AP", scene_quake, BROWN),
    ("WEATHER",
     "Supercell Storm Flattens Brazil Town",
     "4 dead, 162 hurt as 162 km/h winds hit Tupanciretã.",
     "AFP", scene_storm, SLATE),
    ("BUSINESS",
     "SEC Probes Nvidia’s Accounting",
     "Shares fall 14% as regulators probe the chip maker’s books.",
     "REUTERS", scene_nvidia, NAVY),
    ("FRANCE",
     "French Protests Enter Sixth Weekend",
     "Cost-of-living marches draw 82,500; turnout falls again.",
     "REUTERS", scene_france, PURPLE),
]

LEAD, MID, BOTTOM = STORIES[0], STORIES[1:3], STORIES[3:]


# ------------------------------------------------------------------- cards
def tag_chip(c, x, y, label, accent):
    """Small dark chip with the story's section label."""
    pad = 9
    w = text_width(label, "tag") + pad * 2
    h = 24
    c.rect(x, y, w, h, CHIP)
    c.text(x + pad, y + 17, label, "tag", CHIP_TEXT)
    c.rect(x, y + h, w, 3, accent)
    return w


def source_line(c, x, y, source, accent):
    c.text(x, y, "SOURCE: " + source, "tag", accent)


def draw_lead(c, x, y, w, h, story):
    tag, headline, deck, source, scene, accent = story
    c.rect(x, y, w, h, CARD)
    c.frame(x, y, w, h, CARD_LINE, 2)
    pic_w = 330
    pic_x = x + w - pic_w - 14
    pic_y = y + 14
    pic_h = h - 28
    c.set_clip(pic_x, pic_y, pic_w, pic_h)
    scene(c, pic_x, pic_y, pic_w, pic_h)
    c.clear_clip()
    c.frame(pic_x, pic_y, pic_w, pic_h, INK, 2)
    tx = x + 18
    tag_chip(c, tx, y + 16, tag, accent)
    text_w = pic_x - tx - 18
    lines = wrap_text(headline, "lead", text_w)
    c.para(tx, y + 72, lines, "lead", INK, 41)
    deck_first = y + 72 + len(lines) * 41 + 18
    deck_lines = wrap_text(deck, "deck", text_w)
    c.para(tx, deck_first, deck_lines, "deck", MUTED, 22)
    source_line(c, tx, y + h - 18, source, accent)


def draw_card(c, x, y, w, h, story, head_lead, deck_lead, band_h):
    tag, headline, deck, source, scene, accent = story
    c.rect(x, y, w, h, CARD)
    c.frame(x, y, w, h, CARD_LINE, 2)
    c.set_clip(x + 2, y + 2, w - 4, band_h)
    scene(c, x + 2, y + 2, w - 4, band_h)
    c.clear_clip()
    c.frame(x + 2, y + 2, w - 4, band_h, INK, 1)
    tag_chip(c, x + 12, y + 12, tag, accent)
    tx = x + 14
    text_w = w - 28
    top = y + band_h + 26
    lines = wrap_text(headline, "head", text_w)
    c.para(tx, top, lines, "head", INK, head_lead)
    deck_first = top + len(lines) * head_lead + 20
    deck_lines = wrap_text(deck, "deck", text_w)
    c.para(tx, deck_first, deck_lines, "deck", MUTED, deck_lead)
    source_line(c, tx, y + h - 16, source, accent)


# ---------------------------------------------------------------- masthead
def draw_masthead(c):
    x0, x1 = 28, 996
    kicker = "THE WORLD IN ONE PICTURE"
    kw = text_width(kicker, "tag") + 3 * (len(kicker) - 1)
    c.tracked((SIZE - kw) // 2, 52, kicker, "tag", MUTED, 3)
    date = "SUNDAY, 22 NOVEMBER 2026"
    dw = text_width(date, "mast")
    c.text((SIZE - dw) // 2, 104, date, "mast", INK)
    c.rect(x0, 116, x1 - x0, 3, INK)
    c.rect(x0, 122, x1 - x0, 1, INK)


def draw_footer(c):
    line = ("All events Sunday 22 November 2026  ·  "
            "Sources: Reuters, AP, AFP")
    lw = text_width(line, "tag")
    c.text((SIZE - lw) // 2, 994, line, "tag", MUTED)


# ------------------------------------------------------------------- page
def compose():
    c = Canvas(SIZE, SIZE, PAPER)
    draw_masthead(c)
    draw_lead(c, 28, 134, 968, 236, LEAD)
    mid_y, mid_h = 382, 272
    mid_w = (968 - 24) // 2
    draw_card(c, 28, mid_y, mid_w, mid_h, MID[0],
              32, 21, 100)
    draw_card(c, 28 + mid_w + 24, mid_y, mid_w, mid_h, MID[1],
              32, 21, 100)
    bot_y, bot_h = 666, 292
    bot_w = (968 - 2 * 20) // 3
    for i, story in enumerate(BOTTOM):
        draw_card(c, 28 + i * (bot_w + 20), bot_y, bot_w, bot_h,
                  story, 31, 20, 96)
    draw_footer(c)
    return c


# --------------------------------------------------------------------- png
def chunk(kind, data):
    body = kind + data
    return (struct.pack(">I", len(data)) + body +
            struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))


def write_png(canvas, path):
    raw = bytearray()
    for yy in range(canvas.h):
        raw.append(0)  # filter: none
        start = yy * canvas.w * 3
        raw += canvas.px[start:start + canvas.w * 3]
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", canvas.w, canvas.h,
                                      8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(bytes(png))


def main():
    page = compose()
    out_path = os.path.join(OUT_DIR, "entry.png")
    write_png(page, out_path)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
