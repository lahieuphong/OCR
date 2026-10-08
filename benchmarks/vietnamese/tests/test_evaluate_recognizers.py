"""Known-answer tests for the recognizer metrics and the decision rule."""

import csv
import json
import tempfile
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import bakeoff_common as bakeoff
import evaluate
import evaluate_recognizers as er

MISSING = set("ệựạ")


def score(reference: str, hypothesis: str, cases=()) -> dict:
    return er.score_line(reference, hypothesis, MISSING, list(cases))


class EditDistance(unittest.TestCase):
    def test_known_answers(self):
        self.assertEqual(evaluate.edit_distance("kitten", "sitting"), 3)
        self.assertEqual(evaluate.edit_distance("", "abc"), 3)
        self.assertEqual(evaluate.edit_distance("abc", "abc"), 0)
        self.assertEqual(evaluate.edit_distance("a b c".split(), "a x c d".split()), 2)


class LineScores(unittest.TestCase):
    def test_exact_line(self):
        line = score("Việt Nam", "Việt Nam")
        self.assertEqual((line["char_errors_raw"], line["word_errors_raw"]), (0, 0))
        self.assertEqual((line["exact_raw"], line["exact_nfc"]), (1, 1))
        self.assertEqual((line["missing_char_occurrences"], line["missing_char_correct"]), (1, 1))
        self.assertEqual((line["other_char_occurrences"], line["other_char_correct"]), (7, 7))

    def test_dropped_letter(self):
        # What PP-OCRv6 does with a letter it has no class for.
        line = score("Việt Nam", "Vit Nam")
        self.assertEqual(line["characters_gt"], 8)
        self.assertEqual(line["char_errors_raw"], 1)
        self.assertEqual((line["words_gt"], line["word_errors_raw"]), (2, 1))
        self.assertEqual((line["exact_raw"], line["exact_nfc"]), (0, 0))
        self.assertEqual((line["missing_char_occurrences"], line["missing_char_correct"]), (1, 0))
        self.assertEqual((line["other_char_occurrences"], line["other_char_correct"]), (7, 7))

    def test_substituted_letter(self):
        line = score("sự", "sư")
        self.assertEqual(line["char_errors_raw"], 1)
        self.assertEqual(line["per_missing_character"], {"ự": [1, 0]})

    def test_nfc_only_difference(self):
        reference = "Việt"
        hypothesis = unicodedata.normalize("NFD", reference)
        line = score(reference, hypothesis)
        self.assertGreater(line["char_errors_raw"], 0)
        self.assertEqual(line["char_errors_nfc"], 0)
        self.assertEqual((line["exact_raw"], line["exact_nfc"]), (0, 1))
        # Occurrences are judged on NFC text, so the letter counts as recognised.
        self.assertEqual(line["missing_char_correct"], 1)

    def test_inserted_text_is_an_error_but_not_an_occurrence(self):
        line = score("ạ", "ạ 19")
        self.assertEqual(line["char_errors_raw"], 3)
        self.assertEqual((line["missing_char_occurrences"], line["missing_char_correct"]), (1, 1))
        self.assertEqual(line["other_char_occurrences"], 0)

    def test_hard_case(self):
        right = score("phải thực hiện ngay", "phải thực hiện ngay", cases=["thực hiện"])
        wrong = score("phải thực hiện ngay", "phi thc hin ngay", cases=["thực hiện"])
        self.assertEqual((right["hard_case_occurrences"], right["hard_case_correct"]), (1, 1))
        self.assertEqual((wrong["hard_case_occurrences"], wrong["hard_case_correct"]), (1, 0))


class Aggregation(unittest.TestCase):
    def test_micro_average_weights_by_length(self):
        lines = [score("Việt Nam", "Vit Nam"), score("ab", "ab")]
        summary = er.summarise("x", lines)
        # 1 error over 10 characters, not the mean of 1/8 and 0.
        self.assertAlmostEqual(summary["micro_cer_raw"], 0.1)
        self.assertAlmostEqual(summary["micro_wer_raw"], 1 / 3)
        self.assertAlmostEqual(summary["exact_line_raw"], 0.5)
        self.assertEqual(summary["verified_lines"], 2)

    def test_accuracies(self):
        summary = er.summarise("x", [score("sự việc", "sư việc"), score("lạ", "l")])
        self.assertEqual((summary["missing_char_occurrences"], summary["missing_char_correct"]), (3, 1))
        self.assertAlmostEqual(summary["missing_char_accuracy"], 1 / 3)
        self.assertEqual(summary["other_char_accuracy"], 1.0)

    def test_no_occurrence_gives_no_accuracy(self):
        self.assertIsNone(er.summarise("x", [score("abc", "abc")])["missing_char_accuracy"])

    def test_missing_character_table(self):
        scores = {
            bakeoff.PPOCR: [score("sự việc lạ", "s vic l")],
            bakeoff.VIETOCR: [score("sự việc lạ", "sự việc la")],
        }
        rows = {row["char"]: row for row in er.missing_character_rows(scores, sorted(MISSING))}
        self.assertEqual(rows["ự"]["unicode"], "U+1EF1")
        self.assertEqual(
            [(rows[c]["occurrences"], rows[c]["ppocr_correct"], rows[c]["vietocr_correct"]) for c in "ệựạ"],
            [(1, 0, 1), (1, 0, 1), (1, 0, 0)],
        )
        self.assertEqual(rows["ệ"]["vietocr_accuracy"], "1.000000")
        self.assertEqual(rows["ạ"]["vietocr_accuracy"], "0.000000")


