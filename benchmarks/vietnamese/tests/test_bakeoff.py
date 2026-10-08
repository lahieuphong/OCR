"""Crop manifest, recognizer id sets, annotation table and annotation helper."""

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _paths  # noqa: F401
import bakeoff_common as bakeoff
import export_line_crops
import select_annotation_subset as selection

HAS_EXPORT = bakeoff.MANIFEST.is_file()
HAS_PREDICTIONS = all(path.is_file() for path in bakeoff.PREDICTION_FILES.values())
HAS_PADDLEX = importlib.util.find_spec("paddlex") is not None


def temporary_directory(test: unittest.TestCase) -> Path:
    directory = tempfile.TemporaryDirectory()
    test.addCleanup(directory.cleanup)
    return Path(directory.name)


@unittest.skipUnless(HAS_EXPORT, "line crops have not been exported")
class ExportedManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = bakeoff.load_manifest()

    def test_ids_and_crop_paths_are_unique(self):
        self.assertEqual(len({row["id"] for row in self.rows}), len(self.rows))
        self.assertEqual(len({row["crop_path"] for row in self.rows}), len(self.rows))
        self.assertEqual(len({(row["document"], row["page"], row["line_index"]) for row in self.rows}), len(self.rows))

    def test_id_encodes_document_page_and_line(self):
        for row in self.rows:
            self.assertEqual(row["id"], bakeoff.crop_id(row["document"], row["page"], row["line_index"]))
            self.assertRegex(row["id"], r"_p\d{4}_l\d{4}$")
            self.assertGreaterEqual(row["line_index"], 1)

    def test_schema(self):
        required = {"id", "document", "page", "line_index", "crop_path", "polygon",
                    "paddle_prediction", "paddle_confidence"}  # fmt: skip
        for row in self.rows:
            self.assertLessEqual(required, set(row))
            self.assertEqual(len(row["polygon"]), 4)

    def test_one_crop_file_per_row_and_nothing_else(self):
        on_disk = {path.name for path in bakeoff.CROPS_DIR.glob("*.png")}
        self.assertEqual(on_disk, {Path(row["crop_path"]).name for row in self.rows})

    def test_crops_are_the_exported_files(self):
        for row in self.rows:
            bakeoff.verified_crop_path(row)  # raises on a missing or changed crop

    def test_export_comes_from_the_frozen_profile(self):
        metadata = json.loads(bakeoff.EXPORT_METADATA.read_text(encoding="utf-8"))
        profile = bakeoff.FROZEN_PROFILE
        self.assertEqual(metadata["profile"], "ppocrv6_vi_unwarp_off")
        self.assertEqual(metadata["detection_model"], "PP-OCRv6_medium_det")
        self.assertEqual(
            (metadata["use_doc_orientation_classify"], metadata["use_doc_unwarping"],
             metadata["use_textline_orientation"]),
            (profile.use_doc_orientation_classify, profile.use_doc_unwarping, profile.use_textline_orientation),
        )  # fmt: skip
        self.assertEqual((True, False, True), (profile.use_doc_orientation_classify,
                                               profile.use_doc_unwarping, profile.use_textline_orientation))  # fmt: skip
        self.assertEqual(metadata["num_crops"], len(self.rows))

    def test_export_refuses_to_run_twice(self):
        with self.assertRaises(SystemExit):
            export_line_crops.main([])


