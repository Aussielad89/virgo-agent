"""
Generate Virgo brand assets:
  - logo.ico        multi-resolution Windows app icon (16..256)
  - logo_icon.png   512x512 square mark (transparent corners, dark badge)
  - logo_icon.svg   square mark (vector, transparent)

The constellation geometry is reused from logo.svg so the mark stays
consistent across every surface.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

# ── Virgo constellation (matches logo.svg, 0..400 space) ──────────────
NODES = {
    "n1": (80, 80),
    "n2": (140, 120),
    "n3": (200, 100),
    "spica": (260, 140),   # brightest star
    "n5": (310, 180),
    "n6": (340, 260),
    "n7": (230, 210),
    "n8": (250, 290),
    "n9": (170, 250),
    "n10": (120, 300),
    "n11": (160, 180),
}
LINES = [
    ("n1", "n2"), ("n2", "n3"), ("n3", "spica"), ("spica", "n5"),
    ("n5", "n6"), ("spica", "n7"), ("n7", "n8"), ("n7", "n9"),
    ("n9", "n10"), ("n3", "n11"), ("n2", "n9"), ("n5", "n8"),
]
SPICA = "spica"
WHITE_NODES = {"n1", "n3", "spica", "n6", "n8", "n10"}

BG = (18, 18, 22, 255)
CYAN = (0, 217, 255, 255)
WHITE = (255, 255, 255, 255)


def _transform(coord, scale, cx, cy, size):
    x, y = coord
    return (x - cx) * scale + size / 2, (y - cy) * scale + size / 2


def draw_mark(size: int) -> Image.Image:
    """Draw the square Virgo mark at the given pixel size."""
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img, "RGBA")

    cx = (80 + 340) / 2
    cy = (80 + 300) / 2
    scale = (size * 0.66) / 260.0

    pts = {k: _transform(v, scale, cx, cy, size) for k, v in NODES.items()}

    # connection lines (glow pass + crisp pass)
    for glow_w, glow_a in ((max(3, size / 90), 55),):
        for a, b in LINES:
            d.line([pts[a], pts[b]], fill=(0, 217, 255, glow_a), width=int(glow_w))
    for a, b in LINES:
        d.line([pts[a], pts[b]], fill=CYAN, width=max(1, int(size / 320)))

    # node glow halos
    for k, (x, y) in pts.items():
        big = (size / 12) if k == SPICA else (size / 22)
        for r, a in ((big, 60), (big * 0.6, 90)):
            d.ellipse([x - r, y - r, x + r, y + r], fill=(0, 217, 255, a) if k not in WHITE_NODES else (255, 255, 255, a))

    # node cores
    for k, (x, y) in pts.items():
        r = (size / 34) if k == SPICA else (size / 60)
        core = WHITE if k in WHITE_NODES else CYAN
        d.ellipse([x - r, y - r, x + r, y + r], fill=core)
        if k == SPICA:
            r2 = size / 110
            d.ellipse([x - r2, y - r2, x + r2, y + r2], fill=CYAN)

    # rounded inner border accent
    m = size * 0.06
    d.rounded_rectangle(
        [m, m, size - m, size - m],
        radius=size * 0.12,
        outline=(0, 217, 255, 70),
        width=max(1, int(size / 256)),
    )
    return img


def main() -> None:
    import os

    here = os.path.dirname(os.path.abspath(__file__))

    # 512 master for png
    master = draw_mark(512)
    master.save(os.path.join(here, "logo_icon.png"))

    # multi-resolution ico — Pillow downscales the largest frame per `sizes`
    ico_path = os.path.join(here, "logo.ico")
    draw_mark(256).convert("RGBA").save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("wrote", ico_path, "and logo_icon.png")


if __name__ == "__main__":
    main()
