"""Command line entry point: photosplit SCAN [SCAN ...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .split import SCAN_SUFFIXES, SplitOptions, split_scan


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


def options_from(args: argparse.Namespace) -> SplitOptions:
    return SplitOptions(
        output_dir=Path(args.output).expanduser() if args.output else None,
        fmt=args.format,
        quality=args.quality,
        dpi_override=args.dpi,
        min_size=args.min_size,
        separation=args.separation,
        min_fill=args.min_fill,
        deskew=not args.no_deskew,
        trim=not args.no_trim,
        preview=args.preview,
    )


def process(path: Path, args: argparse.Namespace) -> int:
    """Split one scan, reporting as it goes. Returns the number of photos."""
    options = options_from(args)
    result = split_scan(path, options, write=not args.dry_run)
    label = f"{path.name} [{result.dpi:g} dpi]"

    if not result.count:
        print(f"{label}: no photos found — try --preview, or lower --min-size")
        return 0

    if result.preview_path and not args.dry_run:
        print(f"{label}: preview -> {result.preview_path}")
    print(f"{label}: {result.count} photo(s)")

    reached = sum(1 for p in result.photos if p.clipped)
    for photo, target in zip(result.photos, result.written):
        w_in, h_in = photo.size[0] / result.dpi, photo.size[1] / result.dpi
        number = result.written.index(target) + 1
        detail = f"  {number:2d}. {w_in:.1f}x{h_in:.1f} in  skew {photo.angle:+.2f}°"
        if photo.clipped:
            detail += "  ** reaches the edge of the scan area **"
        if args.dry_run:
            print(detail)
        else:
            print(f"{detail}  -> {target if args.verbose else target.name}")
    if reached:
        print(
            f"  note: {reached} photo(s) reach the edge of the scan area and may be"
            " incomplete. The scannable area is often smaller than the glass."
        )
    return len(result.written)


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
        default=0.03,
        help="inches of erosion used to pull touching photos apart (default 0.03)",
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
