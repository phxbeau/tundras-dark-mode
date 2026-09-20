#!/usr/bin/env python3
"""Regenerate the extension icons (16, 32, 48, 96 and 128 px).

The mark is a crescent moon with a chrome-style diagonal gradient on a black
rounded square, with a soft navy glow (#176093, the accent used for the
selected tab and hover states in dark.css) behind it. It borrows only the
colours and the metallic look of tundras.com's own logo. It does not reproduce
the site's wordmark or the Toyota emblem, both of which are trademarks.

Run from the repo root:

    python3 tools/make_icons.py                  # writes tundras-dark-mode/icons/
    python3 tools/make_icons.py --out some/dir   # write somewhere else

Needs Pillow. This is not part of the extension build (build.py never calls
it); the PNGs it writes are committed.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZES = (16, 32, 48, 96, 128)

GLOW_COLOR = (23, 96, 147)  # #176093

# Diagonal chrome gradient, top-left to bottom-right, sampled from the
# highlights and cool blue-grey mid-tones of the site's logo.
CHROME = [
    (0.00, (255, 255, 255)),
    (0.35, (214, 218, 222)),
    (0.55, (140, 145, 151)),
    (0.75, (75, 79, 84)),
    (1.00, (27, 29, 30)),
]

# The small sizes are the toolbar icons, and there the near-black tail of the
# chrome gradient disappears into the background. Lift the shadow end so the
# whole crescent stays readable, and draw the moon a little larger.
CHROME_LIFTED = [
    (0.00, (255, 255, 255)),
    (0.45, (228, 231, 235)),
    (0.75, (176, 181, 188)),
    (1.00, (118, 124, 132)),
]

# size -> render() overrides. 96 and 128 use the defaults.
TUNING = {
    16: dict(moon_scale=0.76, chrome=CHROME_LIFTED),
    32: dict(moon_scale=0.70, chrome=CHROME_LIFTED),
    48: dict(moon_scale=0.66, chrome=CHROME_LIFTED),
}


def rounded_square_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def diagonal_gradient(size, stops):
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    diag = size * math.sqrt(2)
    for y in range(size):
        for x in range(size):
            t = max(0.0, min(1.0, (x + y) / diag))
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if p0 <= t <= p1:
                    f = (t - p0) / (p1 - p0) if p1 > p0 else 0
                    px[x, y] = tuple(int(c0[i] + (c1[i] - c0[i]) * f) for i in range(3))
                    break
    return grad


def radial_glow(size, center, radius, color, power):
    """Color at the center fading to transparent at `radius`."""
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = glow.load()
    cx, cy = center
    for y in range(max(0, cy - radius), min(size, cy + radius)):
        for x in range(max(0, cx - radius), min(size, cx + radius)):
            dist = math.hypot(x - cx, y - cy)
            if dist < radius:
                px[x, y] = (*color, int(255 * (1 - dist / radius) ** power))
    return glow


def render(size, moon_scale=0.62, chrome=CHROME, glow_radius=2.15, glow_power=1.6):
    """Draw the icon at `size` px, supersampled so the small sizes stay smooth."""
    ss = 4 if size >= 128 else max(4, round(512 / size))
    big = size * ss
    corner = 24 / 128 * size * ss

    bg_mask = rounded_square_mask(big, corner)
    base = Image.new("RGBA", (big, big), (0, 0, 0, 255))
    base.putalpha(bg_mask)

    moon_r = int(big * moon_scale) // 2
    cx, cy = big // 2 - int(big * 0.02), big // 2

    # Navy glow behind the moon, clipped to the rounded square.
    glow = radial_glow(big, (cx, cy), int(moon_r * glow_radius), GLOW_COLOR, glow_power)
    glow.putalpha(ImageChops.multiply(glow.getchannel("A"), bg_mask))
    base = Image.alpha_composite(base, glow)

    # Crescent: a disc with a second, offset disc bitten out of it.
    disc = Image.new("L", (big, big), 0)
    ImageDraw.Draw(disc).ellipse([cx - moon_r, cy - moon_r, cx + moon_r, cy + moon_r], fill=255)
    bx, by = cx + int(moon_r * 0.62), cy - int(moon_r * 0.30)
    bite = Image.new("L", (big, big), 0)
    ImageDraw.Draw(bite).ellipse([bx - moon_r, by - moon_r, bx + moon_r, by + moon_r], fill=255)
    crescent_mask = ImageChops.subtract(disc, bite)

    crescent = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    crescent.paste(diagonal_gradient(big, chrome), (0, 0), crescent_mask)

    # Thin bright rim along the outer edge for a metallic edge highlight.
    eroded = crescent_mask.filter(ImageFilter.MinFilter(int(big * 0.02) // 2 * 2 + 1))
    rim_mask = ImageChops.subtract(crescent_mask, eroded)
    crescent.paste(Image.new("RGBA", (big, big), (255, 255, 255, 180)), (0, 0), rim_mask)

    return Image.alpha_composite(base, crescent).resize((size, size), Image.LANCZOS)


def main():
    root = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description="Regenerate the extension icons.")
    ap.add_argument("--out", type=Path, default=root / "tundras-dark-mode" / "icons")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        dest = args.out / f"icon-{size}.png"
        render(size, **TUNING.get(size, {})).save(dest)
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
