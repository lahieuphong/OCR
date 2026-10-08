"""Fonts are checked for glyphs before use; rendering is mild and reproducible."""

import importlib.util
import random
import unittest
from pathlib import Path

import _paths  # noqa: F401
import build_dataset

HAS_IMAGING = all(importlib.util.find_spec(name) for name in ("cv2", "numpy", "PIL"))
VOCABULARY = build_dataset.recognizer_vocabulary()
SUPPLEMENTAL = Path("/System/Library/Fonts/Supplemental")


@unittest.skipUnless(HAS_IMAGING, "OpenCV, NumPy and Pillow are needed to render")
class Fonts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import fonts

        cls.fonts = fonts
        cls.accepted, cls.rejected = fonts.discover(VOCABULARY)

    def test_names_are_parsed_from_file_names(self):
        describe = self.fonts.describe
        font = describe(Path("Times New Roman Bold Italic.ttf"))
        self.assertEqual((font.family, font.bold, font.italic, font.category), ("Times New Roman", True, True, "serif"))
        self.assertEqual(describe(Path("Arial.ttf")).name, "Arial")
        self.assertEqual(describe(Path("LiberationSerif-Regular.ttf")), None)  # not a known family name
        self.assertEqual(describe(Path("Liberation Serif-Bold.ttf")).bold, True)
        self.assertIsNone(describe(Path("Webdings.ttf")))

    def test_every_accepted_font_draws_every_character(self):
        self.assertTrue(self.accepted, "no usable font on this system")
        for font in self.accepted:
            self.assertEqual(self.fonts.missing_glyphs(font.path, VOCABULARY), [], font.name)

    def test_a_times_like_font_is_available(self):
        self.assertTrue(any(font.category == self.fonts.SERIF for font in self.accepted))

    def test_a_font_without_vietnamese_is_detected(self):
        # Latin-only faces: fine for English, 92 Vietnamese letters missing.
        incomplete = [path for path in (SUPPLEMENTAL / "Arial Narrow.ttf", SUPPLEMENTAL / "Trebuchet MS.ttf")
                      if path.is_file()]  # fmt: skip
        if not incomplete:
            self.skipTest("no Latin-only font to probe on this system")
        for path in incomplete:
            missing = self.fonts.missing_glyphs(path, VOCABULARY)
            self.assertIn("ệ", missing)
            self.assertNotIn("a", missing)
            self.assertIn(path.name, self.rejected)
            self.assertNotIn(path, [font.path for font in self.accepted])

    def test_the_probe_does_not_flag_plain_letters(self):
        font = self.accepted[0]
        self.assertEqual(self.fonts.missing_glyphs(font.path, "aA0;@ ệỹ"), [])
        self.assertEqual(self.fonts.missing_glyphs(font.path, "￿"), ["￿"])


