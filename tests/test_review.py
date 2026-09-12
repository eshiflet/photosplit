"""Checks for the look-at-what-was-written pass."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from photosplit.review import look, review


def write(dir: Path, name: str, image: np.ndarray) -> Path:
    path = dir / name
    cv2.imwrite(str(path), image)
    return path


def photograph(size=(300, 400), seed: int = 3) -> np.ndarray:
    """Something with range in it, as a real crop has.

    Built on a mid tone rather than on black: a canvas of zeros leaves whole
    areas at pure black, which the check flags — correctly — as a crop that has
    lost its shadows, and which no photograph looks like.
    """
    rng = np.random.default_rng(seed)
    base = np.full((size[0], size[1], 3), 120, np.uint8)
    base = np.clip(base + rng.normal(0, 18, base.shape), 8, 247).astype(np.uint8)
    for _ in range(14):
        colour = tuple(int(v) for v in rng.integers(20, 235, 3))
        p1 = (int(rng.integers(0, size[1])), int(rng.integers(0, size[0])))
        p2 = (int(rng.integers(0, size[1])), int(rng.integers(0, size[0])))
        cv2.rectangle(base, p1, p2, colour, -1)
    return base


class LookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-review-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_a_photograph_is_not_flagged(self) -> None:
        _, problems = look(write(self.dir, "good.png", photograph()))
        self.assertEqual(problems, [], f"flagged a normal crop: {problems}")

    def test_a_blank_crop_is_flagged(self) -> None:
        # What a failed detection or an unexposed frame produces.
        flat = np.full((300, 400, 3), 128, np.uint8)
        _, problems = look(write(self.dir, "blank.png", flat))
        self.assertTrue(any("contrast" in p for p in problems), problems)

    def test_a_crop_that_is_nearly_all_holder_is_flagged(self) -> None:
        dark = np.full((300, 400, 3), 6, np.uint8)
        _, problems = look(write(self.dir, "dark.png", dark))
        self.assertTrue(any("dark" in p or "black" in p for p in problems), problems)

    def test_an_empty_slot_is_flagged(self) -> None:
        blown = np.full((300, 400, 3), 254, np.uint8)
        _, problems = look(write(self.dir, "blown.png", blown))
        self.assertTrue(any("bright" in p or "white" in p for p in problems), problems)

    def test_a_crushed_crop_is_flagged(self) -> None:
        image = photograph()
        image[: image.shape[0] // 2] = 0  # half of it lost to pure black
        _, problems = look(write(self.dir, "crushed.png", image))
        self.assertTrue(any("crushed" in p for p in problems), problems)

    def test_sixteen_bit_crops_are_measured_on_the_same_scale(self) -> None:
        deep = photograph().astype(np.uint16) * 257
        facts, problems = look(write(self.dir, "deep.png", deep))
        self.assertLess(facts["mean"], 256, "16-bit was not scaled to 0-255")
        self.assertEqual(problems, [])


class ReviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="photosplit-review2-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_a_fragment_among_its_siblings_is_flagged(self) -> None:
        # The signature of a detection that split one photograph into pieces.
        paths = [
            write(self.dir, f"f{i}.png", photograph(seed=i)) for i in range(4)
        ]
        paths.append(write(self.dir, "runt.png", photograph(size=(60, 70), seed=9)))
        flagged = {f.path.name for f in review(paths)}
        self.assertIn("runt.png", flagged)
        self.assertNotIn("f0.png", flagged)

    def test_siblings_of_a_normal_size_are_left_alone(self) -> None:
        paths = [write(self.dir, f"n{i}.png", photograph(seed=i)) for i in range(4)]
        self.assertEqual(review(paths), [])

    def test_an_unreadable_file_is_a_finding_not_a_crash(self) -> None:
        broken = self.dir / "broken.png"
        broken.write_bytes(b"not a png at all")
        found = review([broken])
        self.assertEqual(len(found), 1)
        self.assertIn("could not be read", found[0].detail)

    def test_two_files_are_too_few_to_call_anything_a_runt(self) -> None:
        # A size comparison needs something to compare against.
        paths = [
            write(self.dir, "big.png", photograph()),
            write(self.dir, "small.png", photograph(size=(60, 70))),
        ]
        self.assertEqual([f.path.name for f in review(paths)], [])


if __name__ == "__main__":
    unittest.main()
