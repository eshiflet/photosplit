"""Build synthetic flatbed scans with known photo placements, for testing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

# (inches wide, inches tall, left, top, white print border?, skew degrees)
SEPARATED = [
    (4.0, 6.0, 0.30, 0.30, False, 1.4),
    (3.5, 5.0, 4.70, 0.40, True, -2.1),
    (5.0, 3.5, 0.30, 6.80, False, 0.0),
    (2.5, 3.5, 5.60, 6.90, True, 3.2),
]
# Photos butted right up against each other, the hard case.
TOUCHING = [
    (4.0, 6.0, 0.40, 0.40, False, 0.0),
    (3.5, 5.0, 4.45, 0.40, False, 0.0),
    (5.0, 3.5, 0.40, 6.55, True, -0.8),
]


def photo_content(w: int, h: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    top, bottom = rng.integers(30, 220, 3), rng.integers(30, 220, 3)
    ramp = np.linspace(0, 1, h)[:, None, None]
    img = np.repeat((top * (1 - ramp) + bottom * ramp).astype(np.float32), w, axis=1)
    for _ in range(int(rng.integers(3, 8))):
        colour = tuple(int(v) for v in rng.integers(0, 255, 3))
        p1 = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        p2 = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        cv2.rectangle(img, p1, p2, colour, -1)
    img += rng.normal(0, 6, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def make(path: Path, layout=SEPARATED, dpi: int = 300, seed: int = 7, bg: int = 242) -> list[dict]:
    rng = np.random.default_rng(seed)
    scan = np.full((int(11.0 * dpi), int(8.5 * dpi), 3), bg, np.uint8)
    scan = np.clip(scan + rng.normal(0, 2.5, scan.shape), 0, 255).astype(np.uint8)

    truth = []
    for i, (w_in, h_in, x_in, y_in, bordered, skew) in enumerate(layout):
        w, h = int(w_in * dpi), int(h_in * dpi)
        img = photo_content(w, h, seed + i)
        if bordered:
            b = int(0.12 * dpi)
            img[:b], img[-b:], img[:, :b], img[:, -b:] = 252, 252, 252, 252

        pad = int(0.25 * dpi)
        canvas = np.full((h + 2 * pad, w + 2 * pad, 3), bg, np.uint8)
        canvas[pad : pad + h, pad : pad + w] = img
        centre = (canvas.shape[1] / 2, canvas.shape[0] / 2)
        matrix = cv2.getRotationMatrix2D(centre, skew, 1.0)
        canvas = cv2.warpAffine(
            canvas, matrix, (canvas.shape[1], canvas.shape[0]), borderValue=(bg, bg, bg)
        )

        y, x = int(y_in * dpi) - pad, int(x_in * dpi) - pad
        y, x = max(0, y), max(0, x)
        region = scan[y : y + canvas.shape[0], x : x + canvas.shape[1]]
        piece = canvas[: region.shape[0], : region.shape[1]]
        drawn = np.abs(piece.astype(int) - bg).max(2, keepdims=True) > 3
        np.copyto(region, piece, where=drawn)
        truth.append(
            {
                "w_in": w_in,
                "h_in": h_in,
                "skew": skew,
                "cx_in": (x + canvas.shape[1] / 2) / dpi,
                "cy_in": (y + canvas.shape[0] / 2) / dpi,
            }
        )

    for _ in range(40):  # dust and lint on the glass
        spot = (int(rng.integers(0, 8.5 * dpi)), int(rng.integers(0, 11.0 * dpi)))
        cv2.circle(scan, spot, int(rng.integers(1, 5)), (120, 120, 120), -1)

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), scan)
    path.with_suffix(".json").write_text(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/data/scan.png")
    layout = TOUCHING if "tight" in out.stem else SEPARATED
    print(f"wrote {out} with {len(make(out, layout))} photos")