@unittest.skipUnless(HAS_IMAGING, "OpenCV, NumPy and Pillow are needed to render")
class Rendering(unittest.TestCase):
    TEXT = "Căn cứ Nghị định số 15/2024/NĐ-CP ngày 05 tháng 02 năm 2024 của Chính phủ;"

    @classmethod
    def setUpClass(cls):
        import fonts
        import numpy
        import render

        cls.numpy, cls.render = numpy, render
        cls.fonts, _ = fonts.discover(VOCABULARY)

    def test_same_seed_and_sample_give_the_same_pixels(self):
        first = self.render.render(self.TEXT, "legal_basis", self.fonts, 7, "sample_1")
        second = self.render.render(self.TEXT, "legal_basis", self.fonts, 7, "sample_1")
        self.assertTrue(self.numpy.array_equal(first.clean, second.clean))
        self.assertTrue(self.numpy.array_equal(first.augmented, second.augmented))
        self.assertEqual((first.font, first.steps), (second.font, second.steps))

    def test_another_sample_or_seed_gives_another_image(self):
        base = self.render.render(self.TEXT, "legal_basis", self.fonts, 7, "sample_1")
        for seed, sample in ((7, "sample_2"), (8, "sample_1")):
            other = self.render.render(self.TEXT, "legal_basis", self.fonts, seed, sample)
            self.assertFalse(
                base.augmented.shape == other.augmented.shape
                and self.numpy.array_equal(base.augmented, other.augmented)
            )

    def test_seed_depends_on_the_sample_not_on_generation_order(self):
        seeds = [self.render.sample_seed(5, f"s{index}") for index in range(4)]
        self.assertEqual(seeds, [self.render.sample_seed(5, f"s{index}") for index in range(4)][::1])
        self.assertEqual(len(set(seeds)), 4)
        self.assertNotEqual(self.render.sample_seed(5, "s0"), self.render.sample_seed(6, "s0"))

    def test_clean_image_is_black_text_on_white(self):
        clean = self.render.render(self.TEXT, "legal_basis", self.fonts, 3, "clean").clean
        self.assertEqual(clean.ndim, 2)
        self.assertEqual(int(clean.max()), 255)
        self.assertLess(int(clean.min()), 40)
        self.assertGreater((clean > 200).mean(), 0.6)  # mostly paper
        # Cropped to the ink: the outermost rows and columns are margin, a few pixels at most.
        ink = self.numpy.argwhere(clean < 128)
        self.assertLessEqual(int(ink[:, 0].min()), 6)
        self.assertLessEqual(clean.shape[1] - 1 - int(ink[:, 1].max()), 8)

    def test_augmentation_is_mild(self):
        for index in range(40):
            rendered = self.render.render(self.TEXT, "body", self.fonts, 11, f"mild_{index}")
            clean, augmented = rendered.clean, rendered.augmented
            # Same line, roughly the same size: nothing is stretched, bent or cropped away.
            self.assertLess(abs(augmented.shape[1] - clean.shape[1]), 0.05 * clean.shape[1] + 20)
            self.assertLess(abs(augmented.shape[0] - clean.shape[0]), 2 * self.render.MAX_SKEW_PIXELS + 12)
            # Still text on paper: clearly darker ink than background.
            self.assertGreater(float(self.numpy.percentile(augmented, 90)) - float(self.numpy.percentile(augmented, 2)), 60)

    def test_skew_stays_within_its_limits(self):
        clean = self.render.render(self.TEXT, "body", self.fonts, 1, "skew").clean
        for index in range(20):
            turned = self.render.skew(clean, self.numpy.random.default_rng(index))
            self.assertLessEqual(turned.shape[0], clean.shape[0] + 2 * self.render.MAX_SKEW_PIXELS + 12)

    def test_small_text_is_degraded_less(self):
        # The same steps on a 14 px line must leave more of it than on a 40 px line would lose.
        small = self.numpy.full((14, 300), 255, self.numpy.uint8)
        small[4:10, 20:280:6] = 0
        kept = 0
        for index in range(30):
            augmented, steps = self.render.augment(small, self.numpy.random.default_rng(index), allow_thinning=False)
            self.assertNotIn("stroke", steps)  # strokes of small text are never altered
            kept += float(augmented.min()) < 140
        self.assertEqual(kept, 30)

    def test_headings_are_mostly_bold_and_fonts_mostly_times(self):
        rng = random.Random(4)
        chosen = [self.render.choose_font(self.fonts, "QUYẾT ĐỊNH", "heading", rng) for _ in range(300)]
        self.assertGreater(sum(font.bold for font in chosen) / 300, 0.5)
        if any(font.family == "Times New Roman" for font in self.fonts):
            body = [self.render.choose_font(self.fonts, "văn bản", "body", rng) for _ in range(400)]
            self.assertGreater(sum(font.family == "Times New Roman" for font in body) / 400, 0.4)


if __name__ == "__main__":
    unittest.main()
