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

WIDE = 520  # the drawing is a diagram, not an image; this is plenty
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
    pad = 34
    canvas = np.full(
        (int(height * scale) + pad * 2, int(width * scale) + pad * 2, 3), PAPER, np.uint8
    )
    x0, y0 = pad, pad
    x1, y1 = canvas.shape[1] - pad, canvas.shape[0] - pad
    cv2.rectangle(canvas, (x0, y0), (x1, y1), INK, 2)

    # Mark the lips, which is what makes the drawing orientable at a glance:
    # they are the edges the person can feel on the actual scanner.
    for edge in lips:
        # The lips are already named as the viewer sees them.
        shown = edge
        a, b = {
            "top": ((x0, y0), (x1, y0)),
            "bottom": ((x0, y1), (x1, y1)),
            "left": ((x0, y0), (x0, y1)),
            "right": ((x1, y0), (x1, y1)),
        }[shown]
        cv2.line(canvas, a, b, LIP, 6)

    for index, photo in enumerate(photos, start=1):
        (cx, cy), (w, h), angle = photo.center, photo.size, photo.angle
        if mirrored:
            cx = width - cx
            angle = -angle
        box = cv2.boxPoints(((cx * scale + x0, cy * scale + y0), (w * scale, h * scale), angle))
        corners = box.astype(np.int32)
        from .detect import as_seen

        risky = any(as_seen(e) not in lips for e in getattr(photo, "edges", ()))
        cv2.fillPoly(canvas, [corners], BOX)
        cv2.polylines(canvas, [corners], True, WARN if risky else INK, 2)

        label = str(index)
        size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        cv2.putText(
            canvas, label,
            (int(cx * scale + x0 - size[0] / 2), int(cy * scale + y0 + size[1] / 2)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, INK, 2, cv2.LINE_AA,
        )

    cv2.putText(
        canvas, "looking down at the glass; green edges are the lips",
        (x0, canvas.shape[0] - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, INK, 1, cv2.LINE_AA,
    )
    return canvas


def _flip_edge(edge: str) -> str:
    return {"left": "right", "right": "left"}.get(edge, edge)