class DecisionRule(unittest.TestCase):
    def scores(self, lines: int, ppocr: str, vietocr: str) -> dict:
        reference = "thực hiện việc lạ"
        return {
            bakeoff.PPOCR: [score(reference, ppocr) for _ in range(lines)],
            bakeoff.VIETOCR: [score(reference, vietocr) for _ in range(lines)],
        }

    def test_too_few_lines(self):
        report = er.decide(self.scores(99, "thc hin vic l", "thực hiện việc lạ"), 100)
        self.assertEqual(len(report), 1)
        self.assertIn("NOT DECIDED", report[0])

    def test_no_lines(self):
        report = er.decide({name: [] for name in er.RECOGNIZERS}, 100)
        self.assertIn("NOT DECIDED", report[0])

    def test_vietocr_clearly_better(self):
        report = er.decide(self.scores(100, "thc hin vic l", "thực hiện việc lạ"), 100)
        self.assertIn("VietOCR recognition", report[-1])

    def test_ppocr_competitive_apart_from_the_missing_letters(self):
        # VietOCR reads the missing letters but garbles the rest of the line.
        report = er.decide(self.scores(100, "thc hin vic l", "xxựx xxệx xxệx xạ"), 100)
        self.assertIn("extended PP-OCRv6 dictionary", report[-1])


class EndToEnd(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.dictionary = self.root / "dict.txt"
        self.dictionary.write_text("".join(c + "\n" for c in "abcdefghijklmnopqrstuvwxyz"), encoding="utf-8")
        self.hard_cases = self.root / "hard_cases.txt"
        self.hard_cases.write_text("thực hiện\n", encoding="utf-8")

    def write(self, verified: str, ppocr_ids=("a", "b"), vietocr_ids=("a", "b")) -> list[str]:
        truth = {"a": "thực hiện", "b": "abc"}
        bakeoff.write_annotation(
            self.root / "manifest.tsv",
            [
                {"id": key, "document": "d", "page": 1, "crop_path": f"{key}.png",
                 "ppocr_prediction": "", "vietocr_prediction": "",
                 "ground_truth": truth[key] if verified == "true" else "", "verified": verified}
                for key in truth
            ],
        )  # fmt: skip
        predictions = {"ppocr": {"a": "thc hin", "b": "abc"}, "vietocr": {"a": "thực hiện", "b": "abd"}}
        for name, ids in (("ppocr", ppocr_ids), ("vietocr", vietocr_ids)):
            bakeoff.write_jsonl(
                self.root / f"{name}.jsonl",
                [{"id": key, "prediction": predictions[name].get(key, ""), "confidence": None, "runtime_ms": 1}
                 for key in ids],
            )  # fmt: skip
        return [
            "--annotation", str(self.root / "manifest.tsv"),
            "--ppocr", str(self.root / "ppocr.jsonl"),
            "--vietocr", str(self.root / "vietocr.jsonl"),
            "--dict", str(self.dictionary),
            "--hard-cases", str(self.hard_cases),
            "--results-dir", str(self.root / "results"),
        ]  # fmt: skip

    def read(self, name: str) -> list[dict]:
        with (self.root / "results" / name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_metrics_files(self):
        self.assertEqual(er.main(self.write("true")), 0)
        metrics = {row["recognizer"]: row for row in self.read("recognizer_metrics.csv")}
        # Ground truth: "thực hiện" (9 characters) + "abc" (3).
        self.assertEqual(metrics["ppocrv6"]["micro_cer_nfc"], f"{2 / 12:.6f}")
        self.assertEqual(metrics["vietocr"]["micro_cer_nfc"], f"{1 / 12:.6f}")
        self.assertEqual(metrics["ppocrv6"]["exact_line_nfc"], "0.500000")
        self.assertEqual(metrics["ppocrv6"]["missing_char_accuracy"], "0.000000")
        self.assertEqual(metrics["vietocr"]["missing_char_accuracy"], "1.000000")
        self.assertEqual(metrics["vietocr"]["hard_case_accuracy"], "1.000000")

        missing = self.read("missing_characters.csv")
        self.assertEqual(tuple(missing[0]), er.MISSING_COLUMNS)
        by_char = {row["char"]: row for row in missing}
        self.assertEqual(
            (by_char["ự"]["occurrences"], by_char["ự"]["ppocr_correct"], by_char["ự"]["vietocr_correct"]),
            ("1", "0", "1"),
        )
        # Letters that never occur keep an empty accuracy instead of a made-up one.
        self.assertEqual((by_char["ỹ"]["occurrences"], by_char["ỹ"]["ppocr_accuracy"]), ("0", ""))

    def test_unverified_rows_are_not_scored(self):
        self.assertEqual(er.main(self.write("false")), 0)
        self.assertFalse((self.root / "results").exists())

    def test_different_id_sets_fail(self):
        with self.assertRaises(SystemExit) as failure:
            er.main(self.write("true", vietocr_ids=("a",)))
        self.assertIn("FAIL", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
