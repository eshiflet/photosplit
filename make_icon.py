"""Draw Photosplit's icon: a scan with one photo lifting off it."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def icon(size: int) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)

    d.rounded_rectangle([s * 0.06, s * 0.06, s * 0.94, s * 0.94], r, fill=(38, 84, 140, 255))
    # the sheet on the glass
    d.rounded_rectangle(
        [s * 0.17, s * 0.20, s * 0.66, s * 0.80], int(s * 0.04), fill=(240, 242, 245, 255)
    )
    for i, y in enumerate((0.30, 0.44, 0.58)):
        d.rounded_rectangle(
            [s * 0.23, s * y, s * 0.60, s * (y + 0.09)],
            int(s * 0.015),
            fill=(196, 205, 215, 255),
        )
    # one photo lifted clear, the thing the app produces
    d.rounded_rectangle(
        [s * 0.45, s * 0.34, s * 0.86, s * 0.68], int(s * 0.04), fill=(252, 252, 253, 255)
    )
    d.rounded_rectangle(
        [s * 0.48, s * 0.37, s * 0.83, s * 0.65], int(s * 0.02), fill=(94, 168, 214, 255)
    )
    d.polygon(
        [(s * 0.48, s * 0.65), (s * 0.62, s * 0.46), (s * 0.74, s * 0.65)],
        fill=(60, 122, 90, 255),
    )
    d.ellipse([s * 0.72, s * 0.40, s * 0.79, s * 0.47], fill=(247, 214, 120, 255))
    return img


def build(destination: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "photosplit.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            icon(base).save(iconset / f"icon_{base}x{base}.png")
            icon(base * 2).save(iconset / f"icon_{base}x{base}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(destination)], check=True
        )
    return destination


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "Photosplit.icns")
    print(f"wrote {build(out)}")
