"""Report what a scanner does with nothing on the glass.

The measuring lives in `photosplit/blank.py`, shared with the app's glass
calibration; this is the command line over it. Scan the empty bed with the lid
closed and hand the file here.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photosplit.blank import Blank, draw_map, measure  # noqa: E402

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
