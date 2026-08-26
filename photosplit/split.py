"""The scan-to-files step, shared by the command line and the app."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image

from . import extract
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


def load_scan(path: Path, dpi_override: float | None = None) -> tuple[np.ndarray, float]:
    """Read a scan as BGR, along with the resolution it was scanned at."""
    with Image.open(path) as image:
        dpi = dpi_override or _dpi_from(image)
        rgb = np.asarray(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), dpi


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
    bgr, dpi = load_scan(path, options.dpi_override)
    photos, background = find_photos(
        bgr,
        dpi=dpi,
        min_side_in=options.min_size,
        min_fill=options.min_fill,
        separation_in=options.separation,
    )
    result = SplitResult(scan=path, dpi=dpi, photos=photos)
    if not photos:
        return result

    out_dir = options.output_dir or path.parent / "split"
    stem = options.stem or path.stem

    if options.preview:
        result.preview_path = out_dir / f"{stem}-preview.jpg"
        if write:
            extract.save(extract.preview(bgr, photos), result.preview_path, dpi, quality=88)

    for index, photo in enumerate(photos, start=1):
        target = out_dir / f"{stem}-{index:02d}.{options.fmt}"
        if write:
            crop = crop_photo(bgr, photo, background, dpi, options)
            if crop.size == 0:
                continue
            extract.save(crop, target, dpi, quality=options.quality)
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
