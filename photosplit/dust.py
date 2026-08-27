"""Find dust on a scan and fill it in, without eating the photograph.

Infrared cleaning is the right way to do this and is not available: the
framework has no infrared pixel type, and on silver-based black-and-white film
the image itself is opaque to infrared, so even a scanner that offered it would
read the whole frame as one enormous defect. What is left is telling dust from
picture by how it behaves.

A threshold on its own does not: run one over a frame of this film and almost
every candidate lands on a camcorder's edges and highlights, because sharp
bright things are what a threshold finds. Dust is not merely a strong local
deviation, it is an **island in a quiet neighbourhood** — a small blob whose
surroundings are smooth. That is also where dust is worth removing, because a
speck in a sky is glaring and a speck in foliage is invisible.

So a candidate has to pass all of:

  - small, in real units rather than pixels, so the same rule holds at any
    resolution;
  - roughly blob-shaped, since a long thin run is an edge;
  - sitting in a smooth surround;
  - and standing well clear of whatever variation that surround does have.

Everything else is left alone. Missing a speck costs a speck. Removing a
catchlight, a distant bird or a freckle costs part of the photograph, and the
scan it came from is the only record.
"""

from __future__ import annotations

import cv2
import numpy as np

# Dust is a physical object, so its size is in millimetres and not in pixels.
# Both ends matter. Anything bigger than the maximum is something in the
# photograph; anything smaller than the minimum is grain, and grain is the
# trap: measured on the same film at 600 and at 2400 dpi, the blobs a pixel
# threshold finds have the same median area of 4 px at both, when a real speck
# would cover sixteen times the area at four times the sampling. Size that does
# not scale with resolution was never an object on the film.
SPECK_MAX_IN = 0.02
SPECK_MIN_IN = 0.0016  # about 40 um, below which nothing is worth removing
SPECK_MIN_PX = 3
MAX_ASPECT = 6.0  # longer than this and it is an edge, not a speck

# How quiet a neighbourhood has to be, and how far the speck must stand out of
# it, on a scale of 0-255. Three settings rather than a slider: the difference
# that matters is how much risk you will take with the picture.
STRENGTHS = {
    "light": (8.0, 8.0, 4.0),
    "normal": (6.0, 12.0, 3.0),
    "strong": (4.5, 20.0, 2.5),
}
DEFAULT_STRENGTH = "normal"


# Where dust and grain become separable. The measured floor is nearer 1100
# dpi — below it the smallest speck worth removing covers fewer pixels than the
# grain does, and what this finds in a lawn is the clover rather than dust —
# but 1200 is on the resolution menu and a little margin is no loss.
MIN_DPI = 1200


def too_coarse(dpi: float) -> bool:
    """Whether a scan has the resolution to tell dust from grain at all."""
    return dpi < MIN_DPI


def find_specks(bgr: np.ndarray, dpi: float, strength: str = DEFAULT_STRENGTH) -> np.ndarray:
    """A mask of everything that looks like dust rather than photograph."""
    sigma_mult, max_ring_std, clearance = STRENGTHS.get(strength, STRENGTHS[DEFAULT_STRENGTH])
    grey = _grey8(bgr)
    if grey.size == 0 or too_coarse(dpi):
        return np.zeros(bgr.shape[:2], np.uint8)

    span = max(3, int(round(SPECK_MAX_IN * dpi)) | 1)
    span = min(span, 31)  # medianBlur is only sensible over a small window
    smoothed = cv2.medianBlur(grey, span)
    residual = grey.astype(np.int16) - smoothed.astype(np.int16)
    noise = _noise(residual)
    if noise <= 0:
        return np.zeros(grey.shape, np.uint8)

    candidates = (np.abs(residual) > sigma_mult * noise).astype(np.uint8)
    return _keep_islands(grey, candidates, residual, dpi, max_ring_std, clearance)


