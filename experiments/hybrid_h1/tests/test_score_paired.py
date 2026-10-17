"""Paired A0/H1 scoring and the frozen blind verdict rule, on synthetic lines."""
import json
import unittest
from pathlib import Path

from experiments.hybrid_h1.score_paired import binomial_upper_bound, key_field_errors, score, verdict

CRITERIA = json.loads((Path(__file__).resolve().parents[1] / "blind_criteria_v1.json").read_text(encoding="utf-8"))
AGENCIES = ["Văn phòng Chính phủ"]


def row(key, reference, a0, h1, *, document="d1.pdf", group="born_digital", sets=("changed",)):
    return {"key": key, "document": document, "group": group, "sets": list(sets), "reference": reference, "a0": a0, "h1": h1}


class Statistics(unittest.TestCase):
    def test_exact_upper_bound(self):
        self.assertAlmostEqual(binomial_upper_bound(0, 150), 1 - 0.05 ** (1 / 150), places=6)
        self.assertAlmostEqual(binomial_upper_bound(0, 3), 1 - 0.05 ** (1 / 3), places=6)
        self.assertLess(binomial_upper_bound(2, 150), 0.05)
        self.assertGreater(binomial_upper_bound(3, 150), 0.05)
        self.assertEqual(binomial_upper_bound(5, 5), 1.0)

    def test_key_field_instance_errors(self):
        entities, wrong = key_field_errors("Số: 4471/BTC-KTN, email a@b.vn", "Số: 447/BTC-KTN, email a@b.vn", AGENCIES)
        self.assertEqual({e["type"] for e in entities}, {"doc_number", "email"})
        self.assertEqual({w[0] for w in wrong}, {"doc_number"})


class Scoring(unittest.TestCase):
    def test_pairs_sets_groups_and_key_field_changes(self):
        rows = [
            row("a", "Email: a@example.vn", "Email: a@example.yn", "Email: a@example.vn"),
            row("b", "Số: 12/QĐ-TTg ngày", "Số: 12/QĐ-TTg ngày", "Số: 12/QĐ-TTe ngày"),
            row("c", "Hà Nội", "Hà Nội", "Hà Nội", sets=("representative",), group="scanned", document="d2.pdf"),
        ]
        result = score(rows, AGENCIES)
        changed = result["metrics"]["by_set"]["changed"]
        self.assertEqual((changed["improved"], changed["regressed"]), (1, 1))
        self.assertEqual(result["metrics"]["all"]["key_fields"]["email"]["fixed_by_h1"], 1)
        self.assertEqual(result["metrics"]["all"]["key_fields"]["doc_number"]["newly_wrong_under_h1"], 1)
        self.assertEqual(sorted(c["type"] for c in result["key_field_changes"]), ["doc_number", "email"])
        self.assertEqual(result["metrics"]["by_group"]["scanned"]["lines"], 1)


class Verdict(unittest.TestCase):
    integrity = {"freeze_verified": True, "fallback_byte_identical": True}
    enough = {"pdfs": 12, "born_digital_pdfs": 8, "excluded_share": 0.02}

    def rows(self, improved=160, regressed=0, new_key_error=False):
        rows = [row(f"i{n}", "quy định của", "quy đinh của", "quy định của", document=f"d{n % 12}.pdf") for n in range(improved)]
        rows += [row(f"r{n}", "quy định của", "quy định của", "quy đinh của", document=f"d{n % 12}.pdf") for n in range(regressed)]
        rows += [row(f"p{n}", "Hà Nội", "Hà Nội", "Hà Nội", sets=("representative",), document=f"d{n % 12}.pdf") for n in range(310)]
        if new_key_error:
            rows.append(row("k", "Số: 125/QĐ-TTg", "Số: 125/QĐ-TTg", "Số: 12S/QĐ-TTg", document="d0.pdf"))
        return score(rows, AGENCIES)["metrics"]

    def test_outcomes(self):
        good = self.rows()
        self.assertEqual(verdict(good, good, CRITERIA, self.integrity, self.enough)["verdict"], "GO_CANDIDATE_FOR_USER_DECISION")
        self.assertEqual(verdict(good, good, CRITERIA, self.integrity, {**self.enough, "pdfs": 3})["verdict"], "INSUFFICIENT_DATA")
        key_error = self.rows(new_key_error=True)
        result = verdict(key_error, key_error, CRITERIA, self.integrity, self.enough)
        self.assertEqual(result["verdict"], "NO_GO")
        self.assertFalse(result["gates"]["B3_no_new_key_field_errors"])
        many = self.rows(regressed=6)
        self.assertFalse(verdict(many, many, CRITERIA, self.integrity, self.enough)["gates"]["B2_regression_rate"])
        flat = self.rows(improved=0)
        self.assertEqual(verdict(good, flat, CRITERIA, self.integrity, self.enough)["verdict"], "INCONCLUSIVE")
        self.assertEqual(verdict(good, good, CRITERIA, {**self.integrity, "fallback_byte_identical": False}, self.enough)["verdict"], "NO_GO")


if __name__ == "__main__":
    unittest.main()
