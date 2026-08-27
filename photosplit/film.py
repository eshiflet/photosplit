"""Find the frames on a strip of film, which is not the problem prints are.

Prints are separate objects on a lid, so `detect.find_photos` looks for things
that differ from their background and gets one blob per print. A strip is one
continuous ribbon: the frames touch, separated only by a rebate line a couple
of millimetres wide, and no amount of eroding blobs apart will cut it.

The tempting discriminator is texture -- a frame has a picture in it, a gap
does not -- and it is wrong. The first frame of the strip this was written
against is an almost empty sky, flatter than the gaps either side of it.

What does separate them is brightness. Unexposed film base is the thinnest
part of a negative, so scanned through the positive unit the rebate is the
brightest thing on the film, and it is the same brightness every time: 143 in
the strip measured, at every one of the four gaps. Frames are what lies
between. An empty holder slot is brighter still and has no film in it at all.
"""

from __future__ import annotations

import cv2
import numpy as np

from .detect import Photo

HOLDER_LEVEL = 40  # below this is the opaque holder rather than film
EMPTY_LEVEL = 220  # above this is a slot with no film in it
BASE_FRACTION = 0.93  # how close to the base level still counts as rebate
GAP_FLATNESS = 6.0  # a rebate line has no picture in it
# ...but how flat that is depends on the film. Six levels holds for fine colour
# film at 600 dpi and is far too strict for TMAX 400 at 2400, whose rebate
# measured 7.4 and 8.4 while its own frames ran 15 to 28. What separates them is
# not an absolute figure, it is that a gap is much flatter than the picture
# around it, so the limit is taken from the strip in hand.
GAP_FLATNESS_SHARE = 0.5
MIN_GAP_IN = 0.015
EDGE_INSET_IN = 0.06  # the very edge of the film is not picture


def find_frames(
    bgr: np.ndarray, dpi: float, min_side_in: float = 0.5
) -> tuple[list[Photo], np.ndarray]:
    """Locate every frame on a strip, plus the colour to trim against."""
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    column = _film_column(grey)
    if column is None:
        return [], np.array([0.0, 0.0, 0.0])
    x, y, w, h = column

    inset = max(1, int(EDGE_INSET_IN * dpi))
    strip = grey[y : y + h, x + inset : x + w - inset].astype(np.float32)
    if strip.size == 0:
        return [], np.array([0.0, 0.0, 0.0])

    smooth = max(3, int(0.01 * dpi) | 1)
    mean = cv2.blur(strip.mean(axis=1).reshape(-1, 1), (1, smooth)).ravel()
    spread = cv2.blur(strip.std(axis=1).reshape(-1, 1), (1, smooth)).ravel()

    frames = []
    for top, bottom in _frame_runs(mean, spread, dpi):
        height, width = bottom - top, w
        if min(height, width) < min_side_in * dpi:
            continue
        centre = (x + width / 2.0, y + top + height / 2.0)
        frames.append(Photo(centre, (float(width), float(height)), 0.0, 1.0))

    # The holder is what a frame is cut out of, so it is what trimming should
    # measure against, not the lid colour a print would use.
    holder = bgr[grey < HOLDER_LEVEL]
    background = holder.mean(axis=0) if holder.size else np.array([0.0, 0.0, 0.0])
    return frames, background


def measure_base(bgr: np.ndarray, dpi: float) -> np.ndarray | None:
    """The unexposed film base, read off the rebate between the frames.

    This is the reference an inversion needs, and it cannot be a constant:
    every stock has its own mask, age shifts it, and processing shifts it
    again. Measuring it from the strip in hand means a roll developed badly
    thirty years ago still calibrates itself.
    """
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    column = _film_column(grey)
    if column is None:
        return None
    x, y, w, h = column
    inset = max(1, int(EDGE_INSET_IN * dpi))
    strip = bgr[y : y + h, x + inset : x + w - inset]
    grey_strip = grey[y : y + h, x + inset : x + w - inset].astype(np.float32)
    if grey_strip.size == 0:
        return None

    smooth = max(3, int(0.01 * dpi) | 1)
    mean = cv2.blur(grey_strip.mean(axis=1).reshape(-1, 1), (1, smooth)).ravel()
    spread = cv2.blur(grey_strip.std(axis=1).reshape(-1, 1), (1, smooth)).ravel()

    film = mean < EMPTY_LEVEL
    if not film.any():
        return None
    base_level = float(np.percentile(mean[film], 97))
    rebate = film & (mean > base_level * BASE_FRACTION) & (spread < _flatness(spread, film))
    if rebate.sum() < max(4, int(0.01 * dpi)):
        return None
    return strip[rebate].reshape(-1, 3).mean(axis=0)


def _film_column(grey: np.ndarray) -> tuple[int, int, int, int] | None:
    """The lit ribbon of film inside the opaque holder."""
    lit = (grey > HOLDER_LEVEL).astype(np.uint8)
    lit = cv2.morphologyEx(lit, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(lit, 8)
    if count < 2:
        return None
    largest = max(range(1, count), key=lambda i: stats[i, cv2.CC_STAT_AREA])
    x, y, w, h, _ = stats[largest]
    return int(x), int(y), int(w), int(h)


def _frame_runs(mean: np.ndarray, spread: np.ndarray, dpi: float) -> list[tuple[int, int]]:
    """Split the strip at its rebate lines, dropping any slot without film."""
    film = mean < EMPTY_LEVEL
    if not film.any():
        return []
    base = float(np.percentile(mean[film], 97))

    rebate = film & (mean > base * BASE_FRACTION) & (spread < _flatness(spread, film))
    # A stretch of holder with no film in it separates frames every bit as
    # well as a rebate line, and a strip does not always end with one: the
    # film simply stops. Without this the last frame runs on into the slot.
    separator = rebate | ~film
    gaps = [
        (start, end)
        for start, end in _runs(separator)
        if (end - start) >= MIN_GAP_IN * dpi
    ]

    # A frame is what lies between two gaps, or between a gap and the end of
    # the film. Taking the far side of each gap rather than its middle keeps
    # the rebate out of the picture.
    edges: list[tuple[int, int]] = []
    previous = 0
    for start, end in gaps:
        edges.append((previous, start))
        previous = end
    edges.append((previous, len(mean)))

    runs = []
    for top, bottom in edges:
        if bottom <= top:
            continue
        if mean[top:bottom].mean() > EMPTY_LEVEL:
            continue  # a slot with no film in it
        runs.append((top, bottom))
    return runs


def _flatness(spread: np.ndarray, film: np.ndarray) -> float:
    """How flat a row must be to count as a gap rather than as picture.

    Relative to this strip's own texture, with an absolute floor so a strip of
    near-empty frames cannot tighten it into finding nothing at all.
    """
    texture = spread[film]
    if texture.size == 0:
        return GAP_FLATNESS
    return max(GAP_FLATNESS, float(np.median(texture)) * GAP_FLATNESS_SHARE)


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """Start and end of every stretch where the flag is true."""
    edges = np.diff(flags.astype(np.int8))
    starts = list(np.where(edges == 1)[0] + 1)
    ends = list(np.where(edges == -1)[0] + 1)
    if flags.size and flags[0]:
        starts.insert(0, 0)
    if flags.size and flags[-1]:
        ends.append(len(flags))
    return list(zip(starts, ends))
