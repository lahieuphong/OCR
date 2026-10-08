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


class EditOperations(unittest.TestCase):
    def test_types_add_up_to_the_edit_distance(self):
        for reference, hypothesis, expected in (
            ("Việt Nam", "Vit Nam", (0, 1, 0)),
            ("sự", "sư", (1, 0, 0)),
            ("được", "được tháng 19", (0, 0, 9)),
            ("abc", "abc", (0, 0, 0)),
        ):
            line = score(reference, hypothesis)
            self.assertEqual((line["substitutions"], line["deletions"], line["insertions"]), expected, hypothesis)
            self.assertEqual(sum(expected), line["char_errors_nfc"])

    def test_groups_by_how_a_line_was_verified(self):
        scores = {
            bakeoff.PPOCR: [score("Việt Nam", "Vit Nam"), score("abcd", "abcd")],
            bakeoff.VIETOCR: [score("Việt Nam", "Việt Nam"), score("abcd", "ab")],
        }
        rows = er.group_rows(scores, ["vietocr_accepted", "typed"], ["typed", "vietocr_accepted"], "ground_truth_source")
        by_key = {(row["ground_truth_source"], row["recognizer"]): row for row in rows}
        # A recognizer is exact on the lines accepted from it; the typed lines say more.
        self.assertEqual(by_key[("vietocr_accepted", bakeoff.VIETOCR)]["exact_line_nfc"], 1.0)
        self.assertAlmostEqual(by_key[("typed", bakeoff.VIETOCR)]["micro_cer_nfc"], 0.5)
        self.assertEqual(by_key[("typed", bakeoff.PPOCR)]["micro_cer_nfc"], 0)


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


class EdgeInsertions(unittest.TestCase):
    def test_clear_suffix_and_prefix(self):
        self.assertEqual(er.edge_insertion("số 64 được", "số 64 được tháng 19"), {"prefix": "", "suffix": " tháng 19"})
        self.assertEqual(er.edge_insertion("truyền thông", "Số 19 truyền thông"), {"prefix": "Số 19 ", "suffix": ""})
        # Two stray characters are not reported: only unmistakable insertions are.
        self.assertEqual(er.edge_insertion("truyền thông", "19 truyền thông"), {"prefix": "", "suffix": ""})
        both = er.edge_insertion("quản lý nhà nước", "Thành quản lý nhà nước trung")
        self.assertEqual((both["prefix"], both["suffix"]), ("Thành ", " trung"))

    def test_ordinary_errors_are_not_insertions(self):
        for reference, hypothesis in (
            ("Việt Nam", "Việt Nam"),
            ("Việt Nam", "Vit Nam"),      # dropped letter
            ("Việt Nam", "Việt Nam."),    # one extra character is below the threshold
            ("Việt Nam", "Việt Nan"),     # wrong last letter: a substitution
            ("Việt Nam", "Việt"),         # truncated
        ):
            self.assertEqual(er.edge_insertion(reference, hypothesis), {"prefix": "", "suffix": ""}, hypothesis)

    def test_unrelated_text_is_not_reported_as_an_insertion(self):
        # Nothing of the line was recognised: that is not "extra text at the edge".
        self.assertEqual(er.edge_insertion("abc", "xyzxyzxyz"), {"prefix": "", "suffix": ""})

    def test_line_score_carries_the_flag(self):
        self.assertEqual(score("số 64 được", "số 64 được tháng 19")["edge_insertion"], 1)
        self.assertEqual(score("số 64 được", "s 64 đưc")["edge_insertion"], 0)


