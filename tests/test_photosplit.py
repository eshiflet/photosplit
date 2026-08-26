"""End-to-end checks against synthetic scans with known photo placements."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photosplit import extract
from photosplit.cli import main
from photosplit.detect import find_photos
from tests.make_scan import BLEEDING, SEPARATED, TOUCHING, make

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
        found = sorted(
            (round(p.size[0] / DPI, 2), round(p.size[1] / DPI, 2)) for p in photos
        )
        # A print with a white border is measured to its content, not its paper
        # edge, when that border is within a few levels of the lid: see
        # test_white_border_shortfall_is_bounded for the size of that effect.
        plain = sorted((round(w, 2), round(h, 2)) for w, h, _, _, b, _ in SEPARATED if not b)
        plain_found = sorted(f for f in found if any(abs(f[0] - w) < 0.1 for w, _ in plain))
        for (ew, eh), (fw, fh) in zip(plain, plain_found):
            self.assertAlmostEqual(ew, fw, delta=0.1)
            self.assertAlmostEqual(eh, fh, delta=0.1)

    def test_white_border_shortfall_is_bounded(self) -> None:
        """A near-invisible white border costs a little size, and only a little.

        The synthetic border is 252 on a 242 lid — a ten-level step, fainter
        than a real print's paper edge. Detection settles on the content edge
        instead. That is tolerable; what is not tolerable is it drifting worse,
        so the loss is pinned here.
        """
        scan = self.dir / "scan.png"
        make(scan, SEPARATED)
        photos, _ = detect(scan)
        bordered = sorted((round(w, 2), round(h, 2)) for w, h, _, _, b, _ in SEPARATED if b)
        found = sorted((p.size[0] / DPI, p.size[1] / DPI) for p in photos)
        for expected_w, expected_h in bordered:
            match = min(found, key=lambda f: abs(f[0] - expected_w) + abs(f[1] - expected_h))
            self.assertLess(expected_w - match[0], 0.25)
            self.assertLess(expected_h - match[1], 0.25)
            self.assertGreater(match[0], expected_w - 0.25)

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

    def test_finds_photos_that_hang_off_the_edge_of_the_glass(self) -> None:
        # The lid colour cannot be read from a border ring when prints overrun
        # the bed; a real scan of six photos found nothing at all this way.
        scan = self.dir / "bleed.png"
        make(scan, BLEEDING)
        photos, background = detect(scan)
        self.assertEqual(len(photos), len(BLEEDING))
        self.assertGreater(min(background), 200, "lid should read as near-white")

    def test_photos_reaching_the_scan_boundary_are_flagged(self) -> None:
        # The scannable area is often smaller than the glass, so a print that
        # was fully on the platen can still arrive cut off. Whether it actually
        # is cannot be known from the scan; that it reaches the edge can.
        scan = self.dir / "bleed.png"
        make(scan, BLEEDING)
        photos, _ = detect(scan)
        self.assertTrue(all(p.clipped for p in photos))

        tidy = self.dir / "scan.png"
        make(tidy, SEPARATED)
        photos, _ = detect(tidy)
        self.assertFalse(any(p.clipped for p in photos))

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


class ResamplingTest(unittest.TestCase):
    """Cropping must not cost detail that the scanner captured."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))
        self.scan = self.dir / "scan.png"
        make(self.scan, SEPARATED)

    @staticmethod
    def detail(image: np.ndarray) -> float:
        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
        return float(cv2.Laplacian(grey, cv2.CV_32F).var())

    def test_a_square_photo_is_taken_without_resampling(self) -> None:
        # Interpolating onto a fractional centre used to blur every crop, even
        # ones needing no rotation at all: roughly a third of the fine detail.
        bgr = cv2.imread(str(self.scan))
        photos, _ = find_photos(bgr, dpi=DPI)
        straight = [p for p in photos if abs(p.angle) <= 0.05]
        self.assertTrue(straight, "fixture should contain an unrotated photo")

        for photo in straight:
            crop = extract.deskew_crop(bgr, photo)
            x0, y0, x1, y1 = photo.bounds()
            source = bgr[max(0, y0) : y1, max(0, x0) : x1]
            self.assertGreater(
                self.detail(crop),
                self.detail(source) * 0.9,
                "crop is softer than the scan region it came from",
            )

    def test_a_rotated_photo_keeps_most_of_its_detail(self) -> None:
        bgr = cv2.imread(str(self.scan))
        photos, _ = find_photos(bgr, dpi=DPI)
        rotated = [p for p in photos if abs(p.angle) > 0.5]
        self.assertTrue(rotated, "fixture should contain a skewed photo")

        for photo in rotated:
            crop = extract.deskew_crop(bgr, photo)
            x0, y0, x1, y1 = photo.bounds()
            source = bgr[max(0, y0) : y1, max(0, x0) : x1]
            # One interpolation pass is unavoidable when straightening; two is
            # not, and two is what the old crop-then-rotate path cost.
            self.assertGreater(self.detail(crop), self.detail(source) * 0.6)


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
