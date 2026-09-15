"""Cinematic background scene matching the approved JARVIS 1.3.9 reference.

This module renders only the static environment. The interactive orb, captions,
conversation history and composer remain real widgets/renderer layers.
"""
from __future__ import annotations

import math
from PIL import Image, ImageDraw, ImageFilter


def _line(draw, xy, fill, width):
    try:
        draw.line(xy, fill=fill, width=max(1, int(width)), joint="curve")
    except TypeError:
        draw.line(xy, fill=fill, width=max(1, int(width)))


def render_reference_scene(width: int, height: int) -> Image.Image:
    """Render a dark glass office/city scene without baking any controls/text."""
    width = max(1, min(3840, int(width)))
    height = max(1, min(2160, int(height)))
    scale = 0.55 if max(width, height) > 1800 else 0.72
    w, h = max(2, int(width * scale)), max(2, int(height * scale))

    image = Image.new("RGB", (w, h), (2, 8, 15))
    d = ImageDraw.Draw(image)
    horizon = int(h * 0.58)
    d.rectangle((0, 0, w, horizon), fill=(3, 14, 27))
    d.rectangle((0, horizon, w, h), fill=(4, 9, 14))

    panes = 7
    for i in range(panes + 1):
        x = int(i * w / panes)
        col = max(2, int(w * 0.006))
        d.rectangle((x - col, 0, x + col, int(h * 0.69)), fill=(5, 18, 31))
        if i < panes:
            x2 = int((i + 1) * w / panes)
            d.rectangle((x + col, int(h * 0.06), x2 - col, horizon), fill=(3, 18 + (i % 2) * 3, 35 + (i % 3) * 4))

    city_seed = 0x139
    def rnd(n):
        nonlocal city_seed
        city_seed = (1103515245 * city_seed + 12345) & 0x7fffffff
        return city_seed % max(1, n)

    base_y = int(h * 0.60)
    x = int(w * 0.02)
    while x < int(w * 0.82):
        bw = max(5, int(w * (0.018 + rnd(18) / 1000)))
        bh = int(h * (0.10 + rnd(300) / 1000))
        top = base_y - bh
        d.rectangle((x, top, x + bw, base_y), fill=(4 + rnd(8), 14 + rnd(14), 28 + rnd(22)))
        rows = max(2, bh // max(6, int(h * 0.018)))
        cols = max(1, bw // max(5, int(w * 0.008)))
        for ry in range(rows):
            for cx in range(cols):
                if rnd(100) < 39:
                    px = x + 2 + cx * max(5, bw // cols)
                    py = top + 3 + ry * max(6, bh // rows)
                    warm = rnd(100) < 35
                    color = (214, 161, 82) if warm else (34, 112, 177)
                    d.rectangle((px, py, px + 1, py + 2), fill=color)
        x += bw + max(3, int(w * 0.009))

    _line(d, [(0, int(h * 0.04)), (int(w * 0.48), int(h * 0.12)), (w, int(h * 0.02))], (26, 31, 38), h * 0.035)
    _line(d, [(int(w * 0.55), 0), (int(w * 0.82), int(h * 0.10)), (w, int(h * 0.06))], (35, 31, 28), h * 0.025)
    for off, alpha in ((0.0, (238, 174, 99)), (0.012, (114, 73, 41))):
        _line(d, [(int(w * 0.57), int(h * (0.035 + off))), (int(w * 0.83), int(h * (0.105 + off)))], alpha, max(1, h * 0.004))
        _line(d, [(int(w * 0.83), int(h * (0.105 + off))), (int(w * 0.83), int(h * 0.54))], alpha, max(1, h * 0.004))

    d.rounded_rectangle((int(w * 0.73), int(h * 0.16), int(w * 0.96), int(h * 0.59)), radius=max(4, int(w * 0.015)), fill=(5, 10, 15), outline=(31, 38, 43), width=max(1, int(w * 0.002)))
    d.ellipse((int(w * 0.79), int(h * 0.23), int(w * 0.90), int(h * 0.40)), outline=(25, 38, 49), width=max(2, int(w * 0.004)))
    _line(d, [(int(w * 0.81), int(h * 0.38)), (int(w * 0.845), int(h * 0.25)), (int(w * 0.885), int(h * 0.38))], (28, 43, 55), max(2, w * 0.005))

    desk_top = int(h * 0.68)
    d.polygon([(0, desk_top), (w, int(h * 0.62)), (w, h), (0, h)], fill=(3, 8, 13))
    for y in range(desk_top, h, max(4, int(h * 0.035))):
        fade = max(8, 25 - int((y - desk_top) / max(1, h - desk_top) * 17))
        _line(d, [(0, y), (w, int(y - (y - desk_top) * 0.16))], (5, 35 + fade, 60 + fade), 1)

    cx = w // 2
    py = int(h * 0.72)
    pw = int(w * 0.34)
    ph = max(8, int(h * 0.075))
    for mul, color, linew in ((1.22, (12, 67, 111), 2), (1.0, (22, 137, 219), 2), (0.72, (36, 193, 255), 1)):
        rx = int(pw * mul / 2); ry = int(ph * mul / 2)
        d.ellipse((cx - rx, py - ry, cx + rx, py + ry), outline=color, width=max(1, int(linew * scale)))
    d.polygon([(cx - pw // 2, py), (cx + pw // 2, py), (cx + int(pw * 0.39), py + ph), (cx - int(pw * 0.39), py + ph)], fill=(5, 13, 20), outline=(23, 68, 96))
    d.ellipse((cx - int(pw * 0.39), py + int(ph * 0.55), cx + int(pw * 0.39), py + int(ph * 1.28)), outline=(16, 119, 190), width=max(1, int(w * 0.002)))

    wave_y = int(h * 0.44)
    _line(d, [(int(w * 0.08), wave_y), (int(w * 0.92), wave_y)], (14, 75, 123), 1)
    for i in range(180):
        t = i / 179.0
        x = int(w * (0.08 + 0.84 * t))
        envelope = 1.0 - min(1.0, abs(t - 0.5) * 1.7)
        pulse = abs(math.sin(t * math.pi * 31) * math.sin(t * math.pi * 7))
        amp = int(h * 0.055 * pulse * (0.35 + 0.65 * (1.0 - envelope)))
        if 0.30 < t < 0.70: amp = int(amp * 0.28)
        color = (30, 149, 233) if i % 3 else (73, 207, 255)
        _line(d, [(x, wave_y - amp), (x, wave_y + amp)], color, max(1, w * 0.0012))

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for r, alpha in ((0.19, 60), (0.12, 80), (0.06, 105)):
        rx = int(w * r)
        gd.ellipse((cx - rx, int(h * 0.66), cx + rx, int(h * 0.93)), fill=(0, 116, 255, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(max(6, int(min(w, h) * 0.045))))
    image = Image.alpha_composite(image.convert("RGBA"), glow).convert("RGB")
    image = image.filter(ImageFilter.GaussianBlur(max(0.5, min(w, h) * 0.0022)))
    return image.resize((width, height), Image.Resampling.LANCZOS)


__all__ = ["render_reference_scene"]
