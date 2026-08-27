"""The scan-to-files step, shared by the command line and the app."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from . import dust as dust_module
from . import extract, film, negative
from .detect import Photo, find_photos

Image.MAX_IMAGE_PIXELS = None  # 1200 dpi scans are legitimately huge

SCAN_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
DEFAULT_DPI = 300.0


@dataclass
class SplitOptions:
    output_dir: Path | None = None  # None means a "split" folder beside the scan
    fmt: str = "jpg"
    quality: int = 95
    dpi_override: float | None = None
    min_size: float = 1.0
    separation: float = 0.03
    min_fill: float = 0.62
    deskew: bool = True
    trim: bool = True
    neutralise: bool = False
    # The originals are one continuous strip of film rather than separate
    # pieces, which is a different problem and wants a different detector.
    strip: bool = False
    # The originals are negatives, so what comes out has to be turned over.
    invert: bool = False
    dust: bool = False
    dust_strength: str = "normal"
    # Ring the specks rather than removing them, so what would be taken can be
    # looked at before it is.
    dust_preview: bool = False
    # Free text written into every file: what film, what exposure, what the
    # picture is of. Recoverable from nobody's memory once the strip is filed.
    note: str = ""
    preview: bool = False
    stem: str | None = None  # base name for the output files


@dataclass
class SplitResult:
    scan: Path
    dpi: float
    photos: list[Photo] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    preview_path: Path | None = None

    @property
    def count(self) -> int:
        return len(self.photos)


def load_scan(
    path: Path, dpi_override: float | None = None, keep_depth: bool = False
) -> tuple[np.ndarray, float]:
    """Read a scan as BGR, along with the resolution it was scanned at.

    Eight bits per channel unless asked otherwise, because everything that
    measures a scan — the detector's thresholds, the quality tools — is
    written in levels out of 255. `keep_depth` hands back what the file
    actually holds, for the one caller that writes the pixels out again.
    """
    with Image.open(path) as image:
        dpi = dpi_override or _dpi_from(image)
        if not keep_depth:
            return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR), dpi

    # Pillow cannot read 16-bit colour; OpenCV can, and hands back BGR already.
    deep = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if deep is None or deep.dtype != np.uint16:
        with Image.open(path) as image:
            return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2BGR), dpi
    if deep.ndim == 2:
        deep = cv2.cvtColor(deep, cv2.COLOR_GRAY2BGR)
    return deep[:, :, :3], dpi


def eight_bit(bgr: np.ndarray) -> np.ndarray:
    """The same picture in levels out of 255, for anything that measures it."""
    if bgr.dtype != np.uint16:
        return bgr
    return (bgr.astype(np.uint32) >> 8).astype(np.uint8)


def _dpi_from(image: Image.Image) -> float:
    value = image.info.get("dpi")
    if isinstance(value, (tuple, list)) and value and float(value[0]) > 1:
        return float(value[0])
    return DEFAULT_DPI


def split_scan(
    path: Path,
    options: SplitOptions,
    on_photo: Callable[[int, int, Path], None] | None = None,
    write: bool = True,
) -> SplitResult:
    """Find every photo in one scan and write each to its own file."""
    bgr, dpi = load_scan(path, options.dpi_override, keep_depth=True)
    # Find the photos in an eight-bit view, cut them out of the real one: every
    # threshold in the detector is a number of levels out of 255.
    view = eight_bit(bgr)
    if options.strip:
        photos, background = film.find_frames(view, dpi=dpi, min_side_in=options.min_size)
    else:
        photos, background = find_photos(
            view,
            dpi=dpi,
            min_side_in=options.min_size,
            min_fill=options.min_fill,
            separation_in=options.separation,
        )
    result = SplitResult(scan=path, dpi=dpi, photos=photos)
    if not photos:
        return result

    if options.neutralise:
        # Correct the whole scan once, so the preview shows what the crops get.
        bgr = extract.neutralise(bgr, background)

    out_dir = options.output_dir or path.parent / "split"
    stem = options.stem or path.stem

    # Measured once for the whole strip: the rebate is between the frames, so
    # no single frame contains it.
    film_base = None
    if options.invert:
        film_base = film.measure_base(view, dpi)
        if film_base is None:
            film_base = negative.estimate_base(view)

    if options.preview:
        result.preview_path = out_dir / f"{stem}-preview.jpg"
        if write:
            extract.save(extract.preview(view, photos), result.preview_path, dpi, quality=88)

    for index, photo in enumerate(photos, start=1):
        target = out_dir / f"{stem}-{index:02d}.{options.fmt}"
        if write:
            crop = crop_photo(bgr, photo, background, dpi, options)
            if crop.size == 0:
                continue
            if options.invert and film_base is not None:
                scale = 257.0 if crop.dtype == np.uint16 else 1.0
                crop = negative.invert(crop, np.asarray(film_base) * scale)
            if options.dust:
                # After the inversion, on the picture as it will be seen: a
                # speck is a speck in the positive, whichever way the original
                # recorded it.
                if options.dust_preview:
                    found = dust_module.find_specks(crop, dpi, options.dust_strength)
                    crop = dust_module.mark(crop, found)
                else:
                    crop, _ = dust_module.remove(crop, dpi, options.dust_strength)
            extract.save(crop, target, dpi, quality=options.quality, note=options.note)
        result.written.append(target)
        if on_photo is not None:
            on_photo(index, len(photos), target)
    return result


def crop_photo(
    bgr: np.ndarray,
    photo: Photo,
    background: np.ndarray,
    dpi: float,
    options: SplitOptions,
) -> np.ndarray:
    upright = Photo(photo.center, photo.size, photo.angle if options.deskew else 0.0, photo.fill)
    crop = extract.deskew_crop(bgr, upright)
    if options.trim:
        crop = extract.trim_background(crop, background, dpi)
    return crop
