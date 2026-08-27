"""Measure an empty bed: what the scanner does when nothing is on the glass.

`scan_quality.py` answers "how good are these scans of these prints". This
answers "what is wrong with this scanner before a print is even involved",
which turns out to be the question worth asking first:

  - Dirt sits in the same place on every scan, so a speck found here is a
    speck in every photograph until someone cleans it.
  - Dust inside the optics shows up as a stripe down the whole bed rather
    than a spot, and no amount of cleaning the glass will move it.
  - The illumination is not even. A bed that darkens towards one edge reads
    as "not background" to the splitter and welds every print in that margin
    into one blob, whatever the spacing between them.
  - The colour cast either is or is not the same across the bed, which is
    what decides whether one gain per channel can correct it.

Take the scan with the lid closed and nothing on the glass.
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

from photosplit.split import load_scan  # noqa: E402

SPECK_DROP = 20  # levels below local background before a pixel counts as dirt
SPECK_MIN_PX = 4  # smaller than this is sensor noise, not something to clean
EDGE_TOLERANCE = 6.0  # levels; how close to the centre counts as "recovered"
# The outermost rows of a scan carry artefacts that differ between scans of the
# same untouched bed, so they are never dirt. Ignore a sliver regardless of what
# the falloff measures, or a clean bed reports dozens of specks that cannot be
# wiped off because they are not there.
MIN_MARGIN_IN = 0.10


@dataclass
class Blank:
    scan: str
    dpi: float
    mean: float
    noise: float
    uniformity: float
    cast: float
    cast_varies: float
    falloff_in: dict[str, float]
    specks: int
    speck_area_px: int
    speck_area_pct: float
    largest_speck_px: int
    largest_speck_mm: float
    streak_columns: int


def zones(image: np.ndarray, rows: int = 3, cols: int = 3):
    """The bed in a grid, so unevenness across it has somewhere to show up."""
    h, w = image.shape[:2]
    for r in range(rows):
        for c in range(cols):
            yield image[
                int(h * r / rows) : int(h * (r + 1) / rows),
                int(w * c / cols) : int(w * (c + 1) / cols),
            ]


def edge_falloff(grey: np.ndarray, dpi: float) -> dict[str, float]:
    """How far in from each edge before the lighting matches the centre.

    This is the number that decides where a print may safely be laid. Inside
    it the bed is darker than the lid the splitter is looking for.
    """
    h, w = grey.shape
    centre = float(grey[int(h * 0.25) : int(h * 0.75), int(w * 0.25) : int(w * 0.75)].mean())
    limit = int(min(h, w) * 0.25)

    def depth(profile: np.ndarray) -> float:
        ok = np.where(profile > centre - EDGE_TOLERANCE)[0]
        return round(float(ok[0] / dpi), 3) if ok.size else round(limit / dpi, 3)

    # Profile each margin along the axis that runs away from that edge.
    return {
        "left": depth(grey[:, :limit].mean(axis=0)),
        "right": depth(grey[:, w - limit :].mean(axis=0)[::-1]),
        "top": depth(grey[:limit].mean(axis=1)),
        "bottom": depth(grey[h - limit :].mean(axis=1)[::-1]),
    }


def find_specks(grey: np.ndarray, margins: dict[str, float], dpi: float):
    """Every spot darker than its surroundings, ignoring the vignetted margins.

    The first and last row of a scan carry edge artefacts that change between
    scans and are not dirt, so the measured falloff is used as the margin
    rather than a fixed guess.
    """
    h, w = grey.shape
    small = cv2.resize(grey, (max(1, w // 8), max(1, h // 8)), interpolation=cv2.INTER_AREA)
    background = cv2.resize(
        cv2.medianBlur(small, 31), (w, h), interpolation=cv2.INTER_LINEAR
    ).astype(np.int16)
    mask = ((background - grey.astype(np.int16)) > SPECK_DROP).astype(np.uint8)

    def inset(edge: str) -> int:
        return max(int(max(margins[edge], MIN_MARGIN_IN) * dpi), 1)

    left, right = inset("left"), w - inset("right")
    top, bottom = inset("top"), h - inset("bottom")

    count, _, stats, centres = cv2.connectedComponentsWithStats(mask, 8)
    found = []
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        x, y = float(centres[i][0]), float(centres[i][1])
        if area < SPECK_MIN_PX or not (left < x < right and top < y < bottom):
            continue
        found.append((area, x, y, int(max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]))))
    found.sort(reverse=True)
    return found


def streak_columns(grey: np.ndarray, margins: dict[str, float], dpi: float) -> int:
    """Columns darker than their neighbours all the way down the bed.

    The carriage travels the length of the glass, so a mark on the mirror or
    the lens is painted into every row of one column. That is inside the
    scanner and cleaning the glass will not touch it.
    """
    w = grey.shape[1]
    left = max(int(max(margins["left"], MIN_MARGIN_IN) * dpi), 1)
    right = w - max(int(max(margins["right"], MIN_MARGIN_IN) * dpi), 1)
    column = grey.mean(axis=0)
    trend = cv2.blur(column.reshape(1, -1).astype(np.float32), (151, 1)).ravel()
    deviation = column - trend
    return int((deviation[left:right] < -2.0).sum())


def measure(path: Path, dpi_override: float | None = None) -> tuple[Blank, list]:
    bgr, dpi = load_scan(path, dpi_override)
    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = grey.shape

    patches = list(zones(grey))
    means = [float(p.mean()) for p in patches]
    casts = [float(np.ptp(p.reshape(-1, 3).mean(axis=0))) for p in zones(bgr)]

    margins = edge_falloff(grey, dpi)
    specks = find_specks(grey, margins, dpi)
    area = sum(s[0] for s in specks)

    return (
        Blank(
            scan=path.name,
            dpi=dpi,
            mean=round(float(grey.mean()), 1),
            noise=round(float(grey.std()), 3),
            uniformity=round(max(means) - min(means), 2),
            cast=round(float(np.mean(casts)), 2),
            cast_varies=round(max(casts) - min(casts), 2),
            falloff_in=margins,
            specks=len(specks),
            speck_area_px=area,
            speck_area_pct=round(area / (h * w) * 100, 5),
            largest_speck_px=specks[0][0] if specks else 0,
            largest_speck_mm=round(specks[0][3] / dpi * 25.4, 2) if specks else 0.0,
            streak_columns=streak_columns(grey, margins, dpi),
        ),
        specks,
    )


def draw_map(path: Path, specks: list, margins: dict[str, float], out: Path, dpi: float) -> None:
    """The bed with every speck ringed, so they can be found on the glass."""
    bgr, _ = load_scan(path, dpi)
    h, w = bgr.shape[:2]
    scale = 8
    image = cv2.resize(bgr, (w // scale, h // scale), interpolation=cv2.INTER_AREA)
    ih, iw = image.shape[:2]
    for i in range(1, int(w / dpi) + 1):
        x = int(i * dpi / scale)
        cv2.line(image, (x, 0), (x, ih), (225, 225, 225), 1)
        cv2.putText(image, str(i), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
    for i in range(1, int(h / dpi) + 1):
        y = int(i * dpi / scale)
        cv2.line(image, (0, y), (iw, y), (225, 225, 225), 1)
        cv2.putText(image, str(i), (2, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (150, 150, 150), 1)
    cv2.rectangle(image, (0, 0), (int(margins["left"] * dpi / scale), ih), (255, 190, 140), 1)
    for rank, (area, x, y, _) in enumerate(specks, start=1):
        radius = max(4, int(np.sqrt(area) / scale * 3))
        colour = (0, 0, 220) if rank <= 10 else (0, 140, 255)
        cv2.circle(image, (int(x / scale), int(y / scale)), radius, colour, 1, cv2.LINE_AA)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image)


ROWS = [
    ("bed mean", "mean", "{:.1f}", "average level with nothing on the glass"),
    ("noise", "noise", "{:.3f}", "spread over the whole bed; includes the dirt"),
    ("uniformity", "uniformity", "{:.2f}", "brightest zone minus darkest; lower is flatter"),
    ("colour cast", "cast", "{:.2f}", "channel spread; lower is more neutral"),
    ("  varies by", "cast_varies", "{:.2f}", "how much the cast moves across the bed"),
    ("specks", "specks", "{}", "spots darker than their surroundings"),
    ("  total area", "speck_area_pct", "{:.5f} %", "how much of the bed they cover"),
    ("  largest", "largest_speck_mm", "{:.2f} mm", "the one most likely to show in a photo"),
    ("streak columns", "streak_columns", "{}", "above ~50 suggests dust inside the optics"),
]


def report(blanks: list[Blank]) -> None:
    width = max(28, max(len(b.scan) for b in blanks) + 2)
    print(" " * 18 + "".join(f"{b.scan:>{width}}" for b in blanks))
    for label, field, form, note in ROWS:
        cells = "".join(f"{form.format(getattr(b, field)):>{width}}" for b in blanks)
        print(f"{label:18s}{cells}   {note}")
    for edge in ("left", "right", "top", "bottom"):
        cells = "".join(f"{b.falloff_in[edge]:>{width}.2f}" for b in blanks)
        note = "inches before the lighting matches the centre" if edge == "left" else ""
        print(f"{'falloff ' + edge:18s}{cells}   {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure a scan of an empty bed.")
    parser.add_argument("scans", nargs="+", help="scans taken with nothing on the glass")
    parser.add_argument("--dpi", type=float, help="override the scan resolution")
    parser.add_argument("--json", help="also write the numbers here")
    parser.add_argument("--map", help="write a PNG of the bed with every speck ringed")
    args = parser.parse_args()

    blanks, last = [], None
    for name in args.scans:
        path = Path(name).expanduser()
        blank, specks = measure(path, args.dpi)
        blanks.append(blank)
        last = (path, specks, blank)

    report(blanks)

    if args.map and last is not None:
        path, specks, blank = last
        draw_map(path, specks, blank.falloff_in, Path(args.map).expanduser(), blank.dpi)
        print(f"\nmap -> {args.map}")
    if args.json:
        Path(args.json).expanduser().write_text(
            json.dumps([asdict(b) for b in blanks], indent=2)
        )
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
