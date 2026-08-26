"""Measure a scan's optical quality, so two scanners can be compared fairly.

Run the same photos through two scanners and diff the numbers. Everything here
is measured off the prints themselves and the lid around them, so it does not
depend on what the photographs happen to contain.

What it cannot tell you: absolute colour accuracy. That needs a reference
target with known values (an IT8 or ColorChecker card) laid on the glass. What
it does measure is colour *neutrality* — whether the scanner renders a known
white as white — plus sharpness, noise, and how much tonal range survives.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photosplit.detect import Photo, background_color, find_photos  # noqa: E402
from photosplit.extract import deskew_crop  # noqa: E402
from photosplit.split import load_scan  # noqa: E402

MARGIN_IN = 0.06  # how much lid to include around a print when profiling its edge


@dataclass
class Quality:
    scan: str
    dpi: float
    photos: int
    lid_rgb: list[float]
    lid_cast: float
    lid_noise: float
    edge_rise_um: float | None
    edge_rise_px: float | None
    edges_measured: int
    luma_p1: float
    luma_p99: float
    clipped_black_pct: float
    clipped_white_pct: float
    saturation: float
    shadow_noise: float


def luminance(bgr: np.ndarray) -> np.ndarray:
    return (
        0.114 * bgr[..., 0] + 0.587 * bgr[..., 1] + 0.299 * bgr[..., 2]
    ).astype(np.float32)


def edge_rise(bgr: np.ndarray, photo: Photo, dpi: float) -> list[float]:
    """10-90% rise distance in microns at the print's own edges.

    A sharper scanner turns the step from lid to print over a shorter distance.
    Measured on the deskewed crop so a crooked print is not penalised.
    """
    margin = int(round(MARGIN_IN * dpi))
    grown = Photo(
        photo.center,
        (photo.size[0] + 2 * margin, photo.size[1] + 2 * margin),
        photo.angle,
        photo.fill,
    )
    patch = deskew_crop(bgr, grown, pad=margin * 2)
    if patch.size == 0 or min(patch.shape[:2]) < 4 * margin:
        return []

    grey = luminance(patch)
    h, w = grey.shape
    rises: list[float] = []
    # Each edge as a profile running lid -> print, sampled across its middle.
    profiles = [
        grey[int(h * 0.2) : int(h * 0.8), : 2 * margin].mean(axis=0),
        grey[int(h * 0.2) : int(h * 0.8), w - 2 * margin :].mean(axis=0)[::-1],
        grey[: 2 * margin, int(w * 0.2) : int(w * 0.8)].mean(axis=1),
        grey[h - 2 * margin :, int(w * 0.2) : int(w * 0.8)].mean(axis=1)[::-1],
    ]
    for profile in profiles:
        if profile.size < 6:
            continue
        lid, print_side = profile[0], profile[-1]
        if abs(lid - print_side) < 20:
            continue  # too little contrast at this edge to time the transition
        low, high = sorted((lid, print_side))
        span = high - low
        crossings = []
        for fraction in (0.1, 0.9):
            level = low + span * fraction
            above = np.where(
                (profile[:-1] - level) * (profile[1:] - level) <= 0
            )[0]
            if above.size == 0:
                break
            crossings.append(float(above[0]))
        if len(crossings) != 2:
            continue
        width = abs(crossings[1] - crossings[0])
        if 0 < width < 2 * margin:
            rises.append(width / dpi * 25400.0)
    return rises


def measure(path: Path, dpi_override: float | None = None) -> Quality:
    bgr, dpi = load_scan(path, dpi_override)
    photos, lid = find_photos(bgr, dpi=dpi)

    lid_mask = (
        np.abs(bgr.astype(np.int16) - lid.astype(np.int16)).max(axis=2) <= 10
    )
    lid_pixels = bgr[lid_mask]
    lid_rgb = lid_pixels[:, ::-1].mean(axis=0) if lid_pixels.size else np.zeros(3)
    lid_noise = float(luminance(bgr)[lid_mask].std()) if lid_pixels.size else 0.0

    rises: list[float] = []
    lumas: list[np.ndarray] = []
    sats: list[float] = []
    shadow: list[float] = []
    for photo in photos:
        rises += edge_rise(bgr, photo, dpi)
        crop = deskew_crop(bgr, photo)
        if crop.size == 0:
            continue
        inner = crop[
            int(crop.shape[0] * 0.1) : int(crop.shape[0] * 0.9),
            int(crop.shape[1] * 0.1) : int(crop.shape[1] * 0.9),
        ]
        if inner.size == 0:
            continue
        y = luminance(inner)
        lumas.append(y.ravel())
        hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
        sats.append(float(hsv[..., 1].mean()))
        dark = y < np.percentile(y, 10)
        if dark.sum() > 100:
            shadow.append(float(y[dark].std()))

    every = np.concatenate(lumas) if lumas else np.zeros(1)
    return Quality(
        scan=path.name,
        dpi=dpi,
        photos=len(photos),
        lid_rgb=[round(float(v), 1) for v in lid_rgb],
        lid_cast=round(float(lid_rgb.max() - lid_rgb.min()), 2),
        lid_noise=round(lid_noise, 3),
        edge_rise_um=round(float(np.median(rises)), 1) if rises else None,
        edge_rise_px=(
            round(float(np.median(rises)) / (25400.0 / dpi), 1) if rises else None
        ),
        edges_measured=len(rises),
        luma_p1=round(float(np.percentile(every, 1)), 1),
        luma_p99=round(float(np.percentile(every, 99)), 1),
        clipped_black_pct=round(float((every <= 2).mean() * 100), 3),
        clipped_white_pct=round(float((every >= 253).mean() * 100), 3),
        saturation=round(float(np.mean(sats)) if sats else 0.0, 1),
        shadow_noise=round(float(np.mean(shadow)) if shadow else 0.0, 2),
    )


ROWS = [
    ("photos found", "photos", "{}", ""),
    ("lid R,G,B", "lid_rgb", "{}", "what the scanner makes of a white lid"),
    ("lid colour cast", "lid_cast", "{:.2f}", "spread between channels; lower is more neutral"),
    ("lid noise", "lid_noise", "{:.3f}", "grain on a uniform surface; lower is cleaner"),
    ("edge rise", "edge_rise_um", "{} um", "10-90% at a print edge; lower is sharper"),
    ("  in pixels", "edge_rise_px", "{} px", "under ~3 px this is the sampling floor, not the optics"),
    ("edges measured", "edges_measured", "{}", ""),
    ("shadow detail (p1)", "luma_p1", "{:.1f}", "higher means less crushed"),
    ("highlight (p99)", "luma_p99", "{:.1f}", "lower means less blown"),
    ("clipped black", "clipped_black_pct", "{:.3f} %", "detail lost at the bottom"),
    ("clipped white", "clipped_white_pct", "{:.3f} %", "detail lost at the top"),
    ("saturation", "saturation", "{:.1f}", "mean chroma across the prints"),
    ("shadow noise", "shadow_noise", "{:.2f}", "grain in the darkest tenth"),
]


SAMPLING_WARNING = (
    "\nEdge rise measured at 2 px or so is not a measurement of the optics: the\n"
    "transition is sharper than the pixel grid, and the figure only reflects the\n"
    "resolution chosen. Compare optics between scanners at their highest\n"
    "resolution, where sampling out-resolves the lens."
)

LID_ONLY_WARNING = (
    "\nNote: the lid figures compare cleanly between any two scans. The tonal\n"
    "figures (shadow, highlight, clipping, saturation) describe the prints that\n"
    "were on the glass, so they are only comparable when both scans hold the\n"
    "same photos."
)


def report(results: list[Quality]) -> None:
    width = max(len(label) for label, *_ in ROWS) + 2
    header = "".join(f"{r.scan[:22]:>24}" for r in results)
    print(f"{'':{width}}{header}")
    for label, field, fmt, note in ROWS:
        cells = ""
        for result in results:
            value = getattr(result, field)
            cells += f"{('n/a' if value is None else fmt.format(value)):>24}"
        print(f"{label:{width}}{cells}   {note}")
    if any(r.edge_rise_px is not None and r.edge_rise_px <= 2.5 for r in results):
        print(SAMPLING_WARNING)
    if len(results) > 1 and len({r.photos for r in results}) > 1:
        print(LID_ONLY_WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure scan quality, for comparing one scanner against another."
    )
    parser.add_argument("scans", nargs="+", help="full-bed scans to measure")
    parser.add_argument("--dpi", type=float, help="override the scan resolution")
    parser.add_argument("--json", help="also write the numbers here")
    args = parser.parse_args()

    results = [measure(Path(s).expanduser(), args.dpi) for s in args.scans]
    report(results)
    if args.json:
        Path(args.json).write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