class LengthGroups(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(er.length_group(320, 32), "short")    # 10:1
        self.assertEqual(er.length_group(512, 32), "short")    # exactly VietOCR's limit
        self.assertEqual(er.length_group(513, 32), "medium")
        self.assertEqual(er.length_group(768, 32), "medium")   # 24:1
        self.assertEqual(er.length_group(769, 32), "long")

    def test_cer_per_group(self):
        scores = {
            bakeoff.PPOCR: [score("Việt Nam", "Vit Nam"), score("abcd", "abcd")],
            bakeoff.VIETOCR: [score("Việt Nam", "Việt Nam"), score("abcd", "ab")],
        }
        rows = {(r["length_group"], r["recognizer"]): r for r in er.length_group_rows(scores, ["short", "long"])}
        self.assertAlmostEqual(rows[("short", bakeoff.PPOCR)]["micro_cer_nfc"], 1 / 8)
        self.assertEqual(rows[("short", bakeoff.VIETOCR)]["micro_cer_nfc"], 0)
        self.assertAlmostEqual(rows[("long", bakeoff.VIETOCR)]["micro_cer_nfc"], 0.5)
        self.assertEqual((rows[("medium", bakeoff.PPOCR)]["lines"], rows[("medium", bakeoff.PPOCR)]["micro_cer_nfc"]), (0, None))


class Paired(unittest.TestCase):
    def test_wins_ties_and_deltas(self):
        scores = {
            bakeoff.PPOCR: [score("Việt Nam", "Vit Nam"), score("abcd", "abcd"), score("xy", "xy")],
            bakeoff.VIETOCR: [score("Việt Nam", "Việt Nam"), score("abcd", "ab"), score("xy", "xy")],
        }
        paired = er.paired_lines(scores)
        self.assertEqual((paired["ppocr_wins"], paired["vietocr_wins"], paired["ties"]), (1, 1, 1))
        # Per-line CER of VietOCR minus PP-OCRv6: -1/8, +2/4, 0.
        self.assertAlmostEqual(paired["mean_cer_delta"], (-0.125 + 0.5 + 0) / 3)
        self.assertAlmostEqual(paired["median_cer_delta"], 0)
        interval = paired["micro_cer_delta"]
        self.assertAlmostEqual(interval["difference"], 2 / 14 - 1 / 14)
        self.assertLessEqual(interval["low"], interval["difference"])
        self.assertGreaterEqual(interval["high"], interval["difference"])


class DecisionRule(unittest.TestCase):
    REFERENCE = "thực hiện việc lạ"

    def decide(
        self, lines: int, ppocr: str, vietocr: str, *, long_ppocr=None, long_vietocr=None, long_lines=None, head=True
    ):
        """``lines`` short lines, plus ``long_lines`` long ones when their predictions are given."""
        scores = {
            bakeoff.PPOCR: [score(self.REFERENCE, ppocr) for _ in range(lines)],
            bakeoff.VIETOCR: [score(self.REFERENCE, vietocr) for _ in range(lines)],
        }
        groups = ["short"] * lines
        if long_ppocr is not None:
            long_lines = lines if long_lines is None else long_lines
            scores[bakeoff.PPOCR] += [score(self.REFERENCE, long_ppocr) for _ in range(long_lines)]
            scores[bakeoff.VIETOCR] += [score(self.REFERENCE, long_vietocr) for _ in range(long_lines)]
            groups += ["long"] * long_lines
        return er.decide(scores, groups, head, 100)

    def test_too_few_lines(self):
        decision = self.decide(99, "thc hin vic l", self.REFERENCE)
        self.assertEqual(decision["verdict"], "NOT DECIDED")
        self.assertEqual(len(decision["report"]), 1)

    def test_no_lines(self):
        decision = er.decide({name: [] for name in er.RECOGNIZERS}, [], None, 100)
        self.assertEqual(decision["verdict"], "NOT DECIDED")

    def test_vietocr_clearly_better(self):
        decision = self.decide(100, "thc hin vic l", self.REFERENCE)
        self.assertEqual(decision["verdict"], "VIETOCR")
        self.assertTrue(all(decision["conditions"]["vietocr"].values()))
        self.assertIn("VietOCR recognizer", decision["report"][-1])

    def test_vietocr_better_overall_but_clearly_worse_on_long_lines_is_inconclusive(self):
        # Many short lines VietOCR reads perfectly, a few long ones where it invents a suffix.
        decision = self.decide(
            100, "thc hin vic l", self.REFERENCE,
            long_ppocr="thc hin vic l", long_vietocr="thực hiện việc lạ thêm 1234", long_lines=20,
        )  # fmt: skip
        self.assertTrue(decision["conditions"]["vietocr"]["CER clearly lower than PP-OCRv6"])
        self.assertFalse(decision["conditions"]["vietocr"]["not clearly worse than PP-OCRv6 on long lines"])
        self.assertEqual(decision["verdict"], "INCONCLUSIVE")
        self.assertIn("verify the remaining lines", decision["report"][-1])

    def test_custom_ppocr_when_close_overall_and_vietocr_fails_long_lines(self):
        arguments = dict(long_ppocr="thc hin vic l", long_vietocr="thực hiện xx xx và chữ bịa thêm")
        decision = self.decide(100, "thc hin vic l", "thực hiện việc lx", **arguments)
        self.assertTrue(all(decision["conditions"]["custom_ppocr"].values()), decision["conditions"])
        self.assertEqual(decision["verdict"], "CUSTOM PP-OCRV6")
        # Without a proven head migration the same numbers do not justify that choice.
        self.assertEqual(self.decide(100, "thc hin vic l", "thực hiện việc lx", head=None, **arguments)["verdict"], "INCONCLUSIVE")

    def test_an_interval_containing_zero_is_never_called_clear(self):
        decision = self.decide(100, "thực hiện việc lạ", "thực hiện việc lạ")
        self.assertFalse(decision["conditions"]["vietocr"]["CER clearly lower than PP-OCRv6"])
        self.assertEqual(decision["verdict"], "INCONCLUSIVE")


class GroundTruthIntegrity(unittest.TestCase):
    def row(self, **changes) -> dict:
        row = {column: "" for column in bakeoff.ANNOTATION_COLUMNS}
        row.update(id="a", ground_truth="Việt Nam", verified="true", ground_truth_sha256=bakeoff.text_sha256("Việt Nam"))
        row.update(changes)
        return row

    def test_verified_rows_with_matching_hash_are_scored(self):
        usable, rejected = er.usable_rows([self.row()])
        self.assertEqual((len(usable), rejected), (1, []))

    def test_ground_truth_edited_after_verification_is_not_scored(self):
        usable, rejected = er.usable_rows([self.row(ground_truth="Việt Nam!")])
        self.assertEqual(usable, [])
        self.assertIn("changed after it was verified", rejected[0])

    def test_skipped_and_pending_rows_are_never_scored(self):
        skipped = self.row(verified="false", excluded_reason="stamp", ground_truth="", ground_truth_sha256="")
        pending = self.row(verified="false", ground_truth="bản nháp", ground_truth_sha256="")
        self.assertEqual(er.usable_rows([skipped, pending]), ([], []))


class EndToEnd(unittest.TestCase):
    TRUTH = {"a": "thực hiện", "b": "abc", "c": "bị che"}

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.dictionary = self.root / "dict.txt"
        self.dictionary.write_text("".join(c + "\n" for c in "abcdefghijklmnopqrstuvwxyz"), encoding="utf-8")
        self.hard_cases = self.root / "hard_cases.txt"
        self.hard_cases.write_text("thực hiện\n", encoding="utf-8")
        bakeoff.write_jsonl(
            self.root / "manifest.jsonl",
            [{"id": key, "crop_path": f"{key}.png", "crop_width": width, "crop_height": 32}
             for key, width in (("a", 900), ("b", 100), ("c", 100))],
        )  # fmt: skip

    def write(self, verified: bool, ppocr_ids=("a", "b", "c"), vietocr_ids=("a", "b", "c")) -> list[str]:
        rows = []
        for key, truth in self.TRUTH.items():
            row = {column: "" for column in bakeoff.ANNOTATION_COLUMNS}
            row.update(id=key, document="d", page="1", crop_path=f"{key}.png", verified="false")
            if key == "c":
                row["excluded_reason"] = "stamp"  # set aside by the annotator
            elif verified:
                row.update(ground_truth=truth, verified="true", ground_truth_source="typed",
                           ground_truth_sha256=bakeoff.text_sha256(truth))  # fmt: skip
            rows.append(row)
        bakeoff.write_annotation(self.root / "manifest.tsv", rows)
        predictions = {
            "ppocr": {"a": "thc hin", "b": "abc", "c": "b che"},
            "vietocr": {"a": "thực hiện", "b": "abd", "c": "bị che"},
        }
        for name, ids in (("ppocr", ppocr_ids), ("vietocr", vietocr_ids)):
            bakeoff.write_jsonl(
                self.root / f"{name}.jsonl",
                [{"id": key, "prediction": predictions[name][key], "confidence": None, "runtime_ms": 1}
                 for key in ids],
            )  # fmt: skip
        return [
            "--annotation", str(self.root / "manifest.tsv"),
            "--manifest", str(self.root / "manifest.jsonl"),
            "--ppocr", str(self.root / "ppocr.jsonl"),
            "--vietocr", str(self.root / "vietocr.jsonl"),
            "--dict", str(self.dictionary),
            "--hard-cases", str(self.hard_cases),
            "--head-analysis", str(self.root / "no_head_analysis.json"),
            "--results-dir", str(self.root / "results"),
        ]  # fmt: skip

    def read(self, name: str) -> list[dict]:
        with (self.root / "results" / name).open(encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))

    def test_metrics_files(self):
        self.assertEqual(er.main(self.write(True)), 0)
        metrics = {row["recognizer"]: row for row in self.read("recognizer_metrics.csv")}
        # Ground truth: "thực hiện" (9 characters) + "abc" (3). Row "c" was set aside.
        self.assertEqual(metrics["ppocrv6"]["verified_lines"], "2")
        self.assertEqual((metrics["ppocrv6"]["characters_gt"], metrics["ppocrv6"]["words_gt"]), ("12", "3"))
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
        # The letter in the row that was set aside is not counted anywhere.
        self.assertEqual(by_char["ị"]["occurrences"], "0")

        groups = {(row["length_group"], row["recognizer"]): row for row in self.read("line_length_groups.csv")}
        self.assertEqual((groups[("long", "ppocrv6")]["lines"], groups[("short", "ppocrv6")]["lines"]), ("1", "1"))
        self.assertEqual(groups[("long", "vietocr")]["micro_cer_nfc"], "0.000000")
        self.assertEqual([row["id"] for row in self.read("recognizer_errors.csv")], ["a", "b"])

        summary = json.loads((self.root / "results" / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["ground_truth"]["verified_lines"], 2)
        self.assertEqual((summary["ground_truth"]["skipped"], summary["ground_truth"]["selected"]), (1, 3))
        self.assertEqual(summary["ground_truth"]["skipped_by_reason"], {"stamp": 1})
        self.assertTrue(summary["ground_truth"]["all_nfc"])
        self.assertEqual(summary["paired"]["ppocr_wins"], 1)
        self.assertEqual(summary["paired"]["vietocr_wins"], 1)
        self.assertEqual(summary["decision"]["verdict"], "NOT DECIDED")

    def test_unverified_rows_are_not_scored(self):
        self.assertEqual(er.main(self.write(False)), 0)
        self.assertFalse((self.root / "results").exists())

    def test_different_id_sets_fail(self):
        with self.assertRaises(SystemExit) as failure:
            er.main(self.write(True, vietocr_ids=("a", "b")))
        self.assertIn("FAIL", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
