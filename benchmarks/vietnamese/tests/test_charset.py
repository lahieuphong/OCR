"""The charset audit and the extended dictionary built from it."""

import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import audit_charset
import build_extended_dict

# Letters the task statement names; each must be reported if the dictionary lacks it.
NAMED_LETTERS = "ảạểếệộớởợủựỵ"


class ReferenceAlphabet(unittest.TestCase):
    def setUp(self):
        self.letters = audit_charset.vietnamese_letters()

    def test_size(self):
        # 12 vowels x 6 tones + 17 consonants, in two cases.
        self.assertEqual(len(self.letters), (12 * 6 + 17) * 2)
        self.assertEqual(len(set(self.letters)), len(self.letters))

    def test_every_letter_is_one_nfc_code_point(self):
        for letter in self.letters:
            self.assertEqual(len(letter), 1)
            self.assertEqual(unicodedata.normalize("NFC", letter), letter)

    def test_accented_letters(self):
        accented = [letter for letter in self.letters if audit_charset.has_diacritic(letter)]
        self.assertEqual(len(accented), 134)
        self.assertIn("đ", accented)
        self.assertNotIn("a", accented)


class DictionaryParsing(unittest.TestCase):
    def write(self, data: bytes) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "dict.txt"
        path.write_bytes(data)
        return path

    def test_whitespace_entries_survive(self):
        path = self.write("a\n　\n \nb\r\n".encode("utf-8"))
        self.assertEqual(audit_charset.read_dictionary(path), ["a", "　", " ", "b"])

    def test_missing_is_computed_from_the_dictionary(self):
        present = [letter for letter in audit_charset.vietnamese_letters() if letter not in "ạỹ"]
        path = self.write("".join(letter + "\n" for letter in present).encode("utf-8"))
        self.assertEqual(audit_charset.audit(path)["missing"], ["ạ", "ỹ"])

    def test_decomposed_entries_do_not_count(self):
        # "a" followed by a combining dot is not the letter U+1EA1.
        path = self.write("a\ṇ\n".encode("utf-8"))
        result = audit_charset.audit(path)
        self.assertIn("ạ", result["missing"])
        self.assertEqual(result["combining_marks_present"], ["̣"])


class VendoredDictionary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = audit_charset.audit(audit_charset.PPOCRV6_DICT)

    def test_missing_count(self):
        self.assertEqual(len(self.result["missing"]), 88)

    def test_missing_are_exactly_the_reference_letters_without_an_entry(self):
        entries = set(self.result["dictionary"])
        expected = {letter for letter in self.result["reference"] if letter not in entries}
        self.assertEqual(set(self.result["missing"]), expected)
        self.assertEqual(self.result["missing"], sorted(expected))

    def test_named_letters(self):
        entries = set(self.result["dictionary"])
        for letter in NAMED_LETTERS:
            with self.subTest(letter=letter):
                self.assertNotIn(letter, entries)
                self.assertIn(letter, self.result["missing"])

    def test_letters_present_are_not_reported(self):
        # U+1ED3 and U+1EA0 are the two Latin Extended Additional letters it has.
        for letter in "ồẠàđư":
            self.assertNotIn(letter, self.result["missing"])

    def test_no_combining_marks(self):
        self.assertEqual(self.result["combining_marks_present"], [])


class ExtendedDictionary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = audit_charset.read_dictionary(audit_charset.PPOCRV6_DICT)
        cls.extended = audit_charset.read_dictionary(build_extended_dict.EXTENDED_DICT)
        cls.missing = audit_charset.audit(audit_charset.PPOCRV6_DICT)["missing"]

    def test_every_original_index_is_preserved(self):
        for index, entry in enumerate(self.original):
            if self.extended[index] != entry:
                self.fail(f"entry {index} changed: {entry!r} -> {self.extended[index]!r}")

    def test_length(self):
        self.assertEqual(len(self.extended), len(self.original) + len(self.missing))
        self.assertEqual(len(self.extended), len(self.original) + 88)

    def test_original_bytes_are_an_exact_prefix(self):
        original = audit_charset.PPOCRV6_DICT.read_bytes()
        extended = build_extended_dict.EXTENDED_DICT.read_bytes()
        self.assertTrue(extended.startswith(original))

    def test_appended_entries_are_the_missing_letters(self):
        self.assertEqual(self.extended[len(self.original):], self.missing)

    def test_no_duplicate_entries(self):
        self.assertEqual(len(set(self.extended)), len(self.extended))

    def test_extended_dictionary_has_no_missing_letter(self):
        self.assertEqual(audit_charset.audit(build_extended_dict.EXTENDED_DICT)["missing"], [])

    def test_file_on_disk_is_what_the_builder_produces(self):
        self.assertEqual(
            build_extended_dict.EXTENDED_DICT.read_bytes(),
            build_extended_dict.build(audit_charset.PPOCRV6_DICT),
        )

    def test_it_lives_outside_the_vendored_tree(self):
        self.assertNotIn(
            build_extended_dict.VENDOR_DIR.resolve(), build_extended_dict.EXTENDED_DICT.resolve().parents
        )

    def test_builder_rejects_a_dictionary_without_final_newline(self):
        with self.assertRaises(ValueError):
            build_extended_dict.extended_dictionary_bytes(b"a\nb", ["c"])

    def test_builder_refuses_to_write_into_the_vendored_tree(self):
        target = build_extended_dict.VENDOR_DIR / "ppocr" / "utils" / "dict" / "should_not_exist.txt"
        with self.assertRaises(SystemExit):
            build_extended_dict.main(["--output", str(target)])
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
