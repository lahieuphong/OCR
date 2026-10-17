"""Crop geometry: exact PaddleX parity at zero padding, padding and masking on synthetic pages."""
import unittest

import numpy as np

from experiments.crop_geometry import geometry
from experiments.crop_geometry.geometry import CONFIGS, Config, crop_line

A0 = CONFIGS[0]


def page(seed: int = 0, height: int = 300, width: int = 400) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


class ZeroPaddingIsPaddleX(unittest.TestCase):
    def test_pixel_identical_to_crop_by_polys(self):
        try:
            from paddlex.inference.pipelines.components import CropByPolys
        except ImportError:
            self.skipTest("PaddleX not installed")
        cropper = CropByPolys(det_box_type="quad")
        image = page()
        polygons = [
            [[20, 30], [220, 30], [220, 58], [20, 58]],          # axis aligned
            [[40, 100], [300, 104], [299, 134], [39, 130]],      # slightly skewed
            [[50.0, 200.5], [180.0, 200.5], [180.0, 221.5], [50.0, 221.5]],  # float corners
            [[330, 20], [350, 20], [350, 90], [330, 90]],        # tall: PaddleX rotates it
        ]
        for polygon in polygons:
            expected = cropper(image, [polygon])[0]
            actual, info = crop_line(image, polygon, [], A0)
            self.assertTrue(np.array_equal(expected, actual), polygon)
        self.assertTrue(crop_line(image, polygons[-1], [], A0)[1]["rotated"])


class Padding(unittest.TestCase):
    def setUp(self):
        self.image = page(1)
        self.polygon = [[60, 120], [260, 120], [260, 150], [60, 150]]

    def test_padding_adds_rows_and_keeps_the_original_pixels(self):
        base, _ = crop_line(self.image, self.polygon, [], A0)
        for pad in (4, 8, 12):
            padded, info = crop_line(self.image, self.polygon, [], Config(f"B{pad}", "B", pad, pad))
            self.assertEqual(padded.shape, (base.shape[0] + 2 * pad, base.shape[1], 3))
            self.assertTrue(np.array_equal(padded[pad:pad + base.shape[0]], base))
            self.assertFalse(info["clipped"])
            self.assertTrue(info["geometry_applied"])

    def test_padding_never_turns_a_short_word_on_its_side(self):
        word = [[100, 100], [116, 100], [116, 109], [100, 109]]
        padded, info = crop_line(self.image, word, [], Config("B12", "B", 12, 12))
        self.assertFalse(info["rotated"])
        self.assertGreater(padded.shape[0], padded.shape[1])  # tall, but still the horizontal word

    def test_vertical_text_keeps_the_baseline_crop(self):
        tall = [[330, 20], [350, 20], [350, 90], [330, 90]]
        base, _ = crop_line(self.image, tall, [], A0)
        padded, info = crop_line(self.image, tall, [], Config("B8", "B", 8, 8))
        self.assertTrue(np.array_equal(base, padded))
        self.assertFalse(info["geometry_applied"])

    def test_padding_is_clipped_at_the_page_edge(self):
        top_line = [[10, 3], [200, 3], [200, 25], [10, 25]]
        padded, info = crop_line(self.image, top_line, [], Config("B12", "B", 12, 12))
        self.assertTrue(info["clipped"])
        self.assertLess(padded.shape[0], 22 + 24)

    def test_pad_for_zoom(self):
        self.assertEqual(geometry.pad_for_zoom(8, 2.0), 8)
        self.assertEqual(geometry.pad_for_zoom(8, 1.0), 4)


class NeighbourMasking(unittest.TestCase):
    def setUp(self):
        self.image = np.full((200, 300, 3), 235, np.uint8)
        self.image[100:120, 50:250] = 20      # target line ink
        self.image[80:92, 50:250] = 30        # line above, inside its own polygon
        self.target = [[50, 98], [250, 98], [250, 122], [50, 122]]
        self.above = [[50, 78], [250, 78], [250, 93], [50, 93]]

    def test_mask_removes_only_neighbour_polygon_pixels(self):
        unmasked, plain = crop_line(self.image, self.target, [self.above], Config("B12", "B", 12, 12))
        masked, info = crop_line(self.image, self.target, [self.above], Config("C12", "C", 12, 12, True))
        self.assertEqual(unmasked.shape, masked.shape)
        self.assertGreater(info["masked_pixels"], 0)
        self.assertEqual(plain["neighbour_pixels_in_band"], info["neighbour_pixels_in_band"])
        self.assertLess(unmasked[:8].min(), 60)      # B keeps the neighbour's ink in the top band
        self.assertGreater(masked[:8].min(), 200)    # C paints it with paper colour
        middle = slice(12 + 4, 12 + 18)
        self.assertTrue(np.array_equal(masked[middle], unmasked[middle]))  # target ink untouched

    def test_without_neighbours_masking_changes_nothing(self):
        b, _ = crop_line(self.image, self.target, [], Config("B8", "B", 8, 8))
        c, info = crop_line(self.image, self.target, [], Config("C8", "C", 8, 8, True))
        self.assertTrue(np.array_equal(b, c))
        self.assertEqual(info["masked_pixels"], 0)

    def test_a_neighbour_overlapping_the_target_never_masks_the_target(self):
        overlapping = [[50, 90], [250, 90], [250, 104], [50, 104]]
        masked, _ = crop_line(self.image, self.target, [overlapping], Config("C4", "C", 4, 4, True))
        base, _ = crop_line(self.image, self.target, [], A0)
        self.assertTrue(np.array_equal(masked[4:4 + base.shape[0]], base))


if __name__ == "__main__":
    unittest.main()
