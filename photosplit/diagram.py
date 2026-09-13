"""Draw the bed, so "photo 3" means something to whoever is standing there.

A message naming photo 3 is no use without a way to tell which one that is.
This draws the bed as a rectangle with a numbered box where each photograph
was, seen the way the person at the scanner sees it: looking down at the glass.

That view is not the scan. A print goes on the glass face down, so the scanner
images it from underneath and the picture comes back mirrored left to right
against the view from above. The numbering has to be flipped with it or it
sends someone to the wrong side of the bed.
"""

from __future__ import annotations

import cv2
import numpy as np

# Drawn near the size it is shown at. A big canvas squeezed into a small view
# throws away exactly the detail that matters here, which is the numbers.
WIDE = 300
PAPER = (252, 252, 252)
INK = (60, 60, 60)
BOX = (210, 228, 245)
WARN = (70, 70, 220)
LIP = (150, 190, 150)


def bed_map(
    photos,
    shape: tuple[int, int],
    dpi: float,
    lips: tuple[str, ...] = ("top", "right"),
    mirrored: bool = True,
) -> np.ndarray:
    """A plan of the bed with each photograph numbered where it lies."""
    height, width = shape[:2]
    if not width or not height:
        return np.full((10, 10, 3), PAPER, np.uint8)

    scale = WIDE / width
    pad = 14
    canvas = np.full(
        (int(height * scale) + pad * 2, int(width * scale) + pad * 2, 3), PAPER, np.uint8
    )
    x0, y0 = pad, pad
    x1, y1 = canvas.shape[1] - pad, canvas.shape[0] - pad
    cv2.rectangle(canvas, (x0, y0), (x1, y1), INK, 2)

    # Mark the lips, which is what makes the drawing orientable at a glance:
    # they are the edges the person can feel on the actual scanner.
    for edge in lips:
        a, b = {
            "top": ((x0, y0), (x1, y0)),
            "bottom": ((x0, y1), (x1, y1)),
            "left": ((x0, y0), (x0, y1)),
            "right": ((x1, y0), (x1, y1)),
        }[edge]
        cv2.line(canvas, a, b, LIP, 6)

    for index, photo in enumerate(photos, start=1):
        (cx, cy), (w, h), angle = photo.center, photo.size, photo.angle
        if mirrored:
            cx = width - cx
            angle = -angle
        box = cv2.boxPoints(((cx * scale + x0, cy * scale + y0), (w * scale, h * scale), angle))
        corners = box.astype(np.int32)
        cv2.fillPoly(canvas, [corners], BOX)
        cv2.polylines(canvas, [corners], True, INK, 2)

        # Sized to the box it sits in rather than fixed, so the number is
        # readable whatever the photograph's size or the scale of the drawing.
        label = str(index)
        room = min(abs(w), abs(h)) * scale
        font = max(0.7, min(room / 42.0, 2.2))
        weight = max(2, int(round(font * 1.6)))
        size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font, weight)
        origin = (int(cx * scale + x0 - size[0] / 2), int(cy * scale + y0 + size[1] / 2))
        # A pale halo, so a number stays legible over a dark box or an edge.
        cv2.putText(canvas, label, origin, cv2.FONT_HERSHEY_SIMPLEX, font,
                    PAPER, weight + 3, cv2.LINE_AA)
        cv2.putText(canvas, label, origin, cv2.FONT_HERSHEY_SIMPLEX, font,
                    INK, weight, cv2.LINE_AA)

    # No caption. At the size this is shown it would be three pixels tall,
    # which is not writing, it is texture. The view carries a tooltip instead.
    return canvas


def _flip_edge(edge: str) -> str:
    return {"left": "right", "right": "left"}.get(edge, edge)
