"""Look at what was written and say which of it looks wrong.

Every failure this project has had looked fine from the outside. A strip came
out as one frame; four frames were discarded for being a hundredth of an inch
too small; a scan through the wrong unit came back washed out; prints welded
together into a single blob. In each case files were written, the log said how
many, and nothing suggested anything was amiss until someone opened them.

So this opens them. It is not a quality metric — `scan_quality.py` is that —
it is a check that what came out is a photograph at all, of the kind that would
be obvious to a person and is tedious at five hundred files.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .split import load_scan

# A photograph has range in it. These are the levels out of 255 below which
# something has gone wrong rather than the picture being merely flat.
FLAT_CONTRAST = 6.0
DIM_MEAN = 26.0
BRIGHT_MEAN = 232.0
CLIPPED_SHARE = 12.0  # per cent at either end before it is worth saying
RUNT_SHARE = 0.35  # of the median area among its siblings


@dataclass
class Finding:
    path: Path
    problem: str
    detail: str


def look(path: Path, dpi_override: float | None = None) -> tuple[dict, list[str]]:
    """Measure one written crop, and say what looks wrong with it."""
    bgr, _ = load_scan(path, dpi_override)
    if bgr.size == 0:
        return {}, ["is empty"]

    grey = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if grey.max() > 255:
        grey = grey / 257.0
    facts = {
        "mean": float(grey.mean()),
        "contrast": float(grey.std()),
        "black": float((grey <= 2).mean() * 100),
        "white": float((grey >= 253).mean() * 100),
        "pixels": int(grey.size),
    }

    problems = []
    if facts["contrast"] < FLAT_CONTRAST:
        problems.append(f"almost no contrast ({facts['contrast']:.1f})")
    if facts["mean"] < DIM_MEAN:
        problems.append(f"very dark (mean {facts['mean']:.0f})")
    elif facts["mean"] > BRIGHT_MEAN:
        problems.append(f"very bright (mean {facts['mean']:.0f})")
    if facts["black"] > CLIPPED_SHARE:
        problems.append(f"{facts['black']:.0f}% crushed to black")
    if facts["white"] > CLIPPED_SHARE:
        problems.append(f"{facts['white']:.0f}% blown to white")
    return facts, problems


def review(paths: list[Path], dpi_override: float | None = None) -> list[Finding]:
    """Check a set of crops, including against each other."""
    measured: list[tuple[Path, dict, list[str]]] = []
    for path in paths:
        try:
            facts, problems = look(path, dpi_override)
        except Exception as problem:  # an unreadable file is itself a finding
            measured.append((path, {}, [f"could not be read: {problem}"]))
            continue
        measured.append((path, facts, problems))

    # A crop far smaller than its siblings is usually a fragment of one of
    # them rather than a photograph in its own right.
    sizes = [f["pixels"] for _, f, _ in measured if f.get("pixels")]
    if len(sizes) >= 3:
        typical = float(np.median(sizes))
        for path, facts, problems in measured:
            if facts.get("pixels") and facts["pixels"] < typical * RUNT_SHARE:
                problems.append(
                    f"much smaller than the others ({facts['pixels'] / typical:.0%} of median)"
                )

    return [
        Finding(path, problems[0], "; ".join(problems))
        for path, _, problems in measured
        if problems
    ]
