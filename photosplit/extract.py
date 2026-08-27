"""Cut each detected photo out of the scan, straighten it, and write it out."""

from __future__ import annotations

import zlib
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .detect import Photo

JPEG_QUALITY = 95


def deskew_crop(bgr: np.ndarray, photo: Photo, pad: int = 8) -> np.ndarray:
    """Return the photo as an upright image, cut out of the scan.

    Resampling costs detail, so this does as little of it as possible: none at
    all when the print is already square to the glass, and exactly one pass
    when it is not. The obvious implementation — rotate the whole region, then
    lift the rectangle out of it — quietly resamples twice.
    """
    height, width = bgr.shape[:2]
    out_w = int(round(photo.size[0]))
    out_h = int(round(photo.size[1]))
    if out_w <= 0 or out_h <= 0:
        return np.empty((0, 0, 3), dtype=bgr.dtype)

    if abs(photo.angle) <= 0.05:
        # Square to the glass: take the pixels exactly as scanned. Interpolating
        # onto a fractional centre here would blur the image for nothing.
        x0 = max(0, min(int(round(photo.center[0] - out_w / 2)), width - 1))
        y0 = max(0, min(int(round(photo.center[1] - out_h / 2)), height - 1))
        return bgr[y0 : min(height, y0 + out_h), x0 : min(width, x0 + out_w)]

    x0, y0, x1, y1 = photo.bounds()
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(width, x1 + pad), min(height, y1 + pad)
    region = bgr[y0:y1, x0:x1]
    if region.size == 0:
        return np.empty((0, 0, 3), dtype=bgr.dtype)

    # One transform that both straightens the print and places it in the
    # output, so the pixels are interpolated once rather than twice.
    centre = (photo.center[0] - x0, photo.center[1] - y0)
    matrix = cv2.getRotationMatrix2D(centre, photo.angle, 1.0)
    matrix[0, 2] += out_w / 2 - centre[0]
    matrix[1, 2] += out_h / 2 - centre[1]
    return cv2.warpAffine(
        region,
        matrix,
        (out_w, out_h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


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
    # The background was measured on an eight-bit view of the scan; a deeper
    # crop needs it, and the tolerance with it, on the same scale.
    scale = 257 if crop.dtype == np.uint16 else 1
    reference = np.asarray(background, dtype=np.int32) * scale
    diff = np.abs(crop.astype(np.int32) - reference).max(axis=2)
    is_bg = diff <= tolerance * scale

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


def neutralise(bgr: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Scale each channel so the lid, which is white, comes out neutral.

    Every scan carries its own reference white: the lid the prints sit against.
    Whatever tint it comes back with — a sensor that is not quite balanced, a
    mat that was never quite white — is the same tint laid over the prints, so
    dividing it out of the whole scan takes it off the photographs too.

    This corrects neutrality, not colour accuracy. It makes a known white read
    as white; it cannot tell you a red is the right red. That needs a target
    with known values on the glass.

    Done through a lookup table rather than arithmetic on the image: a 1200 dpi
    scan is 143 megapixels, and promoting that to float to multiply it would
    cost gigabytes on top of a split that already peaks near three.
    """
    bg = np.asarray(background, dtype=np.float64).reshape(-1)
    if bg.size != 3 or bg.min() <= 0:
        return bgr  # no usable reference; leave the pixels alone

    # Scale up to the brightest channel rather than down to the dimmest, so a
    # correction never darkens the scan. The gains are small either way.
    gain = bg.max() / bg

    if bgr.dtype == np.uint16:
        return _gain_deep(bgr, gain)

    ramp = np.arange(256, dtype=np.float64)
    table = np.empty((1, 256, 3), dtype=np.uint8)
    for channel in range(3):
        table[0, :, channel] = np.clip(ramp * gain[channel], 0, 255).astype(np.uint8)
    return cv2.LUT(bgr, table)


def _gain_deep(bgr: np.ndarray, gain: np.ndarray) -> np.ndarray:
    """The same correction on 16-bit pixels, where no lookup table fits.

    A band at a time: promoting a whole 16-bit film strip to float to multiply
    it would cost more memory than the split it is part of.
    """
    out = np.empty_like(bgr)
    rows = max(1, (1 << 22) // max(1, bgr.shape[1] * bgr.shape[2]))
    for start in range(0, bgr.shape[0], rows):
        band = bgr[start : start + rows].astype(np.float32)
        band *= gain.astype(np.float32)
        np.clip(band, 0, 65535, out=band)
        out[start : start + rows] = band.astype(np.uint16)
    return out


def save(crop: np.ndarray, path: Path, dpi: float, quality: int = JPEG_QUALITY) -> None:
    """Write a crop, tagging it with the scan's resolution."""
    path.parent.mkdir(parents=True, exist_ok=True)
    jpeg = path.suffix.lower() in {".jpg", ".jpeg"}

    if crop.dtype == np.uint16 and not jpeg:
        _save_deep(crop, path, dpi)
        return
    if crop.dtype == np.uint16:
        # A JPEG has nowhere to put the extra bits; say so by rounding rather
        # than by failing, since the depth is a scanner setting and the format
        # is a separate one.
        crop = (crop.astype(np.uint32) >> 8).astype(np.uint8)

    image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    params: dict = {"dpi": (dpi, dpi)}
    if jpeg:
        params.update(quality=quality, subsampling=0)
    image.save(path, **params)


def _save_deep(crop: np.ndarray, path: Path, dpi: float) -> None:
    """Write 16-bit pixels, which Pillow cannot do for colour at all.

    OpenCV writes them losslessly and tags a TIFF's resolution, but writes no
    resolution into a PNG, so that one is added afterwards. Every file this
    project writes carries the resolution it was scanned at; a deeper file is
    not an excuse to drop it.
    """
    resolution = int(round(dpi))
    if path.suffix.lower() in {".tif", ".tiff"}:
        cv2.imwrite(
            str(path),
            crop,
            [cv2.IMWRITE_TIFF_XDPI, resolution, cv2.IMWRITE_TIFF_YDPI, resolution],
        )
        return
    cv2.imwrite(str(path), crop)
    _write_png_resolution(path, dpi)


def _write_png_resolution(path: Path, dpi: float) -> None:
    """Put a pHYs chunk into a PNG, which is where a PNG keeps its resolution."""
    raw = path.read_bytes()
    signature, rest = raw[:8], raw[8:]
    # IHDR is always the first chunk, and pHYs need only come before the image
    # data, so directly after it is both legal and easy to find.
    length = int.from_bytes(rest[:4], "big")
    end = 4 + 4 + length + 4
    header, remainder = rest[:end], rest[end:]

    per_metre = int(round(dpi / 0.0254))
    payload = b"pHYs" + per_metre.to_bytes(4, "big") + per_metre.to_bytes(4, "big") + b"\x01"
    chunk = len(payload[4:]).to_bytes(4, "big") + payload
    chunk += (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")
    path.write_bytes(signature + header + chunk + remainder)


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
