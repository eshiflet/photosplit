"""Checks for dust removal, against frames with known specks and known detail."""

from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import cv2
import numpy as np

from photosplit import dust

DPI = 2400


def frame(shade: int = 120, size: int = 400) -> np.ndarray:
    """A smooth frame with a little grain, as a negative's sky would be."""
    rng = np.random.default_rng(4)
    base = np.full((size, size, 3), shade, np.float32)
    base += rng.normal(0, 1.5, base.shape)
    return np.clip(base, 0, 255).astype(np.uint8)


def speck(image: np.ndarray, x: int, y: int, radius: int, shade: int = 250) -> None:
    cv2.circle(image, (x, y), radius, (shade, shade, shade), -1)


class FindSpecksTest(unittest.TestCase):
    def test_a_speck_on_a_smooth_frame_is_found(self) -> None:
        image = frame()
        speck(image, 200, 200, 4)
        mask = dust.find_specks(image, DPI)
        self.assertTrue(bool(mask[200, 200]), "missed a speck in plain view")

    def test_grain_alone_is_not_dust(self) -> None:
        # The trap this is built around: on the same film at 600 and at 2400
        # dpi a pixel threshold finds blobs of the same 4 px median area, which
        # is not how a physical object behaves.
        mask = dust.find_specks(frame(), DPI)
        self.assertEqual(int(mask.sum()), 0, "grain was mistaken for dust")

    def test_detail_in_a_busy_neighbourhood_is_left_alone(self) -> None:
        # A lawn full of clover flowers is small bright blobs on a mid tone,
        # and removing them would be deleting the photograph.
        rng = np.random.default_rng(7)
        busy = np.clip(
            np.full((400, 400, 3), 110, np.float32) + rng.normal(0, 26, (400, 400, 3)),
            0, 255,
        ).astype(np.uint8)
        for _ in range(40):
            speck(busy, int(rng.integers(20, 380)), int(rng.integers(20, 380)), 3, 230)
        mask = dust.find_specks(busy, DPI)
        self.assertLess(int(mask.sum()), busy.shape[0] * busy.shape[1] * 0.001)

    def test_a_long_scratch_is_not_treated_as_a_speck(self) -> None:
        image = frame()
        cv2.line(image, (100, 200), (300, 200), (250, 250, 250), 2)
        mask = dust.find_specks(image, DPI)
        self.assertEqual(int(mask[200, 190:210].sum()), 0, "an edge was taken as dust")

    def test_something_far_too_big_is_part_of_the_picture(self) -> None:
        image = frame()
        speck(image, 200, 200, 80)
        mask = dust.find_specks(image, DPI)
        self.assertEqual(int(mask[200, 200]), 0, "removed something picture-sized")

    def test_a_coarse_scan_does_nothing_rather_than_guess(self) -> None:
        image = frame()
        speck(image, 200, 200, 4)
        self.assertTrue(dust.too_coarse(600))
        self.assertEqual(int(dust.find_specks(image, 600).sum()), 0)
        self.assertFalse(dust.too_coarse(2400))


class PreviewTest(unittest.TestCase):
    """Looking before removing, since removing is not reversible in the file."""

    def marked(self, depth=np.uint8):
        image = frame()
        speck(image, 200, 200, 4)
        if depth is np.uint16:
            image = image.astype(np.uint16) * 257
        mask = dust.find_specks(image, DPI)
        return image, mask, dust.mark(image, mask)

    def test_specks_are_ringed_and_left_where_they_are(self) -> None:
        image, mask, shown = self.marked()
        self.assertTrue(mask.any(), "nothing to preview")
        # The speck itself is untouched; only the ring around it is drawn.
        self.assertTrue(bool((shown[mask > 0] == image[mask > 0]).all()))
        self.assertFalse(bool((shown == image).all()), "nothing was drawn")

    def test_the_ring_is_visible_against_the_picture(self) -> None:
        _, _, shown = self.marked()
        reds = shown[..., 2].astype(int) - shown[..., 1].astype(int)
        self.assertGreater(int(reds.max()), 80, "the ring does not stand out")

    def test_preview_works_at_sixteen_bits(self) -> None:
        image, _, shown = self.marked(np.uint16)
        self.assertEqual(shown.dtype, np.uint16)
        self.assertFalse(bool((shown == image).all()))

    def test_nothing_to_show_is_not_a_crash(self) -> None:
        image = frame()
        blank = np.zeros(image.shape[:2], np.uint8)
        self.assertTrue(bool((dust.mark(image, blank) == image).all()))