@unittest.skipUnless(HAS_EXPORT and HAS_PREDICTIONS, "recognizers have not been run")
class RecognizerOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest_ids = {row["id"] for row in bakeoff.load_manifest()}
        cls.predictions = {
            name: bakeoff.load_predictions(path) for name, path in bakeoff.PREDICTION_FILES.items()
        }

    def test_both_recognizers_cover_the_same_crops(self):
        ppocr, vietocr = (set(self.predictions[name]) for name in (bakeoff.PPOCR, bakeoff.VIETOCR))
        self.assertEqual(ppocr, vietocr)
        self.assertEqual(ppocr, self.manifest_ids)

    def test_both_read_the_same_manifest(self):
        digests = {
            json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))["manifest_sha256"]
            for path in bakeoff.PREDICTION_FILES.values()
        }
        self.assertEqual(digests, {bakeoff.sha256_file(bakeoff.MANIFEST)})

    def test_prediction_schema(self):
        for rows in self.predictions.values():
            for row in rows.values():
                self.assertEqual(set(row), {"id", "prediction", "confidence", "runtime_ms"})
                self.assertIsInstance(row["prediction"], str)
                self.assertTrue(row["confidence"] is None or 0.0 <= row["confidence"] <= 1.0)

    def test_stock_ppocr_never_outputs_a_missing_letter(self):
        # It has no class for them; if one appears, the dictionary was swapped.
        from audit_charset import PPOCRV6_DICT, audit

        missing = set(audit(PPOCRV6_DICT)["missing"])
        for row in self.predictions[bakeoff.PPOCR].values():
            self.assertFalse(missing & set(row["prediction"]), row["id"])


class IdSetCheck(unittest.TestCase):
    def test_equal_sets_pass(self):
        bakeoff.check_same_ids({"a": {"1", "2"}, "b": {"2", "1"}})

    def test_unequal_sets_fail(self):
        with self.assertRaises(SystemExit) as failure:
            bakeoff.check_same_ids({"ppocrv6": {"1", "2"}, "vietocr": {"1"}})
        self.assertIn("FAIL", str(failure.exception))

    def test_duplicate_prediction_ids_fail(self):
        path = temporary_directory(self) / "p.jsonl"
        bakeoff.write_jsonl(path, [{"id": "1", "prediction": "a"}, {"id": "1", "prediction": "b"}])
        with self.assertRaises(SystemExit):
            bakeoff.load_predictions(path)

    def test_duplicate_manifest_ids_fail(self):
        path = temporary_directory(self) / "manifest.jsonl"
        bakeoff.write_jsonl(path, [{"id": "1", "crop_path": "a"}, {"id": "1", "crop_path": "b"}])
        with self.assertRaises(SystemExit):
            bakeoff.load_manifest(path)

    def test_changed_crop_is_rejected(self):
        root = temporary_directory(self)
        (root / "c.png").write_bytes(b"original")
        row = {"id": "1", "crop_path": "c.png", "crop_sha256": bakeoff.sha256_file(root / "c.png")}
        self.assertEqual(bakeoff.verified_crop_path(row, root), root / "c.png")
        (root / "c.png").write_bytes(b"edited")
        with self.assertRaises(SystemExit):
            bakeoff.verified_crop_path(row, root)


class PageRows(unittest.TestCase):
    def raw(self, **changes) -> dict:
        polygons = [[[0, 0], [10, 0], [10, 5], [0, 5]], [[0, 10], [10, 10], [10, 15], [0, 15]]]
        raw = {
            "text_type": "general",
            "dt_polys": polygons,
            "rec_polys": polygons,
            "rec_texts": ["one", "two"],
            "rec_scores": [0.9, 0.8],
            "textline_orientation_angles": [0, 1],
        }
        raw.update(changes)
        return raw

    def test_ids_are_one_based_and_ordered(self):
        rows = export_line_crops.page_rows("doc.signed", 3, self.raw())
        self.assertEqual([row["id"] for row in rows], ["doc.signed_p0003_l0001", "doc.signed_p0003_l0002"])
        self.assertEqual([row["line_index"] for row in rows], [1, 2])
        self.assertEqual(rows[1]["paddle_prediction"], "two")
        self.assertEqual(rows[1]["textline_orientation_angle"], 1)

    def test_a_dropped_line_stops_the_export(self):
        raw = self.raw()
        with self.assertRaises(SystemExit):
            export_line_crops.page_rows("d", 1, {**raw, "rec_polys": raw["rec_polys"][:1]})


