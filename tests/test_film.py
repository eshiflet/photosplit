"""Checks for splitting a strip of film, against strips with known frames."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from photosplit.film import find_frames
from photosplit.split import SplitOptions, split_scan

DPI = 300
HOLDER = 8  # the opaque holder the film sits in
BASE = 143  # unexposed film base, the brightest thing on the film itself
EMPTY = 253  # a slot with no film in it at all


def strip(
    path: Path,
    frames: int = 4,
    flat_first: bool = True,
    empty_tail_in: float = 3.0,
    dpi: int = DPI,
) -> Path:
    """A synthetic filmstrip: frames, rebate lines between them, empty tail."""
    height_in, width_in = 9.33, 2.70
    canvas = np.full((int(height_in * dpi), int(width_in * dpi), 3), HOLDER, np.uint8)
    rng = np.random.default_rng(11)

    left, right = int(0.9 * dpi), int(1.9 * dpi)
    frame_h, gap_h = int(1.42 * dpi), int(0.06 * dpi)
    y = int(0.36 * dpi)
    for index in range(frames):
        block = canvas[y : y + frame_h, left:right]
        if index == 0 and flat_first:
            # The trap: a nearly empty sky is flatter than the gaps beside it,
            # so anything keying on texture alone reads it as a rebate line.
            block[:] = np.clip(84 + rng.normal(0, 1.2, block.shape), 0, 255).astype(np.uint8)
        else:
            block[:] = rng.integers(50, 130, block.shape, dtype=np.uint8)
            cv2.circle(block, (block.shape[1] // 2, block.shape[0] // 2), dpi // 4, (200, 180, 160), -1)
        y += frame_h
        if index < frames - 1:
            canvas[y : y + gap_h, left:right] = BASE
            y += gap_h

    if empty_tail_in > 0:
        canvas[y : y + int(empty_tail_in * dpi), left:right] = EMPTY

    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)
    return path


class FilmStripTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-film-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_every_frame_on_the_strip_is_found(self) -> None:
        scan = cv2.imread(str(strip(self.dir / "s.png")))
        frames, _ = find_frames(scan, DPI)
        self.assertEqual(len(frames), 4)
        for frame in frames:
            self.assertAlmostEqual(frame.size[1] / DPI, 1.42, delta=0.08)
            self.assertAlmostEqual(frame.size[0] / DPI, 1.00, delta=0.08)

    def test_a_flat_frame_is_not_mistaken_for_a_rebate_line(self) -> None:
        # The whole reason this does not key on texture. Measured on real film:
        # the first frame of the strip was an empty sky, flatter than the gaps.
        scan = cv2.imread(str(strip(self.dir / "flat.png", flat_first=True)))
        frames, _ = find_frames(scan, DPI)
        self.assertEqual(len(frames), 4, "the flat frame was eaten as a gap")
        tops = sorted(f.center[1] - f.size[1] / 2 for f in frames)
        self.assertLess(tops[0] / DPI, 0.5, "the first frame is missing")

    def test_an_empty_slot_is_not_a_frame(self) -> None:
        scan = cv2.imread(str(strip(self.dir / "tail.png", frames=2, empty_tail_in=5.0)))
        frames, _ = find_frames(scan, DPI)
        self.assertEqual(len(frames), 2)
        for frame in frames:
            self.assertLess(frame.size[1] / DPI, 2.0, "swallowed the empty slot")

    def test_a_full_strip_with_no_empty_slot_still_works(self) -> None:
        scan = cv2.imread(str(strip(self.dir / "full.png", frames=5, empty_tail_in=0.0)))
        frames, _ = find_frames(scan, DPI)
        self.assertEqual(len(frames), 5)

    def test_a_grainy_film_still_splits(self) -> None:
        # A rebate line is only flat relative to the film it is on. Six levels
        # of absolute flatness fits fine colour film and fails TMAX 400 at 2400
        # dpi, whose rebate measured 7.4 while its frames ran 15 to 28 — the
        # whole strip came back as one frame.
        path = self.dir / "grainy.png"
        strip(path, frames=4)
        image = cv2.imread(str(path))
        rng = np.random.default_rng(21)
        left, right = int(0.9 * DPI), int(1.9 * DPI)
        band = image[:, left:right].astype(np.int16)
        band += rng.normal(0, 9, band.shape).astype(np.int16)
        image[:, left:right] = np.clip(band, 0, 255).astype(np.uint8)
        cv2.imwrite(str(path), image)

        frames, _ = find_frames(cv2.imread(str(path)), DPI)
        self.assertEqual(len(frames), 4, "grain swallowed the gaps between frames")

    def test_the_holder_is_what_frames_are_trimmed_against(self) -> None:
        # Not a lid colour: a frame is cut out of an opaque black holder.
        scan = cv2.imread(str(strip(self.dir / "bg.png")))
        _, background = find_frames(scan, DPI)
        self.assertLess(float(np.max(background)), 40)

    def test_a_scan_with_no_film_in_it_finds_nothing(self) -> None:
        blank = np.full((int(9.33 * DPI), int(2.70 * DPI), 3), HOLDER, np.uint8)
        path = self.dir / "blank.png"
        cv2.imwrite(str(path), blank)
        frames, _ = find_frames(cv2.imread(str(path)), DPI)
        self.assertEqual(frames, [])

    def test_the_strip_option_writes_one_file_per_frame(self) -> None:
        scan = strip(self.dir / "run.png")
        result = split_scan(
            scan,
            SplitOptions(
                output_dir=self.dir / "out", fmt="png", dpi_override=DPI,
                min_size=0.5, strip=True,
            ),
        )
        self.assertEqual(result.count, 4)
        self.assertEqual(len(list((self.dir / "out").glob("run-*.png"))), 4)

    def test_without_the_strip_option_the_frames_run_together(self) -> None:
        # Why the option exists: the print detector sees one ribbon, not four
        # frames, because the frames touch.
        scan = strip(self.dir / "same.png")
        result = split_scan(
            scan,
            SplitOptions(
                output_dir=self.dir / "prints", fmt="png", dpi_override=DPI,
                min_size=0.5, strip=False,
            ),
            write=False,
        )
        self.assertLess(result.count, 4)


if __name__ == "__main__":
    unittest.main()
