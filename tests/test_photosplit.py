"""End-to-end checks against synthetic scans with known photo placements."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photosplit.cli import main
from photosplit.detect import find_photos
from tests.make_scan import SEPARATED, TOUCHING, make

DPI = 300


def detect(path: Path):
    bgr = cv2.imread(str(path))
    return find_photos(bgr, dpi=DPI)


class DetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))

    def test_finds_every_separated_photo_at_the_right_size(self) -> None:
        scan = self.dir / "scan.png"
        make(scan, SEPARATED)
        photos, _ = detect(scan)

        self.assertEqual(len(photos), len(SEPARATED))
        expected = sorted((round(w, 2), round(h, 2)) for w, h, *_ in SEPARATED)
        found = sorted(
            (round(p.size[0] / DPI, 2), round(p.size[1] / DPI, 2)) for p in photos
        )
        for (ew, eh), (fw, fh) in zip(expected, found):
            self.assertAlmostEqual(ew, fw, delta=0.1)
            self.assertAlmostEqual(eh, fh, delta=0.1)

    def test_measures_skew(self) -> None:
        scan = self.dir / "scan.png"
        make(scan, SEPARATED)
        photos, _ = detect(scan)
        # find_photos reports the rotation that undoes the skew, hence the sign.
        found = sorted(round(-p.angle, 1) for p in photos)
        self.assertEqual(found, sorted(round(row[5], 1) for row in SEPARATED))

    def test_separates_photos_that_touch(self) -> None:
        scan = self.dir / "tight.png"
        make(scan, TOUCHING)
        photos, _ = detect(scan)
        self.assertEqual(len(photos), len(TOUCHING))

    def test_reading_order_is_top_left_first(self) -> None:
        scan = self.dir / "scan.png"
        make(scan, SEPARATED)
        photos, _ = detect(scan)
        corners = [(round(p.bounds()[0] / DPI, 1), round(p.bounds()[1] / DPI, 1)) for p in photos]
        self.assertEqual(corners, sorted(corners, key=lambda c: (round(c[1] / 2), c[0])))

    def test_blank_scan_yields_nothing(self) -> None:
        blank = np.full((1100, 850, 3), 242, np.uint8)
        cv2.imwrite(str(self.dir / "blank.png"), blank)
        photos, _ = detect(self.dir / "blank.png")
        self.assertEqual(photos, [])

    def test_dust_is_not_a_photo(self) -> None:
        scan = np.full((1100, 850, 3), 242, np.uint8)
        for x in range(50, 800, 60):
            cv2.circle(scan, (x, 500), 4, (60, 60, 60), -1)
        cv2.imwrite(str(self.dir / "dust.png"), scan)
        photos, _ = detect(self.dir / "dust.png")
        self.assertEqual(photos, [])


class CommandLineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))
        self.scan = self.dir / "family.png"
        make(self.scan, SEPARATED)
        self.out = self.dir / "out"

    def test_writes_one_file_per_photo_tagged_with_the_scan_dpi(self) -> None:
        self.assertEqual(main([str(self.scan), "-o", str(self.out)]), 0)
        files = sorted(self.out.glob("family-*.jpg"))
        self.assertEqual([f.name for f in files], [f"family-{i:02d}.jpg" for i in range(1, 5)])
        for f in files:
            self.assertEqual(Image.open(f).info.get("dpi"), (DPI, DPI))

    def test_dry_run_writes_nothing(self) -> None:
        self.assertEqual(main([str(self.scan), "-o", str(self.out), "-n"]), 0)
        self.assertFalse(self.out.exists())

    def test_png_output_and_preview(self) -> None:
        main([str(self.scan), "-o", str(self.out), "-f", "png", "--preview"])
        self.assertEqual(len(list(self.out.glob("family-*.png"))), 4)
        self.assertTrue((self.out / "family-preview.jpg").exists())

    def test_a_folder_of_scans_is_processed_as_a_batch(self) -> None:
        make(self.dir / "second.png", TOUCHING)
        main([str(self.dir), "-o", str(self.out)])
        self.assertEqual(len(list(self.out.glob("*.jpg"))), 7)

    def test_crops_carry_no_scanner_background(self) -> None:
        main([str(self.scan), "-o", str(self.out)])
        for f in sorted(self.out.glob("family-*.jpg")):
            crop = cv2.imread(str(f))
            border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
            lid = (np.abs(border.astype(int) - 242).max(axis=1) < 6).mean()
            self.assertLess(lid, 0.5, f"{f.name} still has a lid-coloured edge")

    def test_missing_input_is_reported_not_raised(self) -> None:
        self.assertEqual(main([str(self.dir / "nope.png")]), 1)


if __name__ == "__main__":
    unittest.main()