@unittest.skipUnless(HAS_PADDLEX, "PaddleX is not installed in this environment")
class CropGeometry(unittest.TestCase):
    def test_slanted_line_is_straightened_not_boxed(self):
        import cv2
        import numpy as np

        # A 200 x 20 bar, white with a black left quarter, turned by 20 degrees.
        width, height, angle = 200, 20, 20.0
        canvas = np.full((300, 300, 3), 128, dtype=np.uint8)
        centre = (150.0, 150.0)
        corners = cv2.boxPoints((centre, (width, height), angle))
        cv2.fillConvexPoly(canvas, corners.astype(np.int32), (255, 255, 255))
        dark = cv2.boxPoints(((centre[0] - 75 * np.cos(np.radians(angle)),
                               centre[1] - 75 * np.sin(np.radians(angle))), (50, height), angle))  # fmt: skip
        cv2.fillConvexPoly(canvas, dark.astype(np.int32), (0, 0, 0))

        # Corners in the detector's order: top-left, top-right, bottom-right, bottom-left.
        ordered = sorted(corners.tolist(), key=lambda point: point[0])
        left = sorted(ordered[:2], key=lambda point: point[1])
        right = sorted(ordered[2:], key=lambda point: point[1])
        polygon = [[round(x), round(y)] for x, y in (left[0], right[0], right[1], left[1])]

        crop = export_line_crops.crop_line(canvas, polygon, 0)
        crop_height, crop_width = crop.shape[:2]
        # The size of the bar itself, not of its 195 x 87 axis-aligned bounding box.
        self.assertAlmostEqual(crop_width, width, delta=4)
        self.assertAlmostEqual(crop_height, height, delta=4)
        middle = crop[crop_height // 2]
        self.assertLess(middle[10].mean(), 60)       # dark end on the left
        self.assertGreater(middle[-10].mean(), 200)  # light end on the right

        turned = export_line_crops.crop_line(canvas, polygon, 1)
        self.assertEqual(turned.shape, crop.shape)
        self.assertGreater(turned[crop_height // 2][10].mean(), 200)  # 180 degrees: ends swapped

    def test_unknown_orientation_is_rejected(self):
        import numpy as np

        with self.assertRaises(ValueError):
            export_line_crops.crop_line(np.zeros((10, 10, 3), np.uint8), [[0, 0], [5, 0], [5, 5], [0, 5]], 2)


class LineTags(unittest.TestCase):
    def tags(self, ppocr: str, vietocr: str, height: int = 30) -> set:
        return selection.line_tags({"crop_height": height}, ppocr, vietocr, set("ạệộ"), small_height=20)

    def test_header(self):
        self.assertIn("header", self.tags("CNG HÒA XÃ HI", "CỘNG HÒA XÃ HỘI"))
        self.assertNotIn("body", self.tags("CNG HÒA XÃ HI", "CỘNG HÒA XÃ HỘI"))

    def test_body_with_missing_letters(self):
        tags = self.tags("quan chu trách nhim", "quan chịu trách nhiệm")
        self.assertLessEqual({"body", "missing_chars"}, tags)
        self.assertNotIn("header", tags)

    def test_small_text_digits_and_long_lines(self):
        self.assertIn("small_text", self.tags("abc", "abc", height=20))
        self.assertIn("digits_symbols", self.tags("S: 99/2030/TT-XYZ", "Số: 99/2030/TT-XYZ"))
        self.assertIn("long_line", self.tags("x" * 60, "y"))
        self.assertNotIn("long_line", self.tags("x" * 59, "y"))

    def test_complex_diacritics(self):
        self.assertIn("complex_diacritics", self.tags("", "nhiệm vụ cộng đồng"))
        self.assertNotIn("complex_diacritics", self.tags("", "Hà Nam là"))


class Selection(unittest.TestCase):
    def setUp(self):
        self.root = temporary_directory(self)
        (self.root / "crops").mkdir()
        self.manifest, ppocr, vietocr = [], [], []
        for document, pages in (("a", 2), ("b", 1)):
            for page in range(1, pages + 1):
                for line in range(1, 31):
                    key = bakeoff.crop_id(document, page, line)
                    crop = self.root / "crops" / f"{key}.png"
                    crop.write_bytes(key.encode())
                    self.manifest.append(
                        {"id": key, "document": document, "page": page, "line_index": line,
                         "crop_path": f"crops/{key}.png", "crop_height": 20 + line,
                         "crop_sha256": bakeoff.sha256_file(crop)}
                    )  # fmt: skip
                    ppocr.append({"id": key, "prediction": f"dòng {line} PP", "confidence": 0.9, "runtime_ms": 1})
                    vietocr.append({"id": key, "prediction": f"dòng {line} việt", "confidence": 0.9, "runtime_ms": 1})
        bakeoff.write_jsonl(self.root / "manifest.jsonl", self.manifest)
        bakeoff.write_jsonl(self.root / "ppocr.jsonl", ppocr)
        bakeoff.write_jsonl(self.root / "vietocr.jsonl", vietocr)
        files = {bakeoff.PPOCR: self.root / "ppocr.jsonl", bakeoff.VIETOCR: self.root / "vietocr.jsonl"}
        patcher = mock.patch.dict(bakeoff.PREDICTION_FILES, files)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.arguments = ["--manifest", str(self.root / "manifest.jsonl"),
                          "--annotation-dir", str(self.root / "annotation")]  # fmt: skip

    def table(self) -> list[dict]:
        return bakeoff.read_annotation(self.root / "annotation" / "manifest.tsv")

    def test_ground_truth_starts_empty_and_unverified(self):
        self.assertEqual(selection.main(self.arguments), 0)
        rows = self.table()
        self.assertTrue(0 < len(rows) <= len(self.manifest))
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        self.assertEqual({row["ground_truth"] for row in rows}, {""})
        self.assertEqual({row["verified"] for row in rows}, {"false"})
        self.assertTrue(all(row["vietocr_prediction"].endswith("việt") for row in rows))
        self.assertEqual({row["document"] for row in rows}, {"a", "b"})
        for row in rows:
            self.assertTrue((self.root / row["crop_path"]).is_file())

    def test_selection_is_deterministic_and_stratified(self):
        rows = [dict(row) for row in self.manifest]
        tags = {row["id"]: {"body"} | ({"header"} if row["line_index"] <= 3 else set()) for row in rows}
        quotas = {"header": 6, "body": 6, "random": 6}
        first = selection.select(rows, tags, quotas, seed=1)
        self.assertEqual(first, selection.select(rows, tags, quotas, seed=1))
        self.assertEqual(len(first), 18)
        headers = [key for key, stratum in first.items() if stratum == "header"]
        self.assertEqual(len(headers), 6)
        # Spread over both documents and all three pages.
        self.assertEqual({key.split("_")[0] for key in headers}, {"a", "b"})
        self.assertEqual(len({key.rsplit("_", 1)[0] for key in headers}), 3)

    def test_existing_ground_truth_is_never_replaced(self):
        selection.main(self.arguments)
        rows = self.table()
        rows[0]["ground_truth"], rows[0]["verified"] = "người gõ", "true"
        bakeoff.write_annotation(self.root / "annotation" / "manifest.tsv", rows)
        with self.assertRaises(SystemExit):
            selection.main(self.arguments + ["--force"])
        self.assertEqual(self.table()[0]["ground_truth"], "người gõ")

    def test_empty_table_needs_force(self):
        selection.main(self.arguments)
        with self.assertRaises(SystemExit):
            selection.main(self.arguments)
        self.assertEqual(selection.main(self.arguments + ["--force"]), 0)


class StockDictionaryOnly(unittest.TestCase):
    def test_ppocr_runner_never_touches_a_dictionary(self):
        source = (_paths.BAKEOFF_DIR / "run_ppocr_rec.py").read_text(encoding="utf-8")
        for forbidden in ("character_dict_path", "EXTENDED_DICT", "ppocrv6_vi_ext_dict", "build_extended_dict"):
            self.assertNotIn(forbidden, source)

    def test_vietocr_runner_contains_no_detector(self):
        source = (_paths.BAKEOFF_DIR / "run_vietocr.py").read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"^\s*(import|from)\s+(paddle|paddleocr|paddlex)\b", source, re.MULTILINE))
        self.assertNotIn("TextDetection", source)


if __name__ == "__main__":
    unittest.main()
