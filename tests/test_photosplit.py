"""End-to-end checks against synthetic scans with known photo placements."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from photosplit import extract
from photosplit.cli import main
from photosplit.detect import find_photos
from photosplit.split import SplitOptions, eight_bit, load_scan, split_scan
from tests.make_scan import BLEEDING, SEPARATED, TOUCHING, make

DPI = 300


def detect(path: Path):
    bgr = cv2.imread(str(path))
    return find_photos(bgr, dpi=DPI)


class DetectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))
        # unittest will not tidy a mkdtemp for us, and these hold whole
        # synthetic scans: an afternoon of runs left 4 GB in /var/folders.
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

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
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
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


class NeutraliseTest(unittest.TestCase):
    """Colour balancing against the lid, which is white by definition."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.scan = self.dir / "scan.png"
        make(self.scan, SEPARATED)

    @staticmethod
    def tint(bgr: np.ndarray, bgr_gain) -> np.ndarray:
        return np.clip(bgr * np.asarray(bgr_gain), 0, 255).astype(np.uint8)

    @staticmethod
    def spread(background: np.ndarray) -> float:
        return float(background.max() - background.min())

    def test_a_tinted_scan_comes_back_neutral(self) -> None:
        # The V500 reads its own white mat at roughly B 244, G 243, R 240:
        # a few levels of blue laid over everything on the glass.
        bgr = cv2.imread(str(self.scan))
        tinted = self.tint(bgr, (1.0, 0.985, 0.955))

        _, before = find_photos(tinted, dpi=DPI)
        fixed = extract.neutralise(tinted, before)
        _, after = find_photos(fixed, dpi=DPI)

        self.assertGreater(self.spread(before), 6.0, "fixture should be visibly tinted")
        self.assertLess(self.spread(after), 1.5)

    def test_a_neutral_scan_is_left_where_it_is(self) -> None:
        bgr = cv2.imread(str(self.scan))
        _, background = find_photos(bgr, dpi=DPI)
        fixed = extract.neutralise(bgr, background)
        # The fixture's lid is already grey, so there is nothing to take out.
        self.assertLess(float(np.abs(fixed.astype(int) - bgr.astype(int)).mean()), 1.0)

    def test_correcting_never_darkens_the_scan(self) -> None:
        # Scaling down to the dimmest channel would balance just as well and
        # cost brightness for nothing. Every gain should be at or above 1.
        bgr = cv2.imread(str(self.scan))
        tinted = self.tint(bgr, (1.0, 0.985, 0.955))
        _, background = find_photos(tinted, dpi=DPI)
        fixed = extract.neutralise(tinted, background)
        self.assertTrue(bool((fixed >= tinted).all()))

    def test_an_unusable_reference_leaves_the_pixels_alone(self) -> None:
        # A scan with no lid in it at all must not be silently mangled.
        bgr = cv2.imread(str(self.scan))
        for useless in (np.zeros(3), np.array([0.0, 12.0, 30.0])):
            with self.subTest(background=list(useless)):
                self.assertTrue(bool((extract.neutralise(bgr, useless) == bgr).all()))

    def test_the_flag_balances_what_gets_written(self) -> None:
        bgr = cv2.imread(str(self.scan))
        tinted_scan = self.dir / "tinted.png"
        cv2.imwrite(str(tinted_scan), self.tint(bgr, (1.0, 0.985, 0.955)))
        out = self.dir / "out"

        self.assertEqual(main([str(tinted_scan), "-o", str(out), "--neutralise"]), 0)
        written = sorted(out.glob("tinted-*.jpg"))
        self.assertTrue(written)

        plain = self.dir / "plain"
        main([str(tinted_scan), "-o", str(plain)])
        for balanced, untouched in zip(written, sorted(plain.glob("tinted-*.jpg"))):
            a = cv2.imread(str(balanced)).reshape(-1, 3).mean(axis=0)
            b = cv2.imread(str(untouched)).reshape(-1, 3).mean(axis=0)
            # Red was the channel held down, so it is the one that comes back.
            self.assertGreater(a[2], b[2])