class DefaultStrengthTest(unittest.TestCase):
    def test_the_default_is_the_cautious_one(self) -> None:
        # The two mistakes do not cost the same. A missed speck is a speck; a
        # highlight taken out of a jumper is gone from the file, and nobody
        # looks at a 2400 dpi frame closely enough to catch it.
        self.assertEqual(dust.DEFAULT_STRENGTH, "light")

    def test_the_default_finds_less_than_the_others(self) -> None:
        image = frame()
        rng = np.random.default_rng(12)
        for _ in range(12):
            speck(image, int(rng.integers(30, 370)), int(rng.integers(30, 370)), 4)
        counts = {
            name: int(dust.find_specks(image, DPI, name).sum())
            for name in ("light", "normal", "strong")
        }
        self.assertLessEqual(counts["light"], counts["normal"])
        self.assertLessEqual(counts["normal"], counts["strong"])


class GlassDustTest(unittest.TestCase):
    """Dirt whose position is known rather than detected."""

    def record(self, specks, dpi=600, measured=None):
        from datetime import datetime

        return {
            "dpi": dpi,
            "measured": measured or datetime.now().isoformat(timespec="seconds"),
            "specks_seen": [
                {"area_px": a, "x_in": x, "y_in": y} for a, x, y in specks
            ],
        }

    def test_a_known_speck_lands_where_the_map_says(self) -> None:
        # 1.0 in across at 600 dpi is 600 px from the scan's origin; a crop
        # taken from (500, 400) puts it at (100, 200) inside the crop.
        mask = dust.known_specks(
            (600, 400), 600, self.record([(30, 1.0, 1.0)]), origin=(500, 400)
        )
        self.assertTrue(bool(mask[200, 100]), "the speck is not where the map put it")
        self.assertLess(int(mask.sum()), 200, "healed far more than one speck")

    def test_a_speck_outside_this_crop_is_ignored(self) -> None:
        mask = dust.known_specks(
            (200, 200), 600, self.record([(30, 5.0, 5.0)]), origin=(0, 0)
        )
        self.assertEqual(int(mask.sum()), 0)

    def test_a_map_taken_at_another_resolution_still_lines_up(self) -> None:
        # Calibration is always 600 dpi; film is scanned at 2400.
        mask = dust.known_specks(
            (3000, 3000), 2400, self.record([(30, 1.0, 1.0)], dpi=600), origin=(0, 0)
        )
        ys, xs = np.nonzero(mask)
        self.assertTrue(xs.size, "nothing placed")
        self.assertAlmostEqual(float(xs.mean()), 2400.0, delta=20)
        self.assertAlmostEqual(float(ys.mean()), 2400.0, delta=20)

    def test_no_map_heals_nothing(self) -> None:
        for empty in (None, {}, {"specks_seen": []}):
            with self.subTest(record=empty):
                self.assertEqual(int(dust.known_specks((80, 80), 600, empty).sum()), 0)

    def test_a_malformed_entry_is_skipped_rather_than_fatal(self) -> None:
        record = {"dpi": 600, "specks_seen": [{"area_px": "x"}, {"x_in": 0.1, "y_in": 0.1, "area_px": 20}]}
        mask = dust.known_specks((200, 200), 600, record)
        self.assertGreater(int(mask.sum()), 0, "the good entry was lost with the bad")

    def test_a_stale_calibration_is_not_used(self) -> None:
        # The map describes the glass as it was. Clean the glass and it becomes
        # a list of places with nothing in them, and healing those is
        # retouching the photograph for no reason.
        import tempfile
        from datetime import datetime, timedelta

        from photosplit.blank import CALIBRATION_JSON
        from photosplit.prefs import Prefs
        import json

        folder = Path(tempfile.mkdtemp(prefix="photosplit-stale-"))
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        old = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        (folder / CALIBRATION_JSON).write_text(json.dumps(self.record([(30, 1.0, 1.0)], measured=old)))

        prefs = Prefs("com.photosplit.tests.stale")
        import photosplit.blank as blank_module

        real = blank_module.calibration_folder
        blank_module.calibration_folder = lambda: folder
        try:
            self.assertIsNone(prefs.glass_dust(), "used a map older than the limit")

            fresh = (datetime.now() - timedelta(days=2)).isoformat(timespec="seconds")
            (folder / CALIBRATION_JSON).write_text(
                json.dumps(self.record([(30, 1.0, 1.0)], measured=fresh))
            )
            self.assertIsNotNone(prefs.glass_dust(), "refused a map from this week")
        finally:
            blank_module.calibration_folder = real


