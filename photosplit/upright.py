"""Decide which way up a photograph goes, by looking for faces.

A print laid sideways on the glass is scanned sideways. Nothing in the pixels
says which edge was the top — not the brightness, not the composition, not the
sky, which is only usually up and only outdoors. Faces do say, and they are in
most photographs anyone bothers to keep.

So the picture is offered to a face detector four times, once each way round,
and whichever way finds the most convincing faces is which way up it goes. If
no way round finds a face, it is left exactly as it was: a photograph nobody
can orient is better left alone than turned on a guess.

The detector is YuNet, vendored in `models/` so that scanning never needs the
network. See that folder for the licence.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

MODEL = Path(__file__).resolve().parent / "models" / "face_detection_yunet_2023mar.onnx"

WORK_EDGE = 640  # faces are found on a small copy; the full scan is needless
MIN_SCORE = 0.7  # below this a "face" is a pattern that happens to look like one
MARGIN = 1.25  # how much the winner must beat the runner-up before turning anything

ROTATIONS = {
    0: None,
    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,
}


def turn(bgr: np.ndarray, degrees: int) -> np.ndarray:
    """The picture turned by a quarter, half or three quarters, losslessly."""
    how = ROTATIONS.get(degrees % 360)
    return bgr if how is None else cv2.rotate(bgr, how)


def _quiet() -> None:
    """Stop OpenCV narrating its backend choice once per photograph."""
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass


def _detector(size: tuple[int, int]):
    if not MODEL.exists():
        return None
    _quiet()
    try:
        return cv2.FaceDetectorYN.create(str(MODEL), "", size, MIN_SCORE)
    except Exception:
        return None  # a model that will not load must not stop a scan


def _score(detector, image: np.ndarray) -> float:
    """How convincing the faces are this way up, summed."""
    height, width = image.shape[:2]
    detector.setInputSize((width, height))
    try:
        _, faces = detector.detect(image)
    except Exception:
        return 0.0
    if faces is None:
        return 0.0
    return float(sum(f[-1] for f in faces if f[-1] >= MIN_SCORE))


def which_way_up(bgr: np.ndarray) -> tuple[int, dict[int, float]]:
    """How far to turn this picture, and what each way round scored.

    Zero when nothing is convincing enough, which includes every photograph
    with no face in it.
    """
    scores = {degrees: 0.0 for degrees in ROTATIONS}
    if bgr is None or bgr.size == 0:
        return 0, scores

    small = bgr
    if small.dtype == np.uint16:
        small = (small.astype(np.uint32) >> 8).astype(np.uint8)
    longest = max(small.shape[:2])
    if longest > WORK_EDGE:
        scale = WORK_EDGE / longest
        small = cv2.resize(small, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    if small.ndim == 2:
        small = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)

    detector = _detector((small.shape[1], small.shape[0]))
    if detector is None:
        return 0, scores

    for degrees in ROTATIONS:
        scores[degrees] = _score(detector, turn(small, degrees))

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best, best_score = ranked[0]
    runner_up = ranked[1][1]
    if best_score <= 0:
        return 0, scores
    # Turning on a narrow win is how a photograph ends up upside down, so the
    # best way round has to be clearly better than the next best.
    if best != 0 and best_score < max(runner_up * MARGIN, MIN_SCORE):
        return 0, scores
    return best, scores


def upright(bgr: np.ndarray) -> tuple[np.ndarray, int]:
    """The picture the right way up, and how far it had to be turned."""
    degrees, _ = which_way_up(bgr)
    return (turn(bgr, degrees) if degrees else bgr), degrees
