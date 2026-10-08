"""The synthetic text: vocabulary, variety, determinism and the rules it obeys."""

import random
import re
import textwrap
import unicodedata
import unittest
from collections import Counter

import _paths  # noqa: F401
import build_dataset
import dataset_common as dataset
import text_generator
from text_generator import KINDS, MAX_CHARACTERS, Lexicon, TextGenerator, hard_case_pattern, load_hard_cases

from audit_charset import PPOCRV6_DICT, audit, vietnamese_letters

VOCABULARY = build_dataset.recognizer_vocabulary()
LEXICON = Lexicon()


def generator(banned=frozenset()) -> TextGenerator:
    return TextGenerator(LEXICON, VOCABULARY, banned)


class Vocabulary(unittest.TestCase):
    def test_recognizer_vocabulary_holds_every_vietnamese_letter(self):
        self.assertEqual([letter for letter in vietnamese_letters() if letter not in VOCABULARY], [])
        # ... including the 88 the PP-OCRv6 dictionary lacks.
        self.assertEqual([letter for letter in audit(PPOCRV6_DICT)["missing"] if letter not in VOCABULARY], [])

    def test_lexicon_entries_are_nfc_and_encodable(self):
        for entry in LEXICON.entries():
            self.assertTrue(unicodedata.is_normalized("NFC", entry), entry)
            self.assertEqual(set(entry) - set(VOCABULARY), set(), entry)
            self.assertEqual(entry, entry.strip())

    def test_no_entry_is_listed_twice_in_a_section(self):
        for name, entries in LEXICON.sections.items():
            self.assertEqual([entry for entry, count in Counter(entries).items() if count > 1], [], name)

    def test_lexicon_reaches_every_lower_case_letter(self):
        present = {character for entry in LEXICON.entries() for character in entry.lower()}
        self.assertEqual([letter for letter in vietnamese_letters() if letter.islower() and letter not in present], [])

    def test_lexicon_is_vocabulary_not_documents(self):
        # Stock phrases only: nothing as long as a line of a page.
        self.assertLess(max(len(entry) for entry in LEXICON.entries()), 80)


class Lines(unittest.TestCase):
    def test_same_seed_same_line(self):
        first = [generator().line(random.Random(f"s:{index}")) for index in range(50)]
        second = [generator().line(random.Random(f"s:{index}")) for index in range(50)]
        self.assertEqual(first, second)
        self.assertNotEqual(first, [generator().line(random.Random(f"t:{index}")) for index in range(50)])

    def test_every_kind_gives_valid_varied_lines(self):
        make = generator()
        for kind in KINDS:
            texts = [make.line(random.Random(f"{kind}:{index}"), kind).text for index in range(60)]
            self.assertGreater(len(set(texts)), 20, kind)
            for text in texts:
                self.assertTrue(0 < len(text) <= MAX_CHARACTERS, text)
                self.assertEqual(set(text) - set(VOCABULARY), set(), text)
                self.assertTrue(unicodedata.is_normalized("NFC", text))
                self.assertEqual(text, text.strip())
                self.assertNotIn("  ", text)

    def test_a_mix_of_lines_has_what_administrative_text_has(self):
        make = generator()
        texts = [make.line(random.Random(f"mix:{index}")).text for index in range(1500)]
        joined = "\n".join(texts)
        self.assertGreater(len(set(texts)), 1400)
        self.assertGreater(sum(text.isupper() for text in texts), 40)                  # headings in capitals
        self.assertGreater(sum(any(c.isdigit() for c in text) for text in texts), 300)  # numbers
        self.assertGreater(len(re.findall(r"ngày \d{1,2} tháng \d{1,2} năm \d{4}", joined)), 80)   # dates
        self.assertGreater(len(re.findall(r"\d+/\d{4}/[A-ZĐ]+[a-z]*-[A-ZĐ0-9]+", joined)), 40)  # 15/2024/NĐ-CP
        self.assertGreater(len(re.findall(r"\d+/[A-ZĐ]+[a-z]*-[A-ZĐ0-9]+", joined)), 40)           # 893/QĐ-TTg
        for mark in ("Căn cứ", "Điều", "Bộ ", "Ủy ban nhân dân", "%", ";", ":", "(", "@", "./."):
            self.assertIn(mark, joined)
        for phrase in ("triển khai", "quyết định", "nghị định", "hướng dẫn", "Thực hiện"):
            self.assertIn(phrase.lower(), joined.lower())

    def test_banned_texts_are_never_produced(self):
        banned = frozenset({"QUYẾT ĐỊNH", "QUYẾT ĐỊNH:", "Độc lập - Tự do - Hạnh phúc", "Nơi nhận:"})
        make = generator(banned)
        texts = {make.line(random.Random(f"ban:{index}"), kind).text
                 for kind in ("heading", "recipient") for index in range(400)}  # fmt: skip
        self.assertEqual(texts & banned, set())
        # Without the ban the same seeds do produce them: the ban is what removes them.
        free = {generator().line(random.Random(f"ban:{index}"), kind).text
                for kind in ("heading", "recipient") for index in range(400)}  # fmt: skip
        self.assertTrue(free & banned)

    def test_long_lines_are_long_and_whole(self):
        make = generator()
        for index in range(80):
            text = make.line(random.Random(f"long:{index}"), long=True).text
            self.assertGreaterEqual(len(text), text_generator.LONG_MIN_CHARACTERS)
            self.assertLessEqual(len(text), MAX_CHARACTERS)

    def test_a_wrapped_line_is_never_cut_inside_a_word(self):
        make = generator()
        for index in range(40):
            rng = random.Random(f"wrap:{index}")
            paragraph = make.paragraph(rng)
            width = random.Random(f"w:{index}").randint(30, 110)
            line = make.wrapped_line(random.Random(index), paragraph, (width, width))
            wrapped = textwrap.wrap(paragraph, width=width, break_long_words=False, break_on_hyphens=False)
            self.assertIn(line, [*wrapped, ""])
            self.assertEqual(" ".join(wrapped), paragraph)  # wrapping loses nothing


