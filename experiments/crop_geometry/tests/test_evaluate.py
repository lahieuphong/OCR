"""Evaluation helpers: text-layer reference filter, paired measures, sign test, selection rule."""
import unittest

from experiments.crop_geometry import evaluate

AGENCIES = ["Văn phòng Chính phủ", "Bộ Tư pháp"]
ENTRIES = sorted({"chuẩn", "triển", "đảng", "nghị định"})


def word(text, x0, y0, x1, y1, block=0, line=0, number=0):
    return (x0, y0, x1, y1, text, block, line, number)


class TextLayerReference(unittest.TestCase):
    polygon = [[100, 100], [500, 100], [500, 140], [100, 140]]  # pixels at zoom 2.0 -> 50..250 x 50..70 pt

    def test_words_inside_the_polygon_form_the_reference(self):
        words = [word("Nghị", 52, 52, 80, 68, number=0), word("định", 82, 52, 110, 68, number=1),
                 word("dòng-khác", 52, 75, 110, 90, line=1)]
        self.assertEqual(evaluate.text_layer_reference(words, self.polygon, 2.0, None), ("Nghị định", "ok"))

    def test_words_are_read_left_to_right_and_spaced_by_their_gap(self):
        # A number typed into a blank is often its own text object (other block, later in the stream).
        words = [word("Số:", 52, 52, 66, 68, block=0), word("/VPCP-KGVX", 90.2, 52, 140, 68, block=0, number=1),
                 word("10427", 70, 52, 90, 68, block=5)]
        self.assertEqual(evaluate.text_layer_reference(words, self.polygon, 2.0, None), ("Số: 10427/VPCP-KGVX", "ok"))

    def test_a_straddling_or_ambiguous_word_excludes_the_line(self):
        straddling = [word("Nghị", 52, 30, 80, 80)]  # centre inside, 60% of its height outside
        self.assertEqual(evaluate.text_layer_reference(straddling, self.polygon, 2.0, None)[1], "word_straddles_polygon")
        ambiguous = [word("Nghị", 52, 52, 80, 68), word("x", 240, 55, 270, 68)]  # centre outside, 1/3 inside
        self.assertEqual(evaluate.text_layer_reference(ambiguous, self.polygon, 2.0, None)[1], "ambiguous_word_assignment")

    def test_out_of_vocabulary_reference_is_excluded(self):
        words = [word("“trích”", 52, 52, 90, 68)]
        self.assertEqual(evaluate.text_layer_reference(words, self.polygon, 2.0, set("trích"))[1], "out_of_vocab_reference")
        self.assertEqual(evaluate.text_layer_reference([], self.polygon, 2.0, None), (None, "no_text_layer_words"))


class Measures(unittest.TestCase):
    def test_tones_confusions_entities_and_canaries(self):
        m = evaluate.line_measures("Tiêu chuẩn của Văn phòng Chính phủ số 41/2026/QH16 ngày 24 tháng 8 năm 2026",
                                   "Tiêu chuấn của Văn phòng Chính phủ số 41/2026/OH16 ngày 24 tháng 8 năm 2026",
                                   AGENCIES, ENTRIES)
        self.assertEqual(m["tone"]["tone_changed:hoi->sac"], 1)
        self.assertEqual(m["zero_O_Q"], 1)
        self.assertEqual(m["entities_wrong"]["doc_number"], 1)
        self.assertEqual(m["entities_wrong"].get("agency_name", 0), 0)
        self.assertEqual(m["entities"]["date"], 1)
        self.assertEqual(m["canary_correct"], {"chuẩn@1": False})
        handwriting = evaluate.line_measures("Số: 521/NQ-CP", "Số: 5U/NQ-CP", AGENCIES, ENTRIES)
        self.assertEqual(handwriting["one_I_U"], 1)

    def test_sign_test(self):
        self.assertEqual(evaluate.sign_test(0, 0)["p_one_sided_improvement"], 1.0)
        self.assertAlmostEqual(evaluate.sign_test(6, 0)["p_one_sided_improvement"], 1 / 64, places=6)
        self.assertAlmostEqual(evaluate.sign_test(3, 3)["p_two_sided"], 1.0, places=6)
        self.assertLess(evaluate.sign_test(9, 1)["p_one_sided_improvement"], 0.05)


class Selection(unittest.TestCase):
    def dev(self, **configs):
        base = {"char_errors": 10, "cer": 0.01, "improved": 0, "regressed": 0,
                "sign_test": {"p_one_sided_improvement": 1.0}, "canary_regressions": [], "new_entity_errors_vs_A0": {}}
        out = {"A0": base}
        for name, change in configs.items():
            out[name] = {**base, **change}
        return out

    def test_only_a_significant_clean_improvement_is_selected(self):
        good = {"char_errors": 4, "cer": 0.004, "improved": 7, "regressed": 0, "sign_test": {"p_one_sided_improvement": 0.0078}}
        lucky = {"char_errors": 9, "cer": 0.009, "improved": 2, "regressed": 1, "sign_test": {"p_one_sided_improvement": 0.5}}
        canary = {**good, "cer": 0.003, "canary_regressions": ["k#chuẩn@1"]}
        entity = {**good, "cer": 0.002, "new_entity_errors_vs_A0": {"doc_number": 1}}
        result = evaluate.select(self.dev(B2=lucky, B4=good, C4=canary, C8=entity), ["A0", "B2", "B4", "C4", "C8"])
        self.assertEqual(result["selected"], "B4")
        reasons = {c["config"]: c["reasons"] for c in result["candidates"]}
        self.assertIn("canary regression", reasons["C4"])
        self.assertIn("new document-number/date/agency/e-mail error", reasons["C8"])

    def test_nothing_selected_when_no_config_is_eligible(self):
        worse = {"char_errors": 12, "cer": 0.012, "improved": 1, "regressed": 3, "sign_test": {"p_one_sided_improvement": 0.94}}
        self.assertIsNone(evaluate.select(self.dev(B2=worse), ["A0", "B2"])["selected"])


class Unlabelled(unittest.TestCase):
    def test_changes_to_canaries_and_number_tokens_are_listed(self):
        by_key = {"d.pdf|1|1": {"A0": {"text": "Văn phòng Trung ương Đảng;"}, "B4": {"text": "Văn phòng Trung ương Đáng;"}},
                  "d.pdf|1|2": {"A0": {"text": "Số: 59 /2025/TT-BXD"}, "B4": {"text": "Số: 59 /2025/TT-BXĐ"}},
                  "d.pdf|1|3": {"A0": {"text": "không đổi"}, "B4": {"text": "không đổi"}}}
        result = evaluate.unlabelled_changes(sorted(by_key), by_key, ["A0", "B4"])["B4"]
        self.assertEqual(result["changed_lines"], 2)
        self.assertEqual(result["baseline_canary_words_changed"], ["d.pdf|1|1#đảng"])
        self.assertEqual(result["baseline_number_tokens_changed"], ["d.pdf|1|2#/2025/TT-BXD"])


if __name__ == "__main__":
    unittest.main()