def _keep_islands(
    grey: np.ndarray,
    candidates: np.ndarray,
    residual: np.ndarray,
    dpi: float,
    max_ring_std: float,
    clearance: float,
) -> np.ndarray:
    """Drop every candidate that is really part of the picture."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates, 8)
    keep = np.zeros(grey.shape, np.uint8)
    biggest = max(SPECK_MIN_PX, int((SPECK_MAX_IN * dpi) ** 2))
    smallest = int((SPECK_MIN_IN * dpi) ** 2)

    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if area < smallest or area > biggest:
            continue
        if max(w, h) > MAX_ASPECT * max(1, min(w, h)):
            continue

        pad = max(4, int(1.5 * max(w, h)))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1 = min(grey.shape[1], x + w + pad)
        y1 = min(grey.shape[0], y + h + pad)
        patch = grey[y0:y1, x0:x1].astype(np.float32)
        speck = labels[y0:y1, x0:x1] == index
        surround = patch[~speck]
        if surround.size < 12:
            continue

        ring_std = float(surround.std())
        if ring_std > max_ring_std:
            continue  # busy neighbourhood: whatever this is, it belongs here
        strength = abs(float(residual[labels == index].mean()))
        if strength < clearance * max(ring_std, 1.0):
            continue
        keep[labels == index] = 1
    return keep


def heal(bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Fill each speck from the pixels around it.

    OpenCV's inpainting is eight-bit only, and these scans are sixteen. For
    blobs this small the median of the ring around one is indistinguishable
    from anything cleverer, and it keeps the depth.
    """
    if mask is None or not mask.any():
        return bgr
    out = bgr.copy()
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        x, y, w, h, _ = stats[index]
        pad = max(3, max(w, h))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(bgr.shape[1], x + w + pad), min(bgr.shape[0], y + h + pad)
        patch = out[y0:y1, x0:x1]
        speck = labels[y0:y1, x0:x1] == index
        ring = patch[~speck]
        if ring.size == 0:
            continue
        patch[speck] = np.median(ring.reshape(-1, bgr.shape[2]), axis=0).astype(bgr.dtype)
    return out


def known_specks(
    shape: tuple[int, int], dpi: float, record: dict | None, origin=(0, 0)
) -> np.ndarray:
    """A mask of the dirt a calibration already found on the glass.

    This is the one source with no guesswork in it. Dirt on the platen sits in
    the same place on every scan, so a calibration knows exactly where it is
    and nothing in the photograph can be mistaken for it. It only covers the
    glass — dust on the film or on the print itself is not here — and it is
    wrong the moment the glass is cleaned, so a stale record is worse than
    none and the caller has to decide how old is too old.
    """
    height, width = shape[:2]
    mask = np.zeros((height, width), np.uint8)
    if not record:
        return mask
    seen = record.get("specks_seen") or []
    calibrated = float(record.get("dpi") or 0) or dpi
    scale = dpi / calibrated
    left, top = origin

    for speck in seen:
        try:
            x = float(speck["x_in"]) * dpi - left
            y = float(speck["y_in"]) * dpi - top
            area = float(speck.get("area_px", 4)) * scale * scale
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= x < width and 0 <= y < height):
            continue
        radius = max(1, int(round((area / 3.14159) ** 0.5)))
        cv2.circle(mask, (int(x), int(y)), radius, 1, -1)
    return mask


def mark(bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The picture with every speck ringed, so it can be looked at first.

    Removing a speck is not reversible in the file that gets written, and a
    false positive takes part of the photograph with it. Cheap to look before
    deciding, so make looking possible.
    """
    if bgr.ndim != 3:
        return bgr
    shown = bgr.copy()
    if mask is None or not mask.any():
        return shown
    top = 65535 if shown.dtype == np.uint16 else 255
    ring = (0, 0, top)  # BGR: red, which no scan of film is going to be short of
    thickness = max(1, int(round(min(shown.shape[:2]) / 400)))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for index in range(1, count):
        x, y, w, h, _ = stats[index]
        pad = max(4, 2 * max(w, h))
        cv2.rectangle(
            shown, (x - pad, y - pad), (x + w + pad, y + h + pad), ring, thickness
        )
    return shown


def remove(
    bgr: np.ndarray, dpi: float, strength: str = DEFAULT_STRENGTH
) -> tuple[np.ndarray, int]:
    """Take the dust off a crop, and say how many specks that was."""
    mask = find_specks(bgr, dpi, strength)
    found = cv2.connectedComponentsWithStats(mask, 8)[0] - 1 if mask.any() else 0
    return heal(bgr, mask), max(0, found)


def _noise(residual: np.ndarray) -> float:
    """The grain, measured so that the picture does not count towards it.

    A standard deviation over the residual is the obvious estimate and is
    wrong: every edge in the photograph lands in it and inflates it — measured
    at better than twice the true figure on a frame with a hard-edged subject
    in it — which quietly raises the threshold until nothing is found at all.
    The median absolute deviation ignores them.
    """
    middle = float(np.median(residual))
    return 1.4826 * float(np.median(np.abs(residual - middle)))


def _grey8(bgr: np.ndarray) -> np.ndarray:
    """Grey, in levels out of 255, whatever depth came in."""
    if bgr.ndim == 2:
        flat = bgr
    else:
        flat = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    if flat.dtype == np.uint16:
        return (flat.astype(np.uint32) >> 8).astype(np.uint8)
    return flat.astype(np.uint8)
