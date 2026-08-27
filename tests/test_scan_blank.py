"""Checks for the empty-bed measurements, against beds with known defects."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import scan_blank  # noqa: E402

DPI = 300
BED = 242


def bed(dir: Path, name: str, draw=None, w_in: float = 3.0, h_in: float = 4.0) -> Path:
    image = np.full((int(h_in * DPI), int(w_in * DPI), 3), BED, np.uint8)
    if draw is not None:
        draw(image)
    path = dir / name
    cv2.imwrite(str(path), image)
    return path


class BlankBedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-blank-"))

    def test_a_clean_even_bed_reports_nothing_wrong(self) -> None:
        blank, _ = scan_blank.measure(bed(self.dir, "clean.png"), DPI)
        self.assertEqual(blank.specks, 0)
        self.assertEqual(blank.streak_columns, 0)
        self.assertLess(blank.uniformity, 1.0)
        for edge in ("left", "right", "top", "bottom"):
            self.assertAlmostEqual(blank.falloff_in[edge], 0.0, places=2)

    def test_every_speck_is_counted_and_the_largest_reported(self) -> None:
        spots = [(120, 200), (300, 500), (600, 900), (200, 1000)]

        def draw(image):
            for x, y in spots:
                cv2.circle(image, (x, y), 4, (90, 90, 90), -1)
            cv2.circle(image, (450, 700), 12, (90, 90, 90), -1)  # the big one

        blank, specks = scan_blank.measure(bed(self.dir, "dirty.png", draw), DPI)
        self.assertEqual(blank.specks, len(spots) + 1)
        self.assertGreater(blank.speck_area_pct, 0)
        # 12 px radius at 300 dpi is a hair over 2 mm across.
        self.assertAlmostEqual(blank.largest_speck_mm, 2.0, delta=0.4)
        self.assertEqual(specks[0][0], max(s[0] for s in specks))

    def test_dirt_in_the_outer_sliver_is_not_counted(self) -> None:
        # The first rows of a real scan carry artefacts that move between scans
        # of an untouched bed. Counting them sends someone hunting for dirt that
        # is not on the glass, which is exactly what happened once.
        def draw(image):
            cv2.circle(image, (5, 5), 4, (90, 90, 90), -1)
            cv2.circle(image, (image.shape[1] - 4, 600), 4, (90, 90, 90), -1)

        blank, _ = scan_blank.measure(bed(self.dir, "edge.png", draw), DPI)
        self.assertEqual(blank.specks, 0)

    def test_a_darkened_margin_is_measured_as_falloff(self) -> None:
        # A bed that darkens towards one edge welds prints in that margin
        # together, so the depth of it is the number worth knowing.
        def draw(image):
            for x in range(int(0.3 * DPI)):
                image[:, x] = BED - int(40 * (1 - x / (0.3 * DPI)))

        blank, _ = scan_blank.measure(bed(self.dir, "vignette.png", draw), DPI)
        self.assertGreater(blank.falloff_in["left"], 0.15)
        self.assertAlmostEqual(blank.falloff_in["right"], 0.0, places=2)

    def test_a_stripe_down_the_whole_bed_reads_as_internal_dust(self) -> None:
        # Dirt on the mirror is painted into every row of one column; dirt on
        # the glass is a spot. The two need different remedies.
        def draw(image):
            image[:, 400:404] = BED - 12

        blank, _ = scan_blank.measure(bed(self.dir, "streak.png", draw), DPI)
        self.assertGreaterEqual(blank.streak_columns, 3)

    def test_a_neutral_bed_reports_no_cast(self) -> None:
        blank, _ = scan_blank.measure(bed(self.dir, "neutral.png"), DPI)
        self.assertLess(blank.cast, 0.5)
        self.assertLess(blank.cast_varies, 0.5)

    def test_a_tinted_bed_reports_the_cast_as_even(self) -> None:
        def draw(image):
            image[:, :, 2] = BED - 6  # red down across the whole bed

        blank, _ = scan_blank.measure(bed(self.dir, "tinted.png", draw), DPI)
        self.assertAlmostEqual(blank.cast, 6.0, delta=0.5)
        self.assertLess(blank.cast_varies, 0.5, "an even tint must not look uneven")


if __name__ == "__main__":
    unittest.main()