class HardCasesAndCoverage(unittest.TestCase):
    def test_hard_case_file(self):
        cases = load_hard_cases(dataset.HARD_CASES)
        for word in ("chuẩn", "triển", "chuyển", "quyết", "nghị", "nguyễn", "huyện", "hướng", "trưởng",
                     "chính phủ", "ủy ban", "cộng hòa", "xã hội"):  # fmt: skip
            self.assertIn(word, cases)
        self.assertGreater(len(cases), 13)  # plus what the verified evaluation revealed
        self.assertEqual(len(set(cases)), len(cases))
        for case in cases:
            self.assertEqual(set(case) - set(VOCABULARY), set(), case)
            self.assertTrue(unicodedata.is_normalized("NFC", case))

    def test_every_hard_case_can_be_generated_in_a_line(self):
        make = generator()
        for case in load_hard_cases(dataset.HARD_CASES):
            line = make.hard_case_line(random.Random(f"hard:{case}"), case)
            self.assertRegex(line.text, re.compile(hard_case_pattern(case), re.IGNORECASE))

    def test_hard_case_matching_respects_word_boundaries(self):
        self.assertIsNone(re.search(hard_case_pattern("ủy"), "thủy lợi", re.IGNORECASE))
        self.assertIsNotNone(re.search(hard_case_pattern("ủy"), "Ủy ban", re.IGNORECASE))
        self.assertIsNotNone(re.search(hard_case_pattern("@"), "vanthu@moit.gov.vn"))
        self.assertIsNotNone(re.search(hard_case_pattern(".vn"), "moit.gov.vn"))
        self.assertIsNone(re.search(hard_case_pattern(".vn"), "moit.gov.vnx"))

    def test_hard_case_lines_avoid_texts_already_used(self):
        make, used = generator(), set()
        for index in range(12):
            line = make.hard_case_line(random.Random(f"again:{index}"), "cộng hòa", used)
            self.assertNotIn(line.text, used)
            used.add(line.text)

    def test_a_coverage_line_exists_for_every_letter(self):
        make = generator()
        for letter in vietnamese_letters():
            self.assertIn(letter, make.coverage_line(random.Random(f"cov:{letter}"), letter).text)


class SplitTexts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.banned = frozenset(dataset.FrozenLines.load(dataset.BAKEOFF_REGRESSION).texts)
        cls.cases = load_hard_cases(dataset.HARD_CASES)[:6]
        cls.seen: set[str] = set()
        make = generator(cls.banned)
        cls.train = build_dataset.split_texts(make, build_dataset.SplitSpec("train", 11, 150, 40, 2, 4), cls.cases, cls.seen)
        cls.val = build_dataset.split_texts(make, build_dataset.SplitSpec("val", 12, 40, 10, 1, 1), cls.cases, cls.seen)

    def test_every_letter_reaches_its_minimum(self):
        counts = Counter(character for sample in self.train for character in sample["text"])
        self.assertGreaterEqual(min(counts[letter] for letter in vietnamese_letters()), 4)
        counts = Counter(character for sample in self.val for character in sample["text"])
        self.assertGreaterEqual(min(counts[letter] for letter in vietnamese_letters()), 1)

    def test_texts_are_unique_and_validation_shares_none_with_training(self):
        train, val = [s["text"] for s in self.train], [s["text"] for s in self.val]
        self.assertEqual(len(set(train)), len(train))
        self.assertEqual(len(set(val)), len(val))
        self.assertEqual(set(train) & set(val), set())

    def test_no_text_of_the_frozen_regression_set(self):
        self.assertEqual({s["text"] for s in self.train + self.val} & self.banned, set())

    def test_ids_subsets_and_sources(self):
        ids = [s["id"] for s in self.train + self.val]
        self.assertEqual(len(set(ids)), len(ids))
        self.assertEqual(sum(s["subset"] == dataset.LONG_LINE for s in self.train), 40)
        self.assertEqual(sum(s["source_type"] == dataset.HARD_CASE for s in self.train), 12)
        self.assertTrue(all(len(s["text"]) >= 76 for s in self.train if s["subset"] == dataset.LONG_LINE))
        self.assertTrue(all(s["id"].startswith(("syn_", "long_", "hard_", "cov_")) for s in self.train))

    def test_same_specification_same_texts(self):
        again = build_dataset.split_texts(
            generator(self.banned), build_dataset.SplitSpec("train", 11, 150, 40, 2, 4), self.cases, set()
        )
        self.assertEqual(again, self.train)

    def test_validation_seed_differs_from_training_seed(self):
        seeds = [spec.seed for spec in build_dataset.PILOT.values()]
        self.assertEqual(len(set(seeds)), len(seeds))


if __name__ == "__main__":
    unittest.main()
