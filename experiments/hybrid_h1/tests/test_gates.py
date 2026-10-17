"""Unit tests of H1's trust gates (no PDF, no labels)."""
import unittest

import numpy as np

from experiments.hybrid_h1.gates import (
    GATES, assemble, assign_words, covered_words, font_trust, ink_checks, normalized_distance, unicode_problem,
)


def word(x0, y0, x1, y1, text, block=0, line=0, number=0, index=0):
    return (x0, y0, x1, y1, text, block, line, number, index)


class FontTrust(unittest.TestCase):
    def test_rules(self):
        trust = font_trust([
            {"basefont": "ABCDEF+Times-Type0", "type": "Type0", "encoding": "Identity-H", "has_tounicode": True},
            {"basefont": "ABCDEF+NoMap-Type0", "type": "Type0", "encoding": "Identity-H", "has_tounicode": False},
            {"basefont": "Helvetica", "type": "Type1", "encoding": "WinAnsiEncoding", "has_tounicode": False},
            {"basefont": "Custom", "type": "TrueType", "encoding": "custom", "has_tounicode": False},
            {"basefont": "", "type": "Type3", "encoding": "", "has_tounicode": True},
            {"basefont": ".VnTime", "type": "TrueType", "encoding": "WinAnsiEncoding", "has_tounicode": False},
            {"basefont": "VNI-Times", "type": "TrueType", "encoding": "WinAnsiEncoding", "has_tounicode": True},
        ])
        self.assertTrue(trust["Times-Type0"] and trust["Helvetica"])
        for name in ("NoMap-Type0", "Custom", "", ".VnTime", "VNI-Times"):
            self.assertFalse(trust[name], name)

    def test_every_object_of_a_name_must_be_trusted_and_mupdf_truncation_matches(self):
        trust = font_trust([
            {"basefont": "AAAAAA+TimesNewRomanPS-BoldItalicMT", "type": "Type0", "encoding": "Identity-H", "has_tounicode": True},
            {"basefont": "BBBBBB+TimesNewRomanPS-BoldItalicMT", "type": "TrueType", "encoding": "WinAnsiEncoding", "has_tounicode": False},
            {"basefont": "CCCCCC+Arial", "type": "Type0", "encoding": "Identity-H", "has_tounicode": True},
            {"basefont": "DDDDDD+Arial", "type": "Type0", "encoding": "Identity-H", "has_tounicode": False},
        ])
        self.assertTrue(trust["TimesNewRomanPS-BoldItalicMT"] and trust["TimesNewRomanPS-BoldItal"])  # MuPDF keeps 31 chars
        self.assertFalse(trust["Arial"])


class UnicodeProblems(unittest.TestCase):
    def test_problems(self):
        vocabulary = set("Hkyýàáạ ")
        self.assertIsNone(unicode_problem("Hà Nội, ngày 08", vocabulary=None))
        self.assertIsNone(unicode_problem("ký", vocabulary))  # NFC composes the tone mark
        self.assertEqual(unicode_problem("ab�"), "replacement_character")
        self.assertEqual(unicode_problem("a​b"), "control_or_unassigned_character")
        self.assertEqual(unicode_problem("a"), "control_or_unassigned_character")
        self.assertEqual(unicode_problem("́a"), "orphan_combining_mark")
        self.assertEqual(unicode_problem("Мир"), "non_latin_letter")
        self.assertEqual(unicode_problem("“ky”", vocabulary), "out_of_vocabulary_character")


class Geometry(unittest.TestCase):
    region = (0, 0, 100, 10)

    def test_assignment_problems(self):
        inside, problem = assign_words([word(0, 1, 20, 9, "Số:"), word(25, 1, 60, 9, "10427/VPCP")], self.region)
        self.assertEqual((len(inside), problem), (2, None))
        cases = {
            "word_straddles_polygon": [word(0, 1, 20, 9, "a"), word(40, -10, 60, 12, "b")],  # centred inside, 45% inside
            "ambiguous_word_assignment": [word(0, 1, 20, 9, "a"), word(30, 6, 50, 18, "b")],
            "multi_line_text": [word(0, 0, 20, 4, "a"), word(30, 5, 50, 9, "b")],
            "duplicate_text": [word(0, 1, 20, 9, "a"), word(0.2, 1, 20.2, 9, "a")],
            "overlapping_text": [word(0, 1, 20, 9, "a"), word(5, 1, 25, 9, "b")],
        }
        for expected, words in cases.items():
            with self.subTest(expected):
                self.assertEqual(assign_words(words, self.region)[1], expected)

    def test_assemble_reads_left_to_right_and_spaces_only_real_gaps(self):
        words = [word(30, 0, 60, 10, "/VPCP-CN", 1), word(0, 0, 10, 10, "Số:", 0), word(12, 0, 29.8, 10, "10427", 2)]
        self.assertEqual(assemble(words), ("Số: 10427/VPCP-CN", True))
        self.assertEqual(assemble([word(0, 0, 10, 10, "a"), word(12, 0, 20, 10, "b", number=1)]), ("a b", False))

    def test_normalized_distance(self):
        self.assertEqual(normalized_distance("", ""), 0.0)
        self.assertEqual(normalized_distance("example.yn", "example.vn"), 1 / 10)
        self.assertEqual(normalized_distance("abc", "xyz"), 1.0)

    def test_covered_words_follow_display_order(self):
        words = [word(10, 10, 30, 20, "under", index=0), word(10, 40, 30, 50, "over", index=1)]
        log = [("fill-text", (10, 10, 30, 20)), ("fill-image", (0, 0, 100, 25)), ("fill-image", (0, 35, 100, 55)),
               ("fill-text", (10, 40, 30, 50))]
        self.assertEqual(covered_words(words, log), {0})


class Ink(unittest.TestCase):
    def test_blank_words_and_unexplained_ink(self):
        dark = np.zeros((40, 100), dtype=bool)
        dark[10:20, 10:30] = True        # glyphs of word 0
        dark[10:20, 60:70] = True        # ink that no text-layer word explains
        blank, unexplained = ink_checks(dark, [(10, 10, 30, 20), (40, 10, 50, 20)], [3, 3], [(10, 10, 30, 20)], (0, 5, 100, 25))
        self.assertEqual(blank, [1])
        self.assertAlmostEqual(unexplained, 100 / 300)
        self.assertGreater(unexplained, GATES["max_unexplained_ink_share"])
        _, unexplained = ink_checks(dark, [(10, 10, 30, 20)], [3], [(10, 10, 30, 20), (60, 10, 70, 20)], (0, 5, 100, 25))
        self.assertEqual(unexplained, 0.0)


if __name__ == "__main__":
    unittest.main()
