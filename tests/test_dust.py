"""Checks for dust removal, against frames with known specks and known detail."""

from __future__ import annotations

import unittest

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
