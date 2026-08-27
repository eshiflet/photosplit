"""Turn a scanned negative into a positive, using the film's own base as reference.

The scan is what the film actually holds: dense where the scene was bright,
thin where it was dark, and orange all over from the mask in the base. Making
a picture of it needs the mask divided out and the whole thing turned over.

The reference for the mask is not a constant. Every stock has its own, it
shifts as film ages, and home processing shifts it again -- so it is measured
from the strip being scanned, off the unexposed rebate between the frames,
the same way `neutralise` measures a lid and the dust map measures a bed. A
thirty-year-old roll developed in someone's kitchen calibrates itself.

Density, not brightness, is what gets inverted. Film records the logarithm of
exposure, so the distance of each pixel from the base in log space is what the
scene did, and a display gamma at the end turns that back into something to
look at. Inverting the raw values instead gives a flat, dark picture.
"""

from __future__ import annotations

import numpy as np

DISPLAY_GAMMA = 2.2
BLACK_PERCENTILE = 0.5
WHITE_PERCENTILE = 99.5


def invert(
    bgr: np.ndarray,
    base: np.ndarray,
    gamma: float = DISPLAY_GAMMA,
) -> np.ndarray:
    """A positive image from a scanned negative and its measured film base."""
    if bgr.size == 0:
        return bgr
    ceiling = 65535.0 if bgr.dtype == np.uint16 else 255.0
    reference = np.asarray(base, dtype=np.float32).reshape(1, 1, 3)
    if reference.min() <= 0:
        return bgr  # no usable reference; leave the pixels alone

    work = bgr.astype(np.float32)
    np.maximum(work, 1.0, out=work)

    # How far below the base each pixel sits, in log space: nothing at the
    # base, more the more light reached the film there.
    density = np.log10(reference / work)
    np.clip(density, 0.0, None, out=density)

    # Each channel separately, which is what takes the last of the mask out:
    # the three layers sit at different densities and age differently.
    for channel in range(3):
        plane = density[..., channel]
        low, high = np.percentile(plane, (BLACK_PERCENTILE, WHITE_PERCENTILE))
        np.subtract(plane, low, out=plane)
        np.divide(plane, max(high - low, 1e-6), out=plane)
    np.clip(density, 0.0, 1.0, out=density)

    np.power(density, 1.0 / gamma, out=density)
    return (density * ceiling).astype(bgr.dtype)


def estimate_base(bgr: np.ndarray) -> np.ndarray:
    """A film base guessed from the picture, when no rebate was scanned.

    Worse than measuring the real thing: it assumes something in the frame is
    near the base, which a uniformly dark scene is not. Only for a scan that
    has no rebate in it to measure.
    """
    flat = bgr.reshape(-1, 3).astype(np.float32)
    return np.percentile(flat, 99.5, axis=0)
