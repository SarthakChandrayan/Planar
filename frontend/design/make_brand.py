"""Turn the source artwork in this folder into small, web-ready brand assets.

    pip install pillow
    python frontend/design/make_brand.py

Writes frontend/public/brand/*.png. The sources stay here, out of public/,
so the 1.7 MB originals are never shipped to the browser.
"""
import pathlib

from PIL import Image, ImageDraw

DESIGN = pathlib.Path(__file__).resolve().parent
OUT = DESIGN.parent / "public" / "brand"
OUT.mkdir(exist_ok=True)

# ---------------------------------------------------------------- app icon
# Measured on the source: rounded square at x 193..1059, y 208..1053, corner
# radius ~172. The checkerboard around it is painted in, not transparency.
INSET = 2
box = (193 + INSET, 208 + INSET, 1060 - INSET, 1054 - INSET)
radius = 172 - INSET
src = Image.open(DESIGN / "app-icon-source.png").convert("RGB").crop(box)
w, h = src.size

# Anti-aliased rounded-corner mask: draw 4x larger, then shrink.
SS = 4
big = Image.new("L", (w * SS, h * SS), 0)
ImageDraw.Draw(big).rounded_rectangle((0, 0, w * SS - 1, h * SS - 1), radius=radius * SS, fill=255)
mask = big.resize((w, h), Image.LANCZOS)

icon = src.convert("RGBA")
icon.putalpha(mask)
master = icon.resize((512, 512), Image.LANCZOS)  # the square is 2% off square; invisible

for size in (32, 64, 192):
    master.resize((size, size), Image.LANCZOS).save(OUT / f"icon-{size}.png", optimize=True)

# iOS rounds corners itself and dislikes transparency: fill the corners with
# the square's own background colour.
corner_fill = src.getpixel((w // 2, 40))
touch = Image.new("RGBA", (512, 512), corner_fill + (255,))
touch.alpha_composite(master)
touch.convert("RGB").resize((180, 180), Image.LANCZOS).save(OUT / "apple-touch-icon.png", optimize=True)

# ---------------------------------------------------------------- wordmark
# The source already has real transparency: crop to the text, keep its alpha.
src_mark = Image.open(DESIGN / "wordmark-source.png").convert("RGBA")
alpha = src_mark.getchannel("A")
left, top, right, bottom = alpha.point(lambda v: 255 if v > 16 else 0).getbbox()
PAD = 6
crop = (max(left - PAD, 0), max(top - PAD, 0), right + PAD, bottom + PAD)
alpha = alpha.crop(crop).point(lambda v: min(255, round(v * 255 / 250)))  # text 98% -> 100%
HEIGHT = 64
width = round(alpha.width * HEIGHT / alpha.height)
word = Image.new("RGBA", alpha.size, (23, 23, 23, 255))
word.putalpha(alpha)
word.resize((width, HEIGHT), Image.LANCZOS).save(OUT / "wordmark.png", optimize=True)

for f in sorted(OUT.iterdir()):
    print(f"{f.name}: {Image.open(f).size}, {f.stat().st_size / 1024:.1f} KB")
