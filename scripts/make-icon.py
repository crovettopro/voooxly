"""Voooxly icon generator: the editorial quotation mark — speech made text.

Brand shared with the landing page (voooxly.com): serif opening double
quote (Iowan Old Style, the same family as the site) in paper color
on a teal squircle. Replaces the v1 waveform bars, which looked too
much like the Wispr Flow logo.

Usage:
  python scripts/make-icon.py preview   # 512 control PNG → assets/preview/
  python scripts/make-icon.py build     # .icns + menubar template → assets/
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# Brand palette (the landing page's)
TEAL_TOP = (16, 122, 105)      # top-left corner, a touch more luminous
TEAL_BOTTOM = (8, 84, 72)      # bottom-right corner
PAPER = (237, 240, 238)        # #EDF0EE

# The same serif as the site; Georgia as a safety net
FONTS = [
    ("/System/Library/Fonts/Supplemental/Iowan Old Style.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
]

GLYPH = "“"  # opening double quotation mark


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path, index in FONTS:
        try:
            return ImageFont.truetype(path, px, index=index)
        except OSError:
            continue
    raise SystemExit("No system serif available (Iowan/Georgia)")


def _gradient(size: int, c1, c2) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def _glyph_layer(S: int, color, width_ratio: float) -> Image.Image:
    """Transparent layer with the quote centered OPTICALLY.

    The “ glyph's metrics lie depending on the font (it sits glued to the
    ascender), so textbbox is not trusted for placement: draw on an
    oversized canvas, crop to the REAL ink (alpha) and paste that box
    centered on the final canvas. Immune to metric quirks.
    """
    big = S * 3
    scratch = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(scratch)
    d.text((big // 2, big // 2), GLYPH, font=_font(S), fill=(*color, 255), anchor="mm")
    box = scratch.getbbox()
    if box is None:
        raise SystemExit("The font has no ink for the “ glyph")
    ink = scratch.crop(box)
    # scale the ink to the target width preserving aspect ratio
    target_w = int(S * width_ratio)
    target_h = int(ink.height * target_w / ink.width)
    ink = ink.resize((target_w, target_h), Image.LANCZOS)
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    layer.paste(ink, ((S - target_w) // 2, (S - target_h) // 2), ink)
    return layer


def draw_icon(size: int) -> Image.Image:
    S = 1024  # drawn at 1024 and rescaled down (antialias)
    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    grad = _gradient(S, TEAL_TOP, TEAL_BOTTOM).convert("RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, S - 1, S - 1], radius=int(S * 0.2237), fill=255
    )
    icon.paste(grad, (0, 0), mask)
    icon = Image.alpha_composite(icon, _glyph_layer(S, PAPER, 0.52))
    return icon.resize((size, size), Image.LANCZOS)


def draw_menubar(scale: int) -> Image.Image:
    """Glyph template: black quote on alpha; macOS tints it by itself."""
    S = 22 * scale
    big = _glyph_layer(22 * 8, (0, 0, 0), 0.62)  # drawn big and scaled down
    return big.resize((S, S), Image.LANCZOS)


REC_RED = (226, 68, 60)


def draw_menubar_rec(scale: int) -> Image.Image:
    """Red recording dot (NOT a template: shown in color).

    4× supersampling: a small circle drawn at final size comes out jagged.
    """
    S = 22 * scale
    big = S * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(big * 0.26)
    c = big // 2
    d.ellipse([c - r, c - r, c + r, c + r], fill=(*REC_RED, 255))
    return img.resize((S, S), Image.LANCZOS)


def preview():
    out = ASSETS / "preview"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "voooxly-quote.png"
    draw_icon(512).save(path)
    print(path)


def build():
    ASSETS.mkdir(exist_ok=True)
    iconset = ASSETS / "Voooxly.iconset"
    iconset.mkdir(exist_ok=True)
    for pts in (16, 32, 128, 256, 512):
        draw_icon(pts).save(iconset / f"icon_{pts}x{pts}.png")
        draw_icon(pts * 2).save(iconset / f"icon_{pts}x{pts}@2x.png")
    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "Voooxly.icns")],
        check=True,
    )
    for scale, name in ((1, "menubar.png"), (2, "menubar@2x.png")):
        draw_menubar(scale).save(ASSETS / name)
    for scale, name in ((1, "menubar-rec.png"), (2, "menubar-rec@2x.png")):
        draw_menubar_rec(scale).save(ASSETS / name)
    print("OK: assets/Voooxly.icns + assets/menubar*.png + menubar-rec*.png")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "preview"
    if cmd == "preview":
        preview()
    else:
        build()
