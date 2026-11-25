#!/usr/bin/env python3
"""Launcher icon for the TangLisp companion: pixel-art PCB + Lisp parens.

Draws the scene on a 48x48 pixel grid, then renders it at Android's
launcher densities. The board is a deep-green PCB with copper traces,
a chip and a gold pin header; the big cream parentheses and the pink
dot in the middle are the Lisp side of the machine.

Outputs (into app/src/main/res):
  mipmap-{mdpi,hdpi,xhdpi,xxhdpi,xxxhdpi}/ic_launcher.png   (opaque)
  mipmap-xxxhdpi/ic_launcher_foreground.png                 (transparent)
  mipmap-anydpi-v26/ic_launcher.xml                         (adaptive)
"""
from PIL import Image, ImageDraw
import os

GRID = 48
RES = os.path.join(os.path.dirname(__file__), "..", "app", "src", "main", "res")

PCB      = (11, 107, 74, 255)    # board green
PCB_EDGE = (5, 59, 39, 255)      # board edge / outline
PCB_HI   = (16, 130, 90, 255)    # top highlight line
COPPER   = (217, 164, 65, 255)   # traces
GOLD     = (237, 190, 85, 255)   # pin header
VIA      = (181, 126, 34, 255)   # via dots
CHIP     = (20, 35, 27, 255)     # chip body
CHIP_HI  = (32, 56, 42, 255)     # chip top edge
CREAM    = (255, 233, 190, 255)  # parentheses
SHADOW   = (150, 96, 30, 255)    # paren drop shadow (warm brown)
PINK     = (255, 159, 178, 255)  # the dot (Yoka pink)
PINK_HI  = (255, 224, 230, 255)
ICON_BG  = (16, 26, 20, 255)     # legacy icon background

PAREN = [
    "...XX.",
    "..XXXX",
    "..XX..",
    ".XX...",
    ".XX...",
    "XX....",
    "XX....",
    "XX....",
    "XX....",
    "XX....",
    ".XX...",
    ".XX...",
    "..XX..",
    "..XXXX",
    "...XX.",
]


def scene(opaque_bg=False):
    """Return the 48x48 scene as an RGBA image (1 px per grid cell)."""
    img = Image.new("RGBA", (GRID, GRID), ICON_BG if opaque_bg else (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- the board: rounded rect (8,10)..(39,37), corner radius 3 ---
    bx0, by0, bx1, by1 = 8, 10, 39, 37
    for y in range(by0, by1 + 1):
        for x in range(bx0, bx1 + 1):
            cx = min(x - bx0, bx1 - x)
            cy = min(y - by0, by1 - y)
            if cx + cy < 2 and not (cx == 1 and cy == 1):
                continue  # rounded corner cut
            d.point((x, y), PCB_EDGE if (x in (bx0, bx1) or y in (by0, by1)) else PCB)
    for x in range(bx0 + 3, bx1 - 2):
        d.point((x, by0 + 1), PCB_HI)

    # --- the chip (top left) ---
    d.rectangle([11, 12, 17, 18], fill=CHIP)
    d.line([(11, 12), (17, 12)], fill=CHIP_HI)
    for y in (13, 15, 17):                              # pins, left and right
        d.point((10, y), GOLD)
        d.point((18, y), GOLD)

    # --- copper traces (under the parens) ---
    def trace(points):
        for x, y in points:
            d.point((x, y), COPPER)

    trace([(x, 14) for x in range(19, 24)])            # chip -> right
    d.rectangle([23, 13, 24, 14], fill=VIA)            # via at its end
    trace([(36, y) for y in range(12, 29)])            # right edge run
    d.rectangle([35, 28, 36, 29], fill=VIA)            # via at its foot
    trace([(x, 31) for x in range(13, 31)])            # bottom run

    # --- gold pin header along the bottom edge ---
    for x in range(11, 37, 3):
        d.rectangle([x, 33, x + 1, 34], fill=GOLD)

    # --- parentheses, with a warm pixel shadow ---
    def paren(ox, oy, mirror, color):
        for r, row in enumerate(PAREN):
            for c, ch in enumerate(row):
                if ch != "X":
                    continue
                x = ox + (len(row) - 1 - c if mirror else c)
                d.point((x, oy + r), color)

    paren(16, 17, False, SHADOW)
    paren(28, 17, True, SHADOW)
    paren(15, 16, False, CREAM)
    paren(27, 16, True, CREAM)

    # --- the pink dot in the middle ---
    dot = [".XX.", "XXXX", "XXXX", ".XX."]
    for r, row in enumerate(dot):
        for c, ch in enumerate(row):
            if ch == "X":
                d.point((22 + c, 21 + r), PINK)
    d.point((23, 21), PINK_HI)

    return img


def render(img, size):
    return img.resize((size, size), Image.NEAREST)


def main():
    art = scene(opaque_bg=False)
    legacy = scene(opaque_bg=True)

    densities = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for name, size in densities.items():
        out = os.path.join(RES, f"mipmap-{name}")
        os.makedirs(out, exist_ok=True)
        render(legacy, size).save(os.path.join(out, "ic_launcher.png"))

    # Adaptive foreground: keep the art inside the mask safe zone.
    fg = Image.new("RGBA", (432, 432), (0, 0, 0, 0))
    art_big = render(art, 380)
    fg.paste(art_big, (26, 26), art_big)
    fg.save(os.path.join(RES, "mipmap-xxxhdpi", "ic_launcher_foreground.png"))

    anydpi = os.path.join(RES, "mipmap-anydpi-v26")
    os.makedirs(anydpi, exist_ok=True)
    with open(os.path.join(anydpi, "ic_launcher.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n'
                '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                '    <background android:drawable="@color/icon_background" />\n'
                '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
                '</adaptive-icon>\n')
    print("icon written")


if __name__ == "__main__":
    main()