class NoteTest(unittest.TestCase):
    """Free text written into the files, since nobody remembers a roll later."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-note-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.crop = (np.random.default_rng(2).random((40, 60, 3)) * 255).astype(np.uint8)

    def read_back(self, path: Path):
        with Image.open(path) as image:
            return dict(getattr(image, "text", {}))

    def test_a_note_reaches_the_file(self) -> None:
        path = self.dir / "n.png"
        extract.save(self.crop, path, 600, note="Kodak T-MAX 400, back garden 1994")
        self.assertEqual(
            self.read_back(path).get("Description"), "Kodak T-MAX 400, back garden 1994"
        )

    def test_a_note_survives_sixteen_bit(self) -> None:
        deep = (self.crop.astype(np.uint16) * 257)
        path = self.dir / "deep.png"
        extract.save(deep, path, 600, note="TMY, f/8")
        self.assertEqual(self.read_back(path).get("Description"), "TMY, f/8")
        self.assertEqual(cv2.imread(str(path), cv2.IMREAD_UNCHANGED).dtype, np.uint16)

    def test_a_note_does_not_disturb_the_resolution(self) -> None:
        path = self.dir / "both.png"
        extract.save(self.crop, path, 600, note="something")
        with Image.open(path) as image:
            self.assertAlmostEqual(image.info["dpi"][0], 600, delta=0.01)

    def test_no_note_writes_no_chunk(self) -> None:
        path = self.dir / "plain.png"
        extract.save(self.crop, path, 600)
        self.assertNotIn("Description", self.read_back(path))

    def test_text_outside_latin1_is_kept_rather_than_mangled(self) -> None:
        path = self.dir / "wide.png"
        extract.save(self.crop, path, 600, note="Ilford HP5 — Kraków, 1994 ☂")
        with Image.open(path) as image:
            written = dict(getattr(image, "text", {}))
        self.assertIn("Kraków", written.get("Description", ""))

    def test_the_note_reaches_every_file_a_split_writes(self) -> None:
        scan = self.dir / "scan.png"
        make(scan, SEPARATED)
        result = split_scan(
            scan,
            SplitOptions(
                output_dir=self.dir / "out", fmt="png", dpi_override=DPI,
                note="roll 12, Kodak Gold 200",
            ),
        )
        self.assertTrue(result.written)
        for path in result.written:
            with self.subTest(path=path.name):
                self.assertEqual(
                    self.read_back(path).get("Description"), "roll 12, Kodak Gold 200"
                )


class HolderTrimTest(unittest.TestCase):
    """A mount is thick, and its edge shadows the picture it surrounds."""

    @staticmethod
    def mounted(ramp: int = 10, picture: int = 120, floor: int = 4) -> np.ndarray:
        """A crop as it comes off a slide: shadow ramping up into the picture."""
        crop = np.full((200, 160, 3), picture, np.uint8)
        for step in range(ramp):
            level = int(floor + (picture - floor) * step / ramp)
            crop[step, :] = level
            crop[-1 - step, :] = level
            crop[:, step] = level
            crop[:, -1 - step] = level
        return crop

    def test_the_shadow_of_a_mount_is_taken_off(self) -> None:
        crop = self.mounted(ramp=10)
        trimmed = extract.trim_background(crop, np.array([4.0, 4.0, 4.0]), DPI)
        self.assertLess(trimmed.shape[0], crop.shape[0])
        edge = np.concatenate(
            [trimmed[0], trimmed[-1], trimmed[:, 0], trimmed[:, -1]]
        )
        self.assertGreater(float(edge.mean()), 60.0, "shadow still on the edge")

    def test_a_white_border_on_a_lid_is_still_kept(self) -> None:
        # The reason the shadow trim only runs against a dark background: on a
        # lid, background-coloured edge is often the print's own white border,
        # and taking it would be silently cropping the photograph.
        lid = 242
        crop = np.full((200, 160, 3), 90, np.uint8)
        border = 16
        crop[:border], crop[-border:] = 250, 250
        crop[:, :border], crop[:, -border:] = 250, 250

        trimmed = extract.trim_background(crop, np.array([float(lid)] * 3), DPI)

        # The conservative trim takes about a millimetre off each side and no
        # more, so most of the border is still there. What must not happen is
        # the shadow trim running and taking the lot.
        millimetre = int(round(0.02 * DPI))
        self.assertGreaterEqual(trimmed.shape[1], crop.shape[1] - 2 * millimetre)
        edge = np.concatenate(
            [trimmed[0], trimmed[-1], trimmed[:, 0], trimmed[:, -1]]
        )
        self.assertGreater(float(edge.mean()), 200.0, "the white border was cropped")

    def test_a_dark_photograph_is_not_eaten(self) -> None:
        # The picture level is measured from the middle rather than assumed, so
        # a genuinely dark frame keeps its edges.
        crop = self.mounted(ramp=4, picture=30)
        trimmed = extract.trim_background(crop, np.array([4.0, 4.0, 4.0]), DPI)
        self.assertGreater(trimmed.shape[0], crop.shape[0] * 0.8)
        self.assertGreater(trimmed.size, 0)

    def test_a_crop_that_is_all_shadow_survives(self) -> None:
        flat = np.full((60, 60, 3), 6, np.uint8)
        trimmed = extract.trim_background(flat, np.array([4.0, 4.0, 4.0]), DPI)
        self.assertGreater(trimmed.size, 0, "trimmed a crop away to nothing")


class SixteenBitTest(unittest.TestCase):
    """A deeper scan has to stay deeper all the way to the file.

    Pillow cannot write 16-bit colour at all, so the old path silently
    truncated to 8 -- which is exactly the range an inverted negative needs.
    """

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-16-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.eight = self.dir / "eight.png"
        make(self.eight, SEPARATED)
        self.deep = self.dir / "deep.tif"
        cv2.imwrite(
            str(self.deep),
            cv2.imread(str(self.eight)).astype(np.uint16) * 257,
            [cv2.IMWRITE_TIFF_XDPI, DPI, cv2.IMWRITE_TIFF_YDPI, DPI],
        )

    def test_a_deep_scan_is_read_at_its_own_depth(self) -> None:
        kept, _ = load_scan(self.deep, DPI, keep_depth=True)
        self.assertEqual(kept.dtype, np.uint16)
        # And flattened for anything that measures in levels out of 255.
        flat, _ = load_scan(self.deep, DPI)
        self.assertEqual(flat.dtype, np.uint8)

    def test_crops_from_a_deep_scan_are_deep(self) -> None:
        result = split_scan(
            self.deep,
            SplitOptions(output_dir=self.dir / "out", fmt="png", dpi_override=DPI),
        )
        self.assertEqual(result.count, len(SEPARATED))
        for path in result.written:
            written = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            self.assertEqual(written.dtype, np.uint16, f"{path.name} lost its depth")

    def test_a_deep_crop_still_carries_its_resolution(self) -> None:
        # PNG keeps resolution in whole pixels per metre, so it comes back a
        # hair off a round number; that is the format, not a mistake.
        crop = (np.random.default_rng(3).random((40, 60, 3)) * 65535).astype(np.uint16)
        for suffix in (".png", ".tif"):
            with self.subTest(suffix=suffix):
                path = self.dir / f"deep{suffix}"
                extract.save(crop, path, 600)
                self.assertAlmostEqual(Image.open(path).info["dpi"][0], 600, delta=0.01)
                back = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                self.assertEqual(back.dtype, np.uint16)
                self.assertTrue(bool((back == crop).all()), "not written losslessly")

    def test_a_deep_crop_asked_for_as_jpeg_is_rounded_not_refused(self) -> None:
        crop = (np.random.default_rng(4).random((40, 60, 3)) * 65535).astype(np.uint16)
        path = self.dir / "deep.jpg"
        extract.save(crop, path, 600)
        self.assertEqual(cv2.imread(str(path), cv2.IMREAD_UNCHANGED).dtype, np.uint8)

    def test_eight_bit_scans_are_untouched_by_any_of_this(self) -> None:
        result = split_scan(
            self.eight,
            SplitOptions(output_dir=self.dir / "shallow", fmt="png", dpi_override=DPI),
        )
        self.assertEqual(result.count, len(SEPARATED))
        for path in result.written:
            self.assertEqual(cv2.imread(str(path), cv2.IMREAD_UNCHANGED).dtype, np.uint8)

    def test_trimming_and_balancing_work_at_either_depth(self) -> None:
        for scan in (self.eight, self.deep):
            with self.subTest(scan=scan.name):
                bgr, _ = load_scan(scan, DPI, keep_depth=True)
                view = eight_bit(bgr)
                photos, background = find_photos(view, dpi=DPI)
                self.assertTrue(photos)

                balanced = extract.neutralise(bgr, background)
                self.assertEqual(balanced.dtype, bgr.dtype)

                crop = extract.deskew_crop(bgr, photos[0])
                trimmed = extract.trim_background(crop, background, DPI)
                self.assertEqual(trimmed.dtype, bgr.dtype)
                self.assertLessEqual(trimmed.shape[0], crop.shape[0])
                self.assertGreater(trimmed.size, 0)


class CommandLineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
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
