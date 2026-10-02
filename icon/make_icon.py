"""Renders Iris.icns from scratch — no source PNG exists, and the
venv has no image library other than pyobjc (already a pywebview
dependency). Draws a 1024x1024 warm-to-cool gradient (sign-off reference:
a design mockup showing a black diamond centered on a pink/orange/yellow
to purple/blue gradient) rounded square with a black diamond, then shells
out to `iconutil` to build the multi-resolution .icns Apple requires.

Usage (run once, from this directory's parent, using the project venv):
    .venv/bin/python icon/make_icon.py
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ICONSET_DIR = os.path.join(HERE, "Iris.iconset")
ICNS_PATH = os.path.join(HERE, "Iris.icns")

# Top-left to bottom-right, matching the approved reference mockup.
GRADIENT_STOPS = [
    ("#FFE9A8", 0.0),
    ("#FF9A56", 0.3),
    ("#F0637E", 0.55),
    ("#8A5AC2", 0.8),
    ("#5B4FCF", 1.0),
]

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def _background_rect(size):
    from Foundation import NSMakeRect

    from AppKit import NSBezierPath

    # macOS app icons bake in ~9% transparent margin around the artwork (Big Sur+ HIG);
    # without it the icon reads visually larger than neighboring Dock icons that have it.
    margin = size * 0.09
    glyph_size = size - margin * 2
    corner_radius = glyph_size * 0.22
    rect = NSMakeRect(margin, margin, glyph_size, glyph_size)
    clip = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(rect, corner_radius, corner_radius)
    clip.addClip()
    return margin, glyph_size


def render_master_png(path, size=1024):
    from AppKit import NSBezierPath, NSBitmapImageRep, NSColor, NSGradient, NSImage
    from Foundation import NSMakePoint, NSMakeRect

    image = NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()

    margin, glyph_size = _background_rect(size)

    colors = [NSColor.colorWithCalibratedRed_green_blue_alpha_(*_hex_to_rgb(hex_value), 1.0) for hex_value, _ in GRADIENT_STOPS]
    locations = [location for _, location in GRADIENT_STOPS]
    gradient = NSGradient.alloc().initWithColors_atLocations_colorSpace_(colors, locations, colors[0].colorSpace())
    gradient.drawFromPoint_toPoint_options_(
        NSMakePoint(margin, size - margin), NSMakePoint(size - margin, margin), 0
    )

    cx, cy = size / 2.0, size / 2.0
    r = glyph_size * 0.16
    diamond = NSBezierPath.bezierPath()
    diamond.moveToPoint_(NSMakePoint(cx, cy + r))
    diamond.lineToPoint_(NSMakePoint(cx + r, cy))
    diamond.lineToPoint_(NSMakePoint(cx, cy - r))
    diamond.lineToPoint_(NSMakePoint(cx - r, cy))
    diamond.closePath()
    NSColor.blackColor().setFill()
    diamond.fill()

    rep = NSBitmapImageRep.alloc().initWithFocusedViewRect_(NSMakeRect(0, 0, size, size))
    image.unlockFocus()

    png_data = rep.representationUsingType_properties_(4, None)  # NSBitmapImageFileTypePNG = 4
    png_data.writeToFile_atomically_(path, True)


def build_iconset(master_png):
    if os.path.isdir(ICONSET_DIR):
        shutil.rmtree(ICONSET_DIR)
    os.makedirs(ICONSET_DIR)

    for size in SIZES:
        for scale, suffix in ((1, ""), (2, "@2x")):
            out_size = size * scale
            if out_size > 1024:
                continue
            out_name = f"icon_{size}x{size}{suffix}.png"
            out_path = os.path.join(ICONSET_DIR, out_name)
            subprocess.run(
                ["sips", "-z", str(out_size), str(out_size), master_png, "--out", out_path],
                check=True, capture_output=True,
            )


def main():
    if sys.platform != "darwin":
        raise SystemExit("Icon generation requires macOS (uses AppKit + iconutil)")

    master_png = os.path.join(HERE, "Iris-master.png")
    render_master_png(master_png)
    build_iconset(master_png)
    subprocess.run(["iconutil", "-c", "icns", ICONSET_DIR, "-o", ICNS_PATH], check=True)
    print(f"Wrote {ICNS_PATH}")


if __name__ == "__main__":
    main()
