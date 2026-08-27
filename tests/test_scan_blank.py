"""Checks for the empty-bed measurements, against beds with known defects."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from photosplit import blank as scan_blank  # noqa: E402

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
        # unittest will not tidy a mkdtemp for us, and these hold whole
        # synthetic scans: an afternoon of runs left 4 GB in /var/folders.
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

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


class CalibrationTest(unittest.TestCase):
    """Saving a calibration, and what it tells someone who just cleaned."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-cal-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.store = self.dir / "store"

    def measure_bed(self, name: str, spots: int) -> tuple:
        def draw(image):
            for i in range(spots):
                cv2.circle(image, (150 + (i % 5) * 90, 200 + (i // 5) * 90), 5, (90, 90, 90), -1)

        return scan_blank.measure(bed(self.dir, name, draw), DPI)

    def test_a_calibration_round_trips(self) -> None:
        blank, specks = self.measure_bed("one.png", 6)
        scan_blank.save_calibration(self.store, blank, specks, self.dir / "one.png")

        loaded = scan_blank.load_calibration(self.store)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["specks"], blank.specks)
        self.assertIn("measured", loaded)
        self.assertEqual(len(loaded["specks_seen"]), blank.specks)
        self.assertTrue((self.store / scan_blank.CALIBRATION_MAP).exists())

    def test_the_run_before_is_kept_for_comparison(self) -> None:
        first, first_specks = self.measure_bed("first.png", 10)
        scan_blank.save_calibration(self.store, first, first_specks, self.dir / "first.png")
        second, second_specks = self.measure_bed("second.png", 3)
        scan_blank.save_calibration(self.store, second, second_specks, self.dir / "second.png")

        loaded = scan_blank.load_calibration(self.store)
        self.assertEqual(loaded["specks"], second.specks)
        self.assertEqual(loaded["history"][0]["specks"], second.specks)
        self.assertEqual(loaded["history"][1]["specks"], first.specks)

    def test_history_keeps_five_runs_and_stops(self) -> None:
        for run in range(8):
            blank, specks = self.measure_bed(f"run{run}.png", run + 1)
            scan_blank.save_calibration(self.store, blank, specks, self.dir / f"run{run}.png")

        loaded = scan_blank.load_calibration(self.store)
        history = loaded["history"]
        self.assertEqual(len(history), scan_blank.HISTORY_LIMIT)
        # Newest first, and only the summary of each -- a run's own history is
        # never nested inside another, or the file would grow without bound.
        counts = [h["specks"] for h in history]
        self.assertEqual(counts, sorted(counts, reverse=True))
        for entry in history:
            self.assertNotIn("history", entry)
            self.assertNotIn("specks_seen", entry)

    def test_a_record_written_before_history_existed_still_works(self) -> None:
        blank, specks = self.measure_bed("old.png", 4)
        scan_blank.save_calibration(self.store, blank, specks, self.dir / "old.png")
        path = self.store / scan_blank.CALIBRATION_JSON
        stale = json.loads(path.read_text())
        stale.pop("history")
        stale["previous"] = {"measured": "2026-01-01T00:00:00", "specks": 99,
                             "speck_area_pct": 0.9, "largest_speck_mm": 2.0}
        path.write_text(json.dumps(stale))

        newer, newer_specks = self.measure_bed("newer.png", 2)
        scan_blank.save_calibration(self.store, newer, newer_specks, self.dir / "newer.png")
        history = scan_blank.load_calibration(self.store)["history"]
        self.assertEqual([h["specks"] for h in history], [newer.specks, blank.specks, 99])

    def test_the_verdict_shows_the_run_of_recent_counts(self) -> None:
        # One comparison says whether the last clean helped; the run of them
        # says whether the glass is drifting.
        for run, spots in enumerate((12, 9, 6)):
            blank, specks = self.measure_bed(f"trend{run}.png", spots)
            scan_blank.save_calibration(self.store, blank, specks, self.dir / f"trend{run}.png")

        latest, _ = self.measure_bed("trend-now.png", 3)
        lines = scan_blank.verdict(latest, scan_blank.load_calibration(self.store))
        trend = [line for line in lines if "newest first" in line]
        self.assertEqual(len(trend), 1)
        self.assertIn(str(latest.specks), trend[0])

    def test_no_trend_line_until_there_is_a_trend(self) -> None:
        blank, specks = self.measure_bed("only.png", 5)
        scan_blank.save_calibration(self.store, blank, specks, self.dir / "only.png")
        later, _ = self.measure_bed("later.png", 4)
        lines = scan_blank.verdict(later, scan_blank.load_calibration(self.store))
        self.assertFalse(any("newest first" in line for line in lines))

    def test_a_missing_or_broken_calibration_is_not_fatal(self) -> None:
        self.assertIsNone(scan_blank.load_calibration(self.store))
        self.store.mkdir(parents=True)
        (self.store / scan_blank.CALIBRATION_JSON).write_text("{ not json")
        self.assertIsNone(scan_blank.load_calibration(self.store))

    def test_the_verdict_says_which_way_the_glass_went(self) -> None:
        dirty, dirty_specks = self.measure_bed("dirty.png", 12)
        clean, clean_specks = self.measure_bed("clean2.png", 2)

        first = scan_blank.verdict(dirty, None)
        self.assertIn("speck", first[0])
        self.assertTrue(all("last time" not in line for line in first))

        scan_blank.save_calibration(self.store, dirty, dirty_specks, self.dir / "dirty.png")
        improved = scan_blank.verdict(clean, scan_blank.load_calibration(self.store))
        self.assertTrue(any("cleaner than last time" in line for line in improved))

        scan_blank.save_calibration(self.store, clean, clean_specks, self.dir / "clean2.png")
        worse = scan_blank.verdict(dirty, scan_blank.load_calibration(self.store))
        self.assertTrue(any("dirtier than last time" in line for line in worse))

    def test_the_verdict_names_the_margin_to_keep_prints_out_of(self) -> None:
        # The number that matters most after a calibration is where a print may
        # safely be laid, because a vignetted margin welds prints together.
        def draw(image):
            for x in range(int(0.3 * DPI)):
                image[:, x] = BED - int(40 * (1 - x / (0.3 * DPI)))

        blank, _ = scan_blank.measure(bed(self.dir, "vig.png", draw), DPI)
        lines = scan_blank.verdict(blank, None)
        self.assertTrue(any("clear of the left edge" in line for line in lines))

    def test_internal_dust_is_called_out_as_uncleanable(self) -> None:
        def draw(image):
            image[:, 200:400] = BED - 12

        blank, _ = scan_blank.measure(bed(self.dir, "inside.png", draw), DPI)
        lines = scan_blank.verdict(blank, None)
        self.assertTrue(any("inside the scanner" in line for line in lines))
