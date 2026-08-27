"""What a scanner does with nothing on the glass, shared by the tool and the app.

`split.py` is the scan-to-files step; this is the scan-to-diagnosis one. It is
the question worth asking before a print is ever involved:

  - Dirt sits in the same place on every scan, so a speck here is a speck in
    every photograph until someone cleans it.
  - Dust inside the optics shows as a stripe down the whole bed rather than a
    spot, and cleaning the glass will never move it.
  - The illumination is not even. A bed that darkens towards an edge reads as
    "not background" to the splitter and welds every print in that margin into
    one blob, whatever the spacing between them.
  - The colour cast either is or is not the same across the bed, which decides
    whether one gain per channel can correct it.

Take the scan with the lid closed and nothing on the glass.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .split import load_scan

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


# -- calibration ----------------------------------------------------------
# The app keeps one of these per machine so it can say whether a clean helped,
# and so the margins it measured are on hand the next time a print lands in one.

CALIBRATION_JSON = "dust-map.json"
CALIBRATION_MAP = "dust-map.png"


def calibration_folder() -> Path:
    """Where a Mac app is supposed to keep data it generated itself."""
    return Path.home() / "Library" / "Application Support" / "Photosplit"


def save_calibration(folder: Path, blank: Blank, specks: list, scan: Path) -> Path:
    """Record this calibration, keeping the previous one to compare against."""
    folder.mkdir(parents=True, exist_ok=True)
    previous = load_calibration(folder)
    record = asdict(blank)
    record["measured"] = datetime.now().isoformat(timespec="seconds")
    record["specks_seen"] = [
        {"area_px": int(a), "x_in": round(x / blank.dpi, 3), "y_in": round(y / blank.dpi, 3)}
        for a, x, y, _ in specks[:200]
    ]
    if previous is not None:
        # Only the numbers, never the previous one's own history: keeping a
        # chain of these would grow the file without bound.
        record["previous"] = {
            k: previous.get(k) for k in ("measured", "specks", "speck_area_pct", "largest_speck_mm")
        }
    path = folder / CALIBRATION_JSON
    path.write_text(json.dumps(record, indent=2))
    draw_map(scan, specks, blank.falloff_in, folder / CALIBRATION_MAP, blank.dpi)
    return path


def load_calibration(folder: Path) -> dict | None:
    path = folder / CALIBRATION_JSON
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None  # a half-written or hand-edited file is not worth crashing over


def verdict(blank: Blank, previous: dict | None) -> list[str]:
    """What to tell someone who has just cleaned the glass.

    A speck count on its own means nothing — 98 looked alarming and 71 looked
    fine on the same scanner — so it is only ever reported against the last
    one, and the margin it measured is reported because that is the number
    that decides where a print may be laid.
    """
    lines = [
        f"Glass calibrated: {blank.specks} speck(s), "
        f"{blank.speck_area_pct:.4f}% of the bed, largest {blank.largest_speck_mm:.2f} mm."
    ]
    if previous and previous.get("specks") is not None:
        was, now = float(previous["speck_area_pct"]), blank.speck_area_pct
        if now < was * 0.9:
            change = f"cleaner than last time ({previous['specks']} speck(s))"
        elif now > was * 1.1:
            change = f"dirtier than last time ({previous['specks']} speck(s))"
        else:
            change = f"about the same as last time ({previous['specks']} speck(s))"
        lines.append(f"  {change}")

    margin = max(blank.falloff_in.values())
    if margin >= 0.15:
        edge = max(blank.falloff_in, key=lambda k: blank.falloff_in[k])
        lines.append(
            f"  Keep prints {margin:.2f} in clear of the {edge} edge: "
            "the bed is dark there and photos in it merge."
        )
    if blank.streak_columns > 50:
        lines.append(
            f"  {blank.streak_columns} streaked column(s) — that is dust inside the "
            "scanner, not on the glass, and cleaning will not shift it."
        )
    return lines
