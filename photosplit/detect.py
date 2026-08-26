"""Find the rectangular photo regions inside a flatbed scan."""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# Detection runs on a downscaled copy; this is the longest edge it uses.
WORK_MAX_EDGE = 1600


@dataclass
class Photo:
    """One detected photo, in full-resolution pixel coordinates."""

    center: tuple[float, float]
    size: tuple[float, float]  # width, height after deskew
    angle: float  # degrees to rotate the scan by to make this photo upright
    fill: float  # contour area / rect area, 1.0 for a perfect rectangle
    clipped: bool = False  # runs into the edge of the scannable area

    @property
    def area(self) -> float:
        return self.size[0] * self.size[1]

    def bounds(self) -> tuple[int, int, int, int]:
        """Axis-aligned bounding box (x0, y0, x1, y1) that contains the rect."""
        pts = cv2.boxPoints((self.center, self.size, self.angle))
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        return int(np.floor(x0)), int(np.floor(y0)), int(np.ceil(x1)), int(np.ceil(y1))


def background_color(bgr: np.ndarray, sample_edge: int = 800) -> np.ndarray:
    """The colour of the scanner lid.

    Sampling a border ring is tempting and wrong: photos are routinely laid
    right up to the edge of the glass, or hanging off it, which poisons the
    ring with photo content. Instead take the most common colour among the
    scan's *flat* pixels. The lid is one uniform expanse, so it wins the vote
    even when prints cover most of the bed, and nothing is assumed about
    whether that expanse is white or black.
    """
    scale = min(1.0, sample_edge / max(bgr.shape[:2]))
    small = (
        cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else bgr
    )
    blur = cv2.GaussianBlur(small, (0, 0), 1.2)
    gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
    grad = cv2.magnitude(
        cv2.Scharr(gray, cv2.CV_32F, 1, 0), cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    )
    flat = blur[grad <= np.percentile(grad, 35)].reshape(-1, 3)
    if flat.shape[0] < 100:
        return np.median(small.reshape(-1, 3), axis=0)

    step = 16
    coarse = (flat // step).astype(np.int32)
    keys = coarse[:, 0] * 256 + coarse[:, 1] * 16 + coarse[:, 2]
    winner = int(np.bincount(keys, minlength=4096).argmax())
    centre = np.array(
        [winner // 256, (winner // 16) % 16, winner % 16], dtype=np.float64
    ) * step + step / 2
    near = flat[np.abs(flat.astype(np.int16) - centre).max(axis=1) <= step]
    return np.median(near if near.size else flat, axis=0)


def background_tolerance(bgr: np.ndarray, bg: np.ndarray) -> float:
    """How far a pixel must stray from the lid colour to count as photo.

    Measured from how much the lid itself varies, floored so a very clean scan
    does not end up with a hair-trigger that treats dust as art, and capped so
    a noisy one does not swallow dark prints.
    """
    diff = np.abs(bgr.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    lid = diff[diff <= 24]
    if lid.size < 100:
        return 24.0
    return float(min(40.0, max(8.0, np.percentile(lid, 99) * 1.5)))


def foreground_mask(
    bgr: np.ndarray,
    bg: np.ndarray,
    dpi_scaled: float,
    colour_tol: float | None = None,
    edge_tol: float | None = None,
) -> np.ndarray:
    """Pixels that are not scanner background.

    Two signals are combined: distance from the background colour, which finds
    the body of every photo, and gradient magnitude, which finds the edge of a
    photo whose white border is nearly the same shade as the lid. Both
    thresholds default to a measurement of this scan's own noise, since what
    counts as "flat" depends on the scanner and the bit depth.
    """
    blur = cv2.GaussianBlur(bgr, (0, 0), 1.2)

    diff = np.abs(blur.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    if colour_tol is None:
        colour_tol = background_tolerance(bgr, bg)
    by_colour = (diff > colour_tol).astype(np.uint8)

    gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
    grad = cv2.magnitude(
        cv2.Scharr(gray, cv2.CV_32F, 1, 0), cv2.Scharr(gray, cv2.CV_32F, 0, 1)
    )
    if edge_tol is None:
        # Measure the gradient noise floor over pixels that are confidently
        # lid rather than merely under the colour threshold.
        #
        # Sampling only wide-open lid (eroding this mask first) lowers the
        # threshold enough to catch the outer edge of a white print border that
        # is within ~10 levels of the lid — but it also lets the gap between two
        # touching prints close up, merging them. A border shaved off one print
        # is a smaller loss than two prints welded into one file, so the noisier
        # sample is the deliberate choice here.
        lid = diff <= max(6.0, colour_tol * 0.4)
        floor = grad[lid]
        edge_tol = max(40.0, float(np.percentile(floor, 99.5)) * 1.5) if floor.size > 99 else 96.0
    by_edge = (grad > edge_tol).astype(np.uint8)

    mask = cv2.bitwise_or(by_colour, by_edge)

    # Only a hair of closing: enough to join a photo to its own faint border,
    # small enough to leave the gap between two neighbouring photos open.
    bridge = max(3, int(round(0.02 * dpi_scaled)) | 1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _kernel(bridge), iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _kernel(3), iterations=1)
    return mask


def _kernel(size: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _touches_edge(cx, cy, w, h, angle, shape, slack: int = 3) -> bool:
    """Does this rectangle run into the boundary of the scanned area?

    The bed is often smaller than the glass, so a print that looked fully on
    the platen can still be cut off. Saying so beats handing back a crop that
    is quietly missing an inch.
    """
    height, width = shape
    box = cv2.boxPoints(((cx, cy), (w, h), angle))
    return bool(
        box[:, 0].min() <= slack
        or box[:, 1].min() <= slack
        or box[:, 0].max() >= width - 1 - slack
        or box[:, 1].max() >= height - 1 - slack
    )


def _normalise(rect) -> tuple[tuple[float, float], tuple[float, float], float]:
    """Re-express a minAreaRect so the rotation needed is at most 45 degrees."""
    (cx, cy), (w, h), angle = rect
    if angle > 45:
        angle -= 90
        w, h = h, w
    elif angle < -45:
        angle += 90
        w, h = h, w
    return (cx, cy), (w, h), angle


def find_photos(
    bgr: np.ndarray,
    dpi: float,
    min_side_in: float = 1.0,
    min_fill: float = 0.62,
    separation_in: float = 0.03,
    max_coverage: float = 0.92,
) -> tuple[list[Photo], np.ndarray]:
    """Locate every photo in a scan.

    Returns the photos in reading order plus the colour of the scanner lid,
    which the crop stage needs in order to tell a sliver of background from a
    photo's own white border.
    """
    full_h, full_w = bgr.shape[:2]
    scale = min(1.0, WORK_MAX_EDGE / max(full_h, full_w))
    work = (
        cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1.0
        else bgr.copy()
    )

    bg = background_color(work)
    mask = foreground_mask(work, bg, dpi_scaled=dpi * scale)

    # Photos butted up against each other merge into one blob. Eroding first
    # pulls them apart; each rect is grown back by the same amount afterwards.
    erode_px = int(round(separation_in * dpi * scale))
    probe = (
        cv2.erode(mask, _kernel(erode_px * 2 + 1), iterations=1) if erode_px > 0 else mask
    )

    contours, _ = cv2.findContours(probe, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_side_px = min_side_in * dpi * scale
    work_area = work.shape[0] * work.shape[1]

    photos: list[Photo] = []
    for contour in contours:
        (cx, cy), (w, h), angle = _normalise(cv2.minAreaRect(contour))
        w += 2 * erode_px
        h += 2 * erode_px
        if min(w, h) < min_side_px:
            continue
        rect_area = w * h
        if rect_area <= 0 or rect_area / work_area > max_coverage:
            continue  # the platen border or a whole-bed artefact, not a photo
        fill = cv2.contourArea(contour) / max(rect_area, 1.0)
        if fill < min_fill:
            continue  # ragged blob: dust, a shadow, a torn edge
        photos.append(
            Photo(
                center=(cx / scale, cy / scale),
                size=(w / scale, h / scale),
                angle=angle,
                fill=fill,
                clipped=_touches_edge(cx, cy, w, h, angle, work.shape[:2]),
            )
        )

    # Reading order: top-to-bottom in rows, left-to-right within a row, so the
    # numbering matches how the photos sit on the glass. The row band is tied to
    # the photos actually present, so a page of 4x6s and a page of wallet prints
    # both group sensibly.
    if photos:
        band = max(1.0, float(np.median([p.size[1] for p in photos])) * 0.5)
        photos.sort(key=lambda p: (round(p.bounds()[1] / band), p.bounds()[0]))
    return photos, bg