class AvailabilityTest(unittest.TestCase):
    """It is the resolution that decides, not the medium."""

    def test_the_floor_is_the_resolution_not_the_mode(self) -> None:
        from photosplit.prefs import FILM, PRINT, SLIDE, Prefs

        prefs = Prefs("com.photosplit.tests.dust")
        prefs.set("resolution", 600, PRINT)
        self.assertFalse(prefs.dust_available(PRINT))
        prefs.set("resolution", 1200, PRINT)
        self.assertTrue(prefs.dust_available(PRINT), "a fine print scan is workable")
        for mode in (FILM, SLIDE):
            with self.subTest(mode=mode):
                prefs.set("resolution", 2400, mode)
                self.assertTrue(prefs.dust_available(mode))
                prefs.set("resolution", 1200, mode)
                self.assertTrue(prefs.dust_available(mode))

    def test_a_coarse_mode_cannot_turn_it_on_by_accident(self) -> None:
        from photosplit.prefs import PRINT, Prefs

        prefs = Prefs("com.photosplit.tests.dust2")
        prefs.mode = PRINT
        prefs.set("resolution", 600)
        prefs.set("dust", True)
        self.assertFalse(prefs.as_split_options().dust, "ran below the floor")
        prefs.set("resolution", 2400)
        self.assertTrue(prefs.as_split_options().dust)


class HealTest(unittest.TestCase):
    def test_a_speck_is_filled_from_its_surroundings(self) -> None:
        image = frame(shade=120)
        speck(image, 200, 200, 4)
        cleaned, found = dust.remove(image, DPI)
        self.assertGreaterEqual(found, 1)
        self.assertLess(abs(int(cleaned[200, 200].mean()) - 120), 12)

    def test_healing_keeps_sixteen_bit_depth(self) -> None:
        deep = (frame().astype(np.uint16) * 257)
        cv2.circle(deep, (200, 200), 4, (64000, 64000, 64000), -1)
        cleaned, _ = dust.remove(deep, DPI)
        self.assertEqual(cleaned.dtype, np.uint16)
        self.assertLess(int(cleaned[200, 200].mean()), 40000)

    def test_an_empty_mask_returns_the_image_unchanged(self) -> None:
        image = frame()
        self.assertTrue(bool((dust.heal(image, np.zeros(image.shape[:2], np.uint8)) == image).all()))

    def test_nothing_outside_the_mask_moves(self) -> None:
        image = frame()
        speck(image, 200, 200, 4)
        mask = dust.find_specks(image, DPI)
        cleaned = dust.heal(image, mask)
        untouched = mask == 0
        self.assertTrue(bool((cleaned[untouched] == image[untouched]).all()))


if __name__ == "__main__":
    unittest.main()
