"""Checks for deciding which way up a photograph goes."""

from __future__ import annotations

import unittest

import cv2
import numpy as np

from photosplit import upright


def flat(size=(400, 300)) -> np.ndarray:
    """A picture with no face in it, however hard you look."""
    rng = np.random.default_rng(4)
    base = np.full((size[0], size[1], 3), 120, np.uint8)
    return np.clip(base + rng.normal(0, 20, base.shape), 0, 255).astype(np.uint8)


class TurnTest(unittest.TestCase):
    def test_turning_is_lossless_and_reversible(self) -> None:
        image = flat()
        for degrees in (90, 180, 270):
            with self.subTest(degrees=degrees):
                there = upright.turn(image, degrees)
                back = upright.turn(there, 360 - degrees)
                self.assertTrue(bool((back == image).all()), "a turn lost something")

    def test_a_quarter_turn_swaps_the_sides(self) -> None:
        image = flat((400, 300))
        turned = upright.turn(image, 90)
        self.assertEqual(turned.shape[:2], (300, 400))

    def test_no_turn_is_the_same_picture(self) -> None:
        image = flat()
        self.assertIs(upright.turn(image, 0), image)


class WhichWayUpTest(unittest.TestCase):
    def test_a_picture_with_no_face_is_left_alone(self) -> None:
        # Most of what this will ever see. Turning it would be a guess.
        degrees, scores = upright.which_way_up(flat())
        self.assertEqual(degrees, 0)
        self.assertEqual(max(scores.values()), 0.0)

    def test_an_empty_image_is_not_a_crash(self) -> None:
        degrees, _ = upright.which_way_up(np.empty((0, 0, 3), np.uint8))
        self.assertEqual(degrees, 0)

    def test_sixteen_bit_is_handled(self) -> None:
        deep = flat().astype(np.uint16) * 257
        degrees, _ = upright.which_way_up(deep)
        self.assertEqual(degrees, 0)

    def test_greyscale_is_handled(self) -> None:
        grey = cv2.cvtColor(flat(), cv2.COLOR_BGR2GRAY)
        degrees, _ = upright.which_way_up(grey)
        self.assertEqual(degrees, 0)

    def test_upright_returns_the_picture_and_the_angle(self) -> None:
        image = flat()
        result, degrees = upright.upright(image)
        self.assertEqual(degrees, 0)
        self.assertTrue(bool((result == image).all()))

    def test_the_model_is_vendored_rather_than_fetched(self) -> None:
        # A scan must not need the network, and a photograph turned the wrong
        # way by a model that failed to load is worse than one left alone.
        self.assertTrue(upright.MODEL.exists(), "the model is not in the package")
        self.assertGreater(upright.MODEL.stat().st_size, 100_000)
        licence = upright.MODEL.parent / "LICENSE.yunet"
        self.assertTrue(licence.exists(), "vendored a model without its licence")
        self.assertIn("MIT", licence.read_text())

    def test_a_missing_model_leaves_photographs_alone(self) -> None:
        real = upright.MODEL
        try:
            upright.MODEL = real.parent / "not-here.onnx"
            image = flat()
            result, degrees = upright.upright(image)
            self.assertEqual(degrees, 0)
            self.assertTrue(bool((result == image).all()))
        finally:
            upright.MODEL = real


if __name__ == "__main__":
    unittest.main()
