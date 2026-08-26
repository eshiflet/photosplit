"""Command line entry point: photosplit SCAN [SCAN ...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import __version__, extract
from .detect import Photo, find_photos

Image.MAX_IMAGE_PIXELS = None  # 1200 dpi scans are legitimately huge

SCAN_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
DEFAULT_DPI = 300.0


def load_scan(path: Path, dpi_override: float | None) -> tuple[np.ndarray, float]:
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


def gather(inputs: list[str], recursive: bool) -> list[Path]:
    """Expand the command line into a sorted list of scan files."""
    found: list[Path] = []
    for item in inputs:
        path = Path(item).expanduser()
        if path.is_dir():
            walk = path.rglob("*") if recursive else path.glob("*")
            found += [
                p
                for p in walk
                if p.suffix.lower() in SCAN_SUFFIXES and not p.name.startswith(".")
            ]
        elif path.exists():
            found.append(path)
        else:
            print(f"photosplit: no such file: {path}", file=sys.stderr)
    # A previous run's output living beside the scans should not be re-split.
    return sorted({p.resolve() for p in found if "-preview" not in p.stem})


def process(path: Path, args: argparse.Namespace) -> int:
    """Split one scan. Returns the number of photos written."""
    bgr, dpi = load_scan(path, args.dpi)
    photos: list[Photo]
    photos, background = find_photos(
        bgr,
        dpi=dpi,
        min_side_in=args.min_size,
        min_fill=args.min_fill,
        separation_in=args.separation,
    )

    out_dir = Path(args.output).expanduser() if args.output else path.parent / "split"
    label = f"{path.name} [{dpi:g} dpi]"

    if not photos:
        print(f"{label}: no photos found — try --preview, or lower --min-size")
        return 0

    if args.preview:
        preview_path = out_dir / f"{path.stem}-preview.jpg"
        extract.save(extract.preview(bgr, photos), preview_path, dpi, quality=88)
        print(f"{label}: preview -> {preview_path}")

    print(f"{label}: {len(photos)} photo(s)")
    written = 0
    for index, photo in enumerate(photos, start=1):
        w_in, h_in = photo.size[0] / dpi, photo.size[1] / dpi
        detail = f'  {index:2d}. {w_in:.1f}x{h_in:.1f} in  skew {photo.angle:+.2f}°'
        if args.dry_run:
            print(detail)
            written += 1
            continue

        crop = photo_crop(bgr, photo, background, dpi, args)
        if crop.size == 0:
            print(f"{detail}  -- skipped, empty crop", file=sys.stderr)
            continue
        target = out_dir / f"{path.stem}-{index:02d}.{args.format}"
        extract.save(crop, target, dpi, quality=args.quality)
        written += 1
        if args.verbose:
            print(f"{detail}  -> {target}")
        else:
            print(f"{detail}  -> {target.name}")
    return written


def photo_crop(
    bgr: np.ndarray,
    photo: Photo,
    background: np.ndarray,
    dpi: float,
    args: argparse.Namespace,
) -> np.ndarray:
    upright = Photo(photo.center, photo.size, 0.0 if args.no_deskew else photo.angle, photo.fill)
    crop = extract.deskew_crop(bgr, upright)
    if not args.no_trim:
        crop = extract.trim_background(crop, background, dpi)
    return crop


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photosplit",
        description="Split a flatbed scan of several photos into one file per photo.",
    )
    parser.add_argument("inputs", nargs="+", help="scan files, or folders of scans")
    parser.add_argument("-o", "--output", help="output folder (default: <scan folder>/split)")
    parser.add_argument(
        "-f", "--format", default="jpg", choices=["jpg", "png", "tif"], help="output format"
    )
    parser.add_argument("-q", "--quality", type=int, default=95, help="JPEG quality (default 95)")
    parser.add_argument("--dpi", type=float, help="override the scan resolution")
    parser.add_argument(
        "--min-size",
        type=float,
        default=1.0,
        help="ignore anything whose short side is under this many inches (default 1.0)",
    )
    parser.add_argument(
        "--separation",
        type=float,
        default=0.02,
        help="inches of erosion used to pull touching photos apart (default 0.02)",
    )
    parser.add_argument(
        "--min-fill",
        type=float,
        default=0.62,
        help="how rectangular a blob must be to count as a photo (0-1, default 0.62)",
    )
    parser.add_argument("--no-deskew", action="store_true", help="do not straighten crops")
    parser.add_argument("--no-trim", action="store_true", help="keep any background sliver")
    parser.add_argument(
        "-p", "--preview", action="store_true", help="also write the scan with boxes drawn on it"
    )
    parser.add_argument("-n", "--dry-run", action="store_true", help="report, write nothing")
    parser.add_argument("-r", "--recursive", action="store_true", help="descend into subfolders")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"photosplit {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    scans = gather(args.inputs, args.recursive)
    if not scans:
        print("photosplit: nothing to do", file=sys.stderr)
        return 1

    total = 0
    failed = 0
    for scan in scans:
        try:
            total += process(scan, args)
        except Exception as error:  # one bad scan should not stop the batch
            failed += 1
            print(f"{scan.name}: failed — {error}", file=sys.stderr)

    if len(scans) > 1 or failed:
        verb = "found in" if args.dry_run else "written from"
        print(f"\n{total} photo(s) {verb} {len(scans)} scan(s), {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
