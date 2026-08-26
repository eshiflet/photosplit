"""Cut each detected photo out of the scan, straighten it, and write it out."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .detect import Photo

JPEG_QUALITY = 95


def deskew_crop(bgr: np.ndarray, photo: Photo, pad: int = 8) -> np.ndarray:
    """Return the photo as an upright image, rotated out of the scan."""
    h, w = bgr.shape[:2]
    x0, y0, x1, y1 = photo.bounds()
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(w, x1 + pad), min(h, y1 + pad)
    region = bgr[y0:y1, x0:x1]
    if region.size == 0:
        return region

    center = (photo.center[0] - x0, photo.center[1] - y0)
    if abs(photo.angle) > 0.05:
        matrix = cv2.getRotationMatrix2D(center, photo.angle, 1.0)
        region = cv2.warpAffine(
            region,
            matrix,
            (region.shape[1], region.shape[0]),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE,
        )

    size = (int(round(photo.size[0])), int(round(photo.size[1])))
    size = (min(size[0], region.shape[1]), min(size[1], region.shape[0]))
    if size[0] <= 0 or size[1] <= 0:
        return np.empty((0, 0, 3), dtype=bgr.dtype)
    return cv2.getRectSubPix(region, size, center)


def trim_background(
    crop: np.ndarray,
    background: np.ndarray,
    dpi: float,
    tolerance: int = 14,
    max_trim_in: float = 0.02,
) -> np.ndarray:
    """Shave any leftover lid-coloured sliver off the four edges.

    The detected rectangle is already accurate, so this only has rounding error
    to clean up. The limit is deliberately about a millimetre: a print with a
    white border must come out with that border intact, not silently cropped.
    """
    if crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    diff = np.abs(crop.astype(np.int16) - background.astype(np.int16)).max(axis=2)
    is_bg = diff <= tolerance

    def leading(profile: np.ndarray, limit: int) -> int:
        n = 0
        while n < limit and profile[n] > 0.9:
            n += 1
        return n

    limit = max(1, int(round(max_trim_in * dpi)))
    rows, cols = is_bg.mean(axis=1), is_bg.mean(axis=0)
    top = leading(rows, min(limit, h // 4))
    bottom = leading(rows[::-1], min(limit, h // 4))
    left = leading(cols, min(limit, w // 4))
    right = leading(cols[::-1], min(limit, w // 4))
    return crop[top : h - bottom, left : w - right]


def save(crop: np.ndarray, path: Path, dpi: float, quality: int = JPEG_QUALITY) -> None:
    """Write a crop, tagging it with the scan's resolution."""
    image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    params: dict = {"dpi": (dpi, dpi)}
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        params.update(quality=quality, subsampling=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, **params)


def preview(bgr: np.ndarray, photos: list[Photo]) -> np.ndarray:
    """A copy of the scan with every detection outlined and numbered."""
    out = bgr.copy()
    thickness = max(2, int(round(max(out.shape[:2]) / 500)))
    for index, photo in enumerate(photos, start=1):
        box = cv2.boxPoints((photo.center, photo.size, photo.angle)).astype(np.int32)
        cv2.drawContours(out, [box], -1, (0, 0, 255), thickness)
        cv2.putText(
            out,
            str(index),
            (int(photo.center[0]), int(photo.center[1])),
            cv2.FONT_HERSHEY_SIMPLEX,
            thickness,
            (0, 0, 255),
            thickness,
            cv2.LINE_AA,
        )
    return out
