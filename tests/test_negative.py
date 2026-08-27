"""Checks for turning a scanned negative into a positive."""

from __future__ import annotations

import unittest

import numpy as np

from photosplit import negative

BASE = np.array([112.0, 132.0, 178.0])  # the orange mask, as measured off real film


def negative_of(positive: np.ndarray, base: np.ndarray = BASE) -> np.ndarray:
    """Make the negative a scanner would produce from a known positive."""
    exposure = positive.astype(np.float32) / 255.0
    density = exposure * 1.6  # a plausible range of densities above base
    return (base.reshape(1, 1, 3) * np.power(10.0, -density)).astype(np.uint8)


class InvertTest(unittest.TestCase):
    def test_a_known_positive_comes_back(self) -> None:
        rng = np.random.default_rng(5)
        wanted = rng.integers(10, 245, (64, 48, 3)).astype(np.uint8)
        recovered = negative.invert(negative_of(wanted), BASE)

        # Rank order is what must survive; the absolute levels are stretched to
        # the frame's own range on purpose.
        for channel in range(3):
            a = wanted[..., channel].ravel().astype(float)
            b = recovered[..., channel].ravel().astype(float)
            correlation = float(np.corrcoef(a, b)[0, 1])
            self.assertGreater(correlation, 0.97, f"channel {channel} did not invert")

    def test_the_orange_mask_is_taken_out(self) -> None:
        # A neutral grey scene through an orange mask comes back neutral, which
        # is the whole point of measuring the base rather than assuming one.
        grey = np.full((40, 40, 3), 128, np.uint8)
        recovered = negative.invert(negative_of(grey), BASE).reshape(-1, 3).mean(axis=0)
        self.assertLess(float(np.ptp(recovered)), 12.0)

    def test_it_works_at_sixteen_bits(self) -> None:
        rng = np.random.default_rng(6)
        deep = (rng.random((40, 40, 3)) * 65535).astype(np.uint16)
        out = negative.invert(deep, BASE * 257)
        self.assertEqual(out.dtype, np.uint16)
        self.assertGreater(int(out.max()), 4096, "16-bit output collapsed to nothing")

    def test_an_unusable_base_leaves_the_pixels_alone(self) -> None:
        image = np.full((20, 20, 3), 100, np.uint8)
        for useless in (np.zeros(3), np.array([0.0, 12.0, 30.0])):
            with self.subTest(base=list(useless)):
                self.assertTrue(bool((negative.invert(image, useless) == image).all()))

    def test_an_empty_crop_is_not_a_crash(self) -> None:
        empty = np.empty((0, 0, 3), np.uint8)
        self.assertEqual(negative.invert(empty, BASE).size, 0)

    def test_a_guessed_base_is_in_the_right_region(self) -> None:
        # Only used when a scan holds no rebate to measure.
        scan = negative_of(np.random.default_rng(7).integers(0, 255, (80, 80, 3)).astype(np.uint8))
        guessed = negative.estimate_base(scan)
        self.assertTrue(bool((guessed <= BASE + 6).all()), "guessed above the true base")
        self.assertGreater(float(guessed.max()), 60.0)

    def test_the_display_gamma_opens_the_midtones(self) -> None:
        # Density is linear in log exposure, which is not what a screen wants.
        # Without the gamma at the end the picture comes out dark and flat.
        rng = np.random.default_rng(8)
        scanned = negative_of(rng.integers(0, 255, (64, 64, 3)).astype(np.uint8))
        flat = negative.invert(scanned, BASE, gamma=1.0)
        shown = negative.invert(scanned, BASE, gamma=negative.DISPLAY_GAMMA)
        self.assertGreater(float(shown.mean()), float(flat.mean()) + 20)

    def test_the_ends_of_the_range_are_still_reached(self) -> None:
        # The per-channel stretch should use the full output range rather than
        # leaving a negative looking hazy.
        rng = np.random.default_rng(9)
        scanned = negative_of(rng.integers(0, 255, (64, 64, 3)).astype(np.uint8))
        out = negative.invert(scanned, BASE)
        self.assertLess(int(out.min()), 12)
        self.assertGreater(int(out.max()), 243)


if __name__ == "__main__":
    unittest.main()
