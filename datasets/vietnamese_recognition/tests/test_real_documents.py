"""New real documents: identity, whole-document splits, the blind test, the training mix."""

import contextlib
import io
import json
import re
import unicodedata
import unittest
from pathlib import Path

import _paths  # noqa: F401
import assign_document_splits as assign
import build_dataset
import dataset_common as dataset
import evaluate_splits
import freeze_evaluation_set
import import_real_documents as intake
import select_real_lines as selection
from _fixture import VOCABULARY, Workspace, document_id
from dataset_common import BAKEOFF_REGRESSION, BLIND_TEST, REAL_TRAIN, REAL_VAL, SYNTHETIC_TRAIN, SYNTHETIC_VAL

import bakeoff_common as bakeoff
from annotation_store import ActionError, AnnotationStore

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image body"
TEN_DOCUMENTS = {f"van-ban-{index:02d}": ("", 30) for index in range(10)}


def quiet(function, *arguments):
    with contextlib.redirect_stdout(io.StringIO()) as output:
        status = function(*arguments)
    return status, output.getvalue()


class Intake(unittest.TestCase):
    def setUp(self):
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "real_source"
        self.source.mkdir()
        self.benchmark = self.root / "benchmark.tsv"
        self.benchmark.write_text("document\tfilename\tsha256\tpages\n", encoding="utf-8")

    def run_intake(self, *extra: str):
        status, output = quiet(intake.main, [
            "--source-dir", str(self.source), "--documents", str(self.root / "documents.tsv"),
            "--staged-dir", str(self.root / "staged"), "--benchmark-documents", str(self.benchmark), *extra,
        ])  # fmt: skip
        return status, output, {row["filename"]: row for row in dataset.read_documents(self.root / "documents.tsv")}

    def test_type_comes_from_the_content_not_the_extension(self):
        (self.source / "scan.pdf").write_bytes(PNG)  # a PNG wearing a PDF name
        (self.source / "photo.dat").write_bytes(b"\xff\xd8\xff\xe0 jpeg body")
        (self.source / "notes.txt").write_text("not a document", encoding="utf-8")
        status, output, documents = self.run_intake()
        self.assertEqual(status, 0)
        self.assertEqual({name: row["file_type"] for name, row in documents.items()}, {"scan.pdf": "png", "photo.dat": "jpeg"})
        self.assertIn("skipped notes.txt", output)

    def test_identity_is_the_hash_not_the_name(self):
        (self.source / "a.png").write_bytes(PNG + b"1")
        (self.source / "b-copy-of-a.png").write_bytes(PNG + b"1")
        (self.source / "c.png").write_bytes(PNG + b"2")
        _, output, documents = self.run_intake()
        self.assertEqual(len(documents), 2)  # the same content under two names is one document
        self.assertIn("same content as", output)
        for row in documents.values():
            self.assertEqual(row["document_id"], f"doc_{row['sha256'][:12]}")
        # Renaming a file does not make it a new document.
        (self.source / "c.png").rename(self.source / "renamed.png")
        _, _, again = self.run_intake()
        self.assertEqual({row["sha256"] for row in again.values()}, {row["sha256"] for row in documents.values()})

    def test_a_bakeoff_document_is_refused_whatever_its_name(self):
        (self.source / "looks-new.png").write_bytes(PNG + b"old")
        digest = dataset.sha256_bytes(PNG + b"old")
        self.benchmark.write_text(f"document\tfilename\tsha256\tpages\n738-ttg.signed\tx.pdf\t{digest}\t1\n", encoding="utf-8")
        status, output, documents = self.run_intake()
        self.assertEqual(status, 1)
        self.assertEqual(documents, {})
        self.assertIn("REFUSED looks-new.png: it is the bake-off document 738-ttg.signed", output)

    def test_the_three_real_bakeoff_documents_are_on_the_refusal_list(self):
        self.assertEqual(len(dataset.benchmark_documents()), 3)

    def test_record_fields_and_notes_survive_a_second_import(self):
        (self.source / "a.png").write_bytes(PNG + b"1")
        _, _, documents = self.run_intake("--note", "from the archive")
        row = documents["a.png"]
        self.assertEqual(tuple(row), dataset.DOCUMENT_COLUMNS)
        self.assertEqual((row["page_count"], row["source_note"], row["split"], row["blind"]), ("1", "from the archive", "", "false"))
        rows = dataset.read_documents(self.root / "documents.tsv")
        rows[0].update(split="blind", blind="true", source_note="edited by hand")
        dataset.write_documents(rows, self.root / "documents.tsv")
        (self.source / "b.png").write_bytes(PNG + b"2")
        _, _, documents = self.run_intake("--note", "second batch")
        self.assertEqual((documents["a.png"]["split"], documents["a.png"]["source_note"]), ("blind", "edited by hand"))
        self.assertEqual(documents["b.png"]["source_note"], "second batch")

    def test_documents_are_staged_under_their_id(self):
        (self.source / "a.png").write_bytes(PNG + b"1")
        _, _, documents = self.run_intake()
        staged = list((self.root / "staged").iterdir())
        self.assertEqual([path.name for path in staged], [f"{documents['a.png']['document_id']}.png"])
        self.assertEqual(staged[0].read_bytes(), PNG + b"1")


class DocumentSplits(unittest.TestCase):
    def documents(self, count: int) -> list[dict]:
        return [
            {"document_id": document_id(f"d{index}"), "filename": f"d{index}.pdf", "sha256": dataset.sha256_bytes(f"d{index}".encode()),
             "page_count": 1, "file_type": "pdf", "source_note": "", "split": "", "blind": "false"}
            for index in range(count)
        ]  # fmt: skip

    def test_planned_numbers_follow_the_recommended_allocation(self):
        for total, expected in ((10, 2), (11, 2), (12, 2), (15, 3), (4, 2)):
            self.assertEqual(assign.planned_documents(total), {"blind": expected, "val": expected}, total)

    def test_ten_documents_give_two_two_six(self):
        documents = self.documents(10)
        assign.assign(documents)
        counts = {split: sum(d["split"] == split for d in documents) for split in ("blind", "val", "train")}
        self.assertEqual(counts, {"blind": 2, "val": 2, "train": 6})
        self.assertTrue(all((d["blind"] == "true") == (d["split"] == "blind") for d in documents))

    def test_every_document_belongs_to_exactly_one_split(self):
        documents = self.documents(12)
        assign.assign(documents)
        self.assertTrue(all(d["split"] in dataset.DOCUMENT_SPLITS for d in documents))
        self.assertEqual(len({d["document_id"] for d in documents}), 12)

    def test_assignment_depends_on_content_not_on_names_or_order(self):
        first = self.documents(10)
        assign.assign(first)
        second = [dict(d, filename=f"renamed-{i}.pdf", split="", blind="false") for i, d in enumerate(reversed(self.documents(10)))]
        assign.assign(second)
        self.assertEqual({d["sha256"]: d["split"] for d in first}, {d["sha256"]: d["split"] for d in second})

    def test_new_documents_never_move_old_ones(self):
        documents = self.documents(6)
        assign.assign(documents)
        before = {d["document_id"]: d["split"] for d in documents}
        more = documents + [d for d in self.documents(14) if d["document_id"] not in before]
        assign.assign(more)
        self.assertEqual({d["document_id"]: d["split"] for d in more if d["document_id"] in before}, before)

    def test_a_document_cannot_change_split_once_annotated(self):
        workspace = Workspace(self, {"a": ("train", 5), "b": ("val", 5), "c": ("blind", 5)})
        workspace.annotate(REAL_TRAIN, ["a"], 2)
        arguments = ["--documents", str(workspace.documents_path), "--lines", str(workspace.work_dir / "manifest.jsonl"),
                     "--annotation-dir", str(workspace.work_dir / "annotation")]  # fmt: skip
        with self.assertRaises(SystemExit) as refusal:
            quiet(assign.main, arguments + ["--set", f"{document_id('a')}=blind"])
        self.assertIn("can no longer change", str(refusal.exception))
        # A document nobody has annotated yet may still be moved.
        quiet(assign.main, arguments + ["--set", f"{document_id('b')}=train"])
        moved = {d["document_id"]: d for d in dataset.read_documents(workspace.documents_path)}
        self.assertEqual((moved[document_id("b")]["split"], moved[document_id("a")]["split"]), ("train", "train"))


class DocumentLeakage(unittest.TestCase):
    """One document, one set. Anything else must fail loudly."""

    def workspace(self) -> Workspace:
        workspace = Workspace(self, {"t1": ("train", 6), "t2": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        workspace.annotate(REAL_TRAIN, ["t1", "t2"], 4)
        workspace.annotate(REAL_VAL, ["v1"], 4)
        workspace.annotate(BLIND_TEST, ["b1"], 4)
        return workspace

    def test_a_clean_dataset_builds_and_passes(self):
        workspace = self.workspace()
        self.assertEqual(quiet(workspace.build)[0], 0)
        splits = workspace.splits()
        self.assertEqual({split: len(splits[split]) for split in (REAL_TRAIN, REAL_VAL, BLIND_TEST)},
                         {REAL_TRAIN: 8, REAL_VAL: 4, BLIND_TEST: 4})  # fmt: skip
        self.assertEqual(dataset.document_leaks(splits), [])
        report = workspace.audit()
        self.assertEqual((report["result"], report["leak_failures"]), ("PASS", 0))
        self.assertEqual({row["blind"] for row in splits[BLIND_TEST]}, {"true"})
        self.assertEqual({row["blind"] for row in splits[REAL_TRAIN] + splits[REAL_VAL]}, {"false"})

    def test_document_leaks_names_the_document_and_both_sets(self):
        rows = {
            REAL_TRAIN: [dataset.manifest_row(id="a1", source_document="doc_a", split=REAL_TRAIN, source_type="real")],
            REAL_VAL: [dataset.manifest_row(id="a2", source_document="doc_a", split=REAL_VAL, source_type="real")],
            BLIND_TEST: [dataset.manifest_row(id="b1", source_document="doc_b", split=BLIND_TEST, source_type="real")],
            SYNTHETIC_TRAIN: [dataset.manifest_row(id="s1", source_document="synthetic/x", split=SYNTHETIC_TRAIN, source_type="synthetic")],
            SYNTHETIC_VAL: [dataset.manifest_row(id="s2", source_document="synthetic/x", split=SYNTHETIC_VAL, source_type="synthetic")],
        }
        self.assertEqual(dataset.document_leaks(rows), ["document doc_a has lines in real_train and real_val"])

    def test_build_refuses_a_line_annotated_under_the_wrong_set(self):
        workspace = self.workspace()
        workspace.annotate(REAL_VAL, ["v1", "t1"], 4)  # lines of a training document in the validation table
        with self.assertRaises(SystemExit) as refusal:
            quiet(workspace.build)
        self.assertIn("is assigned to real_train", str(refusal.exception))

    def test_audit_fails_on_a_document_in_train_and_validation(self):
        workspace = self.workspace()
        quiet(workspace.build)
        moved = workspace.splits()[REAL_TRAIN][0]
        workspace.rewrite(REAL_TRAIN, lambda rows: rows.pop(0))
        workspace.rewrite(REAL_VAL, lambda rows: rows.append({**moved, "split": REAL_VAL}))
        report = workspace.audit()
        self.assertEqual(report["result"], "FAIL")
        self.assertGreater(report["leak_failures"], 0)
        self.assertTrue(any("has lines in real_train and real_val" in failure for failure in report["failures"]))
        self.assertFalse(report["readiness"]["ready"])

    def test_audit_fails_on_a_document_in_train_and_blind(self):
        workspace = self.workspace()
        quiet(workspace.build)
        moved = workspace.splits()[BLIND_TEST][0]
        workspace.rewrite(REAL_TRAIN, lambda rows: rows.append({**moved, "id": "copy", "crop_sha256": "f" * 64, "split": REAL_TRAIN, "blind": "false"}))
        report = workspace.audit()
        self.assertTrue(any("has lines in blind_test and real_train" in failure for failure in report["failures"]))
        self.assertEqual(report["result"], "FAIL")

    def test_audit_fails_on_the_same_image_in_two_sets(self):
        workspace = self.workspace()
        quiet(workspace.build)
        image = workspace.splits()[REAL_VAL][0]["crop_sha256"]
        workspace.rewrite(SYNTHETIC_TRAIN, lambda rows: rows[0].update(crop_sha256=image))
        report = workspace.audit()
        self.assertEqual(report["images_in_two_sets"], 1)
        self.assertGreater(report["leak_failures"], 0)

    def test_audit_fails_on_a_document_registered_twice_or_from_the_bakeoff(self):
        workspace = self.workspace()
        quiet(workspace.build)
        documents = dataset.read_documents(workspace.documents_path)
        duplicate = dict(documents[0], document_id="doc_other", filename="again.pdf")
        old = dict(documents[1], document_id="doc_bakeoff", sha256=next(iter(dataset.benchmark_documents())), split="train")
        dataset.write_documents(documents + [duplicate, old], workspace.documents_path)
        failures = "\n".join(workspace.audit()["failures"])
        self.assertIn("source document registered 2 times", failures)
        self.assertIn("doc_bakeoff is the bake-off document", failures)

    def test_audit_fails_on_one_document_imported_twice_into_two_sets(self):
        workspace = self.workspace()
        quiet(workspace.build)
        pair = {"first": document_id("t1"), "second": document_id("b1"), "shared_share": 0.9}
        bakeoff.write_json(workspace.work_dir / "document_similarity.json", {"threshold": 0.5, "pairs": [pair]})
        report = workspace.audit()
        self.assertTrue(any("probably one document in two sets" in failure for failure in report["failures"]))
        # The same pair inside one set is suspicious but leaks nothing.
        pair["second"] = document_id("t2")
        bakeoff.write_json(workspace.work_dir / "document_similarity.json", {"threshold": 0.5, "pairs": [pair]})
        report = workspace.audit()
        self.assertEqual(report["result"], "PASS")
        self.assertTrue(any("twice in one set" in warning for warning in report["warnings"]))

    def test_shared_text_is_a_warning_not_a_failure(self):
        workspace = self.workspace()
        workspace.annotate(REAL_VAL, ["v1"], 4, text=lambda line: "Độc lập - Tự do - Hạnh phúc" if line["line_index"] == 1 else line["true_text"])
        workspace.annotate(BLIND_TEST, ["b1"], 4, text=lambda line: "Độc lập - Tự do - Hạnh phúc" if line["line_index"] == 1 else line["true_text"])
        quiet(workspace.build)
        report = workspace.audit()
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["texts_shared_between_sets"].get("real_val/blind_test"), 1)
        self.assertTrue(any("identical text in two sets" in warning for warning in report["warnings"]))

    def test_similar_documents_are_found_by_their_text(self):
        import export_real_line_crops as export

        lines = [f"đây là dòng văn bản số {index} của tài liệu" for index in range(20)]
        fingerprints = {
            "doc_a": export.line_fingerprints(lines),
            "doc_a_rescanned": export.line_fingerprints([line.upper() if i % 4 == 0 else f"  {line} " for i, line in enumerate(lines)]),
            "doc_b": export.line_fingerprints([f"một tài liệu hoàn toàn khác, dòng {index}" for index in range(20)]),
        }
        pairs = export.similar_documents(fingerprints)
        self.assertEqual([(pair["first"], pair["second"]) for pair in pairs], [("doc_a", "doc_a_rescanned")])
        self.assertEqual(pairs[0]["shared_share"], 1.0)


class CropThatIsAlsoAFrozenLine(unittest.TestCase):
    """A validation crop with the very bytes of a bake-off crop: refused, until a person sets it aside."""

    REASON = "duplicate_frozen_image"

    def setUp(self):
        self.workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        self.frozen = dataset.FrozenLines.load(BAKEOFF_REGRESSION).rows[0]
        # The same signature block or header, cut from a new document: another id, the same file.
        self.duplicate = next(line for line in self.workspace.lines if line["document_id"] == document_id("v1"))
        self.duplicate["crop_sha256"] = self.frozen["crop_sha256"]
        self.workspace.save_lines()
        self.workspace.annotate(REAL_TRAIN, ["t1"], 4)
        self.workspace.annotate(REAL_VAL, ["v1"], 4)
        self.workspace.annotate(BLIND_TEST, ["b1"], 4)
        self.table = self.workspace.work_dir / "annotation" / REAL_VAL / "manifest.tsv"

    def set_aside(self) -> AnnotationStore:
        store = AnnotationStore(self.table, self.table.with_name("log.jsonl"), "tester", only_ids=[self.duplicate["id"]])
        self.assertEqual(store.current()["id"], self.duplicate["id"])  # shown again although verified
        store.skip(self.duplicate["id"], self.REASON)
        return store

    def test_the_build_refuses_it_and_touches_no_annotation(self):
        before = self.table.read_bytes()
        with self.assertRaises(SystemExit) as refusal:
            quiet(self.workspace.build)
        self.assertIn(f"{self.duplicate['id']}: image of a bakeoff_regression line (same SHA-256)", str(refusal.exception))
        # Refusing is all the build does: the row is neither removed nor set aside for the annotator.
        self.assertEqual(self.table.read_bytes(), before)
        row = {r["id"]: r for r in bakeoff.read_annotation(self.table)}[self.duplicate["id"]]
        self.assertEqual((row["verified"], row["excluded_reason"]), ("true", ""))
        self.assertFalse(dataset.manifest_path(REAL_VAL, self.workspace.root).exists())

    def test_set_aside_by_a_person_it_no_longer_blocks_the_build(self):
        self.set_aside()
        status, _ = quiet(self.workspace.build)
        self.assertEqual(status, 0)
        validation = self.workspace.splits()[REAL_VAL]
        self.assertEqual(len(validation), 3)
        self.assertNotIn(self.duplicate["id"], {row["id"] for row in validation})
        self.assertNotIn(self.frozen["crop_sha256"], {row["crop_sha256"] for row in validation})
        report = self.workspace.audit()
        self.assertEqual((report["result"], report["leak_failures"], report["images_in_two_sets"]), ("PASS", 0, 0))
        self.assertEqual(report["annotation"][REAL_VAL], {"selected": 6, "verified": 3, "skipped": 1, "pending": 2})
        self.assertEqual(report["readiness"]["conditions"]["real_val_verified"]["found"], 3)

    def test_the_other_sets_and_the_frozen_line_are_left_alone(self):
        others = {split: (self.workspace.work_dir / "annotation" / split / "manifest.tsv").read_bytes() for split in (REAL_TRAIN, BLIND_TEST)}
        self.set_aside()
        quiet(self.workspace.build)
        for split, before in others.items():
            self.assertEqual((self.workspace.work_dir / "annotation" / split / "manifest.tsv").read_bytes(), before, split)
        splits = self.workspace.splits()
        self.assertEqual((len(splits[REAL_TRAIN]), len(splits[BLIND_TEST]), len(splits[BAKEOFF_REGRESSION])), (4, 4, 100))
        kept = {row["id"]: row for row in splits[BAKEOFF_REGRESSION]}[self.frozen["id"]]
        self.assertEqual((kept["text"], kept["crop_sha256"]), (self.frozen["ground_truth"], self.frozen["crop_sha256"]))

    def test_replacements_bring_validation_back_to_its_target(self):
        self.set_aside()
        session = AnnotationStore(self.table, self.table.with_name("log.jsonl"), "tester", target=4)
        self.assertEqual(session.progress()["verified"], 3)
        replaced = []
        while (row := session.current()) is not None:
            replaced.append(row["id"])
            session.enter(row["id"], f"dòng thay thế {len(replaced)}")
        self.assertEqual(len(replaced), 1)
        self.assertNotIn(self.duplicate["id"], replaced)
        quiet(self.workspace.build)
        self.assertEqual(len(self.workspace.splits()[REAL_VAL]), 4)
        self.assertEqual(self.workspace.audit()["result"], "PASS")


class LineLongerThanTheStockDecoder(unittest.TestCase):
    """A verified validation line of 129 characters: never dropped, valid when the configuration covers it."""

    LIMIT_160 = {"characters": 160, "decoder_max_seq_length": 160, "transformer_max_seq_length": 1024, "config": "x.yml"}

    SENTENCE = "Căn cứ Nghị định số 15/2024/NĐ-CP ngày 05 tháng 02 năm 2025 của Chính phủ quy định chức năng, nhiệm vụ; "

    def workspace(self, characters: int) -> tuple[Workspace, str, str]:
        workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        text = (self.SENTENCE * 2)[: characters - 1] + "."
        self.assertEqual(len(text), characters)
        self.assertEqual(set(text) - set(VOCABULARY), set())
        workspace.annotate(REAL_TRAIN, ["t1"], 4)
        workspace.annotate(REAL_VAL, ["v1"], 4, text=lambda line: text if line["line_index"] == 1 else line["true_text"])
        workspace.annotate(BLIND_TEST, ["b1"], 4)
        key = next(line["id"] for line in workspace.lines if line["document_id"] == document_id("v1"))
        return workspace, key, text

    def test_it_stays_in_real_val_and_in_the_file_validation_reads(self):
        workspace, key, text = self.workspace(129)
        self.assertEqual(quiet(workspace.build)[0], 0)
        row = {row["id"]: row for row in workspace.splits()[REAL_VAL]}[key]
        self.assertEqual((row["text"], row["split"], row["verified"]), (text, REAL_VAL, "true"))
        self.assertEqual(row["subset"], "")  # in particular not out_of_vocabulary
        annotation = (workspace.root / "manifests" / "vietocr" / "real_val_annotation.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(annotation), 4)
        self.assertIn(f"{row['image_path']}\t{text}", annotation)
        # Nobody set it aside along the way.
        table = {r["id"]: r for r in bakeoff.read_annotation(workspace.work_dir / "annotation" / REAL_VAL / "manifest.tsv")}
        self.assertEqual((table[key]["verified"], table[key]["excluded_reason"]), ("true", ""))

    def test_under_a_configuration_of_160_steps_the_audit_passes_and_counts_it(self):
        workspace, _, _ = self.workspace(129)
        quiet(workspace.build)
        report = workspace.audit(label_limit=self.LIMIT_160)
        self.assertEqual((report["result"], report["failures"]), ("PASS", []))
        self.assertEqual(report["readiness"]["conditions"]["real_val_verified"]["found"], 4)
        self.assertEqual(report["label_limit"]["longest_label"][REAL_VAL], 129)
        self.assertEqual(report["label_limit"]["labels_beyond_the_stock_decoder"][REAL_VAL], 1)

    def test_under_the_configured_128_steps_it_is_reported_not_dropped(self):
        workspace, key, _ = self.workspace(129)
        quiet(workspace.build)
        self.assertIn(key, {row["id"] for row in workspace.splits()[REAL_VAL]})
        report = workspace.audit()
        self.assertEqual(report["result"], "FAIL")
        self.assertFalse(report["readiness"]["ready"])
        self.assertIn(
            f"{key}: label of 129 characters exceeds the configured limit of 128 "
            "(decoder_max_seq_length 128, transformer.max_seq_length 1024 in exp_a_width512.yml)",
            report["failures"],
        )

    def test_a_line_of_exactly_128_characters_is_an_ordinary_validation_line(self):
        workspace, key, _ = self.workspace(128)
        quiet(workspace.build)
        report = workspace.audit()
        self.assertEqual((report["result"], report["failures"]), ("PASS", []))
        self.assertEqual(report["readiness"]["conditions"]["real_val_verified"]["found"], 4)
        self.assertIn(key, {row["id"] for row in workspace.splits()[REAL_VAL]})


class Selection(unittest.TestCase):
    def test_training_shares_keep_a_quarter_random(self):
        self.assertAlmostEqual(sum(selection.TRAIN_SHARES.values()), 1.0)
        self.assertGreaterEqual(selection.TRAIN_SHARES["random"], 0.25)
        quotas = selection.quotas_for(REAL_TRAIN, 520)
        self.assertEqual(sum(quotas.values()), 520)
        self.assertGreaterEqual(quotas["random"] / 520, 0.25)
        self.assertEqual(list(quotas)[-1], "random")  # filled last, from whatever is left
        for kind in ("header", "date", "document_number", "agency", "proper_name", "long_line", "short_line",
                     "punctuation", "digits_symbols", "complex_diacritics", "low_quality", "body"):  # fmt: skip
            self.assertGreater(quotas[kind], 0, kind)

    def test_validation_and_blind_test_are_drawn_at_random(self):
        self.assertEqual(selection.quotas_for(REAL_VAL, 140), {"random": 140})
        self.assertEqual(selection.quotas_for(BLIND_TEST, 140), {"random": 140})

    def test_line_kinds_are_recognised(self):
        def tags(text: str, confidence: float = 0.99, height: int = 30) -> set:
            row = {"ppocr_prediction": text, "vietocr_prediction": text, "confidence": confidence, "crop_height": height}
            return selection.tags_of(row, set("ệạộ"), small_height=15, low_confidence=0.6)

        self.assertIn("date", tags("Hà Nội, ngày 05 tháng 02 năm 2025"))
        self.assertIn("date", tags("từ 01/02/2025 đến hết năm"))
        self.assertIn("document_number", tags("Số: 15/2024/NĐ-CP"))
        self.assertIn("document_number", tags("theo Quyết định số 893/QĐ-TTg của Thủ tướng"))
        self.assertIn("document_number", tags("Kết luận số 14-KL/TW"))
        self.assertIn("agency", tags("gửi Bộ Tài chính và Ủy ban nhân dân tỉnh"))
        self.assertIn("proper_name", tags("ông Nguyễn Văn An ký"))
        self.assertIn("header", tags("QUYẾT ĐỊNH"))
        self.assertIn("short_line", tags("Nơi nhận:"))
        self.assertIn("punctuation", tags("a) rà soát, sửa đổi; b) bổ sung."))
        self.assertIn("low_quality", tags("chữ mờ", confidence=0.4))
        self.assertIn("low_quality", tags("chữ nhỏ", height=12))
        plain = tags("các cơ quan phối hợp thực hiện nhiệm vụ được giao trong")
        self.assertEqual(plain & {"date", "document_number", "header", "low_quality", "short_line"}, set())

    def tables(self, workspace: Workspace) -> dict[str, list[dict]]:
        quiet(selection.main, ["--documents", str(workspace.documents_path), "--work-dir", str(workspace.work_dir)])
        return {split: bakeoff.read_annotation(workspace.work_dir / "annotation" / split / "manifest.tsv") for split in dataset.REAL_SPLITS}

    def test_lines_follow_their_document_and_start_unlabelled(self):
        workspace = Workspace(self, {"t1": ("train", 40), "t2": ("train", 40), "v1": ("val", 30), "b1": ("blind", 30)})
        tables = self.tables(workspace)
        members = {REAL_TRAIN: {document_id("t1"), document_id("t2")}, REAL_VAL: {document_id("v1")}, BLIND_TEST: {document_id("b1")}}
        seen = set()
        for split, rows in tables.items():
            self.assertTrue(rows)
            self.assertLessEqual({row["document"] for row in rows}, members[split], split)
            self.assertEqual({(row["ground_truth"], row["verified"]) for row in rows}, {("", "false")})
            self.assertEqual(seen & {row["id"] for row in rows}, set())
            seen |= {row["id"] for row in rows}

    def test_blind_lines_are_picked_without_looking_at_them(self):
        workspace = Workspace(self, {"t1": ("train", 40), "v1": ("val", 30), "b1": ("blind", 30)})
        self.tables(workspace)
        reasons = json.loads((workspace.work_dir / "annotation" / BLIND_TEST / "selection.json").read_text(encoding="utf-8"))["lines"]
        self.assertEqual({reason["selected_by"] for reason in reasons.values()}, {"random"})
        self.assertEqual({tuple(reason["tags"]) for reason in reasons.values()}, {()})
        train = json.loads((workspace.work_dir / "annotation" / REAL_TRAIN / "selection.json").read_text(encoding="utf-8"))["lines"]
        self.assertGreater(len({reason["selected_by"] for reason in train.values()}), 2)

    def test_tables_with_annotation_work_are_never_rewritten(self):
        workspace = Workspace(self, {"t1": ("train", 20), "v1": ("val", 20), "b1": ("blind", 20)})
        self.tables(workspace)
        table = workspace.work_dir / "annotation" / REAL_TRAIN / "manifest.tsv"
        store = AnnotationStore(table, table.with_name("log.jsonl"), "tester")
        first = store.current()["id"]
        store.enter(first, "văn bản đã gõ")
        quiet(selection.main, ["--documents", str(workspace.documents_path), "--work-dir", str(workspace.work_dir), "--force"])
        kept = {row["id"]: row for row in bakeoff.read_annotation(table)}
        self.assertEqual((kept[first]["ground_truth"], kept[first]["verified"]), ("văn bản đã gõ", "true"))

    def test_unassigned_documents_stop_the_selection(self):
        workspace = Workspace(self, {"t1": ("train", 5), "u1": ("", 5)})
        with self.assertRaises(SystemExit):
            quiet(selection.main, ["--documents", str(workspace.documents_path), "--work-dir", str(workspace.work_dir)])


class HiddenPredictions(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(self, {"b1": ("blind", 4)})
        self.workspace.annotate(BLIND_TEST, ["b1"], 0)
        self.table = self.workspace.work_dir / "annotation" / BLIND_TEST / "manifest.tsv"

    def store(self, **options) -> AnnotationStore:
        return AnnotationStore(self.table, self.table.with_name("log.jsonl"), "tester", **options)

    def test_no_prediction_can_be_accepted_when_they_are_hidden(self):
        store = self.store(show_predictions=False)
        row = store.current()
        for recognizer in (bakeoff.PPOCR, bakeoff.VIETOCR):
            with self.assertRaises(ActionError):
                store.accept(row["id"], recognizer)
        self.assertEqual(store.progress()["verified"], 0)
        store.enter(row["id"], "gõ từ ảnh")
        saved = {r["id"]: r for r in bakeoff.read_annotation(self.table)}[row["id"]]
        self.assertEqual((saved["ground_truth"], saved["ground_truth_source"]), ("gõ từ ảnh", "typed"))

    def test_hidden_predictions_never_reach_the_page(self):
        import annotation_server

        app = annotation_server.AnnotationApp(self.store(show_predictions=False), lambda row: Path(row["crop_path"]))
        state = app.state()
        self.assertFalse(state["show_predictions"])
        self.assertEqual((state["item"]["ppocr"], state["item"]["vietocr"]), ("", ""))
        shown = annotation_server.AnnotationApp(self.store(), lambda row: Path(row["crop_path"])).state()
        self.assertTrue(shown["show_predictions"])
        self.assertTrue(shown["item"]["vietocr"])

    def test_blind_test_hides_them_by_default(self):
        import annotate_split

        calls = []
        original, annotate_split.annotate.main = annotate_split.annotate.main, lambda arguments: calls.append(arguments) or 0
        original_dir, dataset.REAL_ANNOTATION_DIR = dataset.REAL_ANNOTATION_DIR, self.workspace.work_dir / "annotation"
        try:
            self.workspace.annotate(REAL_TRAIN, [], 0)
            self.workspace.annotate(REAL_VAL, [], 0)
            for split in (BLIND_TEST, REAL_TRAIN, REAL_VAL):
                annotate_split.main([split])
            annotate_split.main([BLIND_TEST, "--show-predictions"])
        finally:
            annotate_split.annotate.main, dataset.REAL_ANNOTATION_DIR = original, original_dir
        hidden = ["--hide-predictions" in arguments for arguments in calls]
        self.assertEqual(hidden, [True, False, False, False])
        targets = [arguments[arguments.index("--target") + 1] for arguments in calls]
        self.assertEqual(targets, ["100", "400", "100", "100"])


class RealLinesInTheBuild(unittest.TestCase):
    def test_only_verified_lines_enter_and_labels_are_the_human_ones(self):
        workspace = Workspace(self, {"t1": ("train", 10), "v1": ("val", 10), "b1": ("blind", 10)})
        workspace.annotate(REAL_TRAIN, ["t1"], 3, text=lambda line: unicodedata.normalize("NFD", f"người gõ {line['line_index']}"))
        workspace.annotate(REAL_VAL, ["v1"], 2)
        workspace.annotate(BLIND_TEST, ["b1"], 1)
        quiet(workspace.build)
        splits = workspace.splits()
        self.assertEqual([len(splits[s]) for s in (REAL_TRAIN, REAL_VAL, BLIND_TEST)], [3, 2, 1])
        for row in splits[REAL_TRAIN]:
            self.assertRegex(row["text"], r"^người gõ \d+$")           # the annotator's text, not a prediction
            self.assertTrue(unicodedata.is_normalized("NFC", row["text"]))
            self.assertEqual((row["source_type"], row["verified"], row["source_document"]), ("real", "true", document_id("t1")))
            self.assertEqual(dataset.sha256_file(workspace.root / row["image_path"]), row["crop_sha256"])
        self.assertEqual(len(splits[BAKEOFF_REGRESSION]), 100)

    def test_a_line_the_recognizer_cannot_encode_is_kept_but_not_trained_on(self):
        workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        dash = lambda line: "giai đoạn 2021 – 2025" if line["line_index"] == 1 else line["true_text"]  # noqa: E731
        workspace.annotate(REAL_TRAIN, ["t1"], 4, text=dash)
        workspace.annotate(REAL_VAL, ["v1"], 4, text=dash)
        workspace.annotate(BLIND_TEST, ["b1"], 2)
        quiet(workspace.build)
        splits = workspace.splits()
        self.assertNotIn("–", VOCABULARY)
        for split in (REAL_TRAIN, REAL_VAL):
            flagged = [row for row in splits[split] if row["subset"] == build_dataset.OUT_OF_VOCABULARY]
            self.assertEqual([row["text"] for row in flagged], ["giai đoạn 2021 – 2025"])
            annotation = (workspace.root / "manifests" / "vietocr" / f"{split}_annotation.txt").read_text(encoding="utf-8")
            self.assertEqual(len(annotation.splitlines()), 3)
            self.assertNotIn("–", annotation)
        self.assertNotIn("–", (workspace.root / "manifests" / "vietocr" / "train_mix_annotation.txt").read_text(encoding="utf-8"))
        report = workspace.audit()
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["readiness"]["conditions"]["real_train_verified"]["found"], 3)

    def test_a_legacy_candidate_in_a_set_fails_the_audit(self):
        workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        workspace.annotate(REAL_TRAIN, ["t1"], 3)
        quiet(workspace.build)
        taken = workspace.splits()[REAL_TRAIN][0]
        bakeoff.write_annotation(workspace.legacy_dir / "manifest.tsv", [{
            "id": taken["id"], "document": "216-tb.signed", "page": "1", "crop_path": "x.png", "ppocr_prediction": "",
            "vietocr_prediction": "", "ground_truth": "", "verified": "false", **dict.fromkeys(bakeoff.REVIEW_COLUMNS, ""),
        }])  # fmt: skip
        report = workspace.audit()
        self.assertEqual(report["legacy_candidates"], {"lines": 1, "in_any_set": 1})
        self.assertTrue(any("a legacy candidate line in real_train" in failure for failure in report["failures"]))

    def test_the_259_old_lines_are_set_aside(self):
        table = dataset.LEGACY_DIR / "manifest.tsv"
        if not table.is_file():
            self.skipTest("the legacy candidates are not on this machine")
        rows = bakeoff.read_annotation(table)
        self.assertEqual(len(rows), 259)
        self.assertEqual({(row["ground_truth"], row["verified"]) for row in rows}, {("", "false")})
        report = json.loads((dataset.LEGACY_DIR / "candidates_report.json").read_text(encoding="utf-8"))
        self.assertEqual((report["role"], report["usable_for_training"]), ("legacy_candidate", False))
        ids = {row["id"] for row in rows}
        for split, lines in dataset.read_splits().items():
            if split != BAKEOFF_REGRESSION:
                self.assertEqual(ids & {line["id"] for line in lines}, set(), split)
        self.assertFalse((dataset.DATASET_DIR / "real_annotation").exists())
        self.assertNotIn("legacy", Path(build_dataset.__file__).read_text(encoding="utf-8").lower())


class TrainingMix(unittest.TestCase):
    def rows(self, prefix: str, count: int) -> list[dict]:
        return [dataset.manifest_row(id=f"{prefix}{index}", text="x", split=REAL_TRAIN) for index in range(count)]

    def mix(self, **changes) -> dict:
        return {"real_to_synthetic": [1, 2], "method": "oversample_real", "max_real_repeats": 10, "seed": 1, **changes}

    def test_planned_default_is_one_real_to_two_synthetic(self):
        mix = build_dataset.load_mix()
        self.assertEqual((mix["real_to_synthetic"], mix["method"]), ([1, 2], "oversample_real"))

    def test_oversampling_real_lines_reaches_the_wanted_share(self):
        rows, report = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix())
        self.assertEqual((report["real_repeats"], report["real_samples"], report["synthetic_samples"]), (6, 2400, 5059))
        self.assertEqual(len(rows), 7459)
        self.assertAlmostEqual(report["real_share"], 2400 / 7459, places=4)  # about one in three
        self.assertEqual(sum(row["id"] == "r0" for row in rows), 6)

    def test_real_lines_are_not_drowned(self):
        _, report = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix())
        self.assertGreater(report["real_share"], 0.25)
        unmixed = 400 / (400 + 5059)
        self.assertGreater(report["real_share"], 4 * unmixed)

    def test_the_ratio_is_a_setting_not_a_constant(self):
        even = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix(real_to_synthetic=[1, 1]))[1]
        light = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix(real_to_synthetic=[1, 4]))[1]
        capped = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix(real_to_synthetic=[1, 1], max_real_repeats=5))[1]
        self.assertEqual((even["real_repeats"], light["real_repeats"], capped["real_repeats"]), (10, 3, 5))

    def test_subsampling_synthetic_lines_instead(self):
        rows, report = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix(method="subsample_synthetic"))
        self.assertEqual((report["real_samples"], report["synthetic_samples"]), (400, 800))
        again, _ = build_dataset.training_mix(self.rows("r", 400), self.rows("s", 5059), self.mix(method="subsample_synthetic"))
        self.assertEqual([row["id"] for row in rows], [row["id"] for row in again])  # same seed, same draw

    def test_without_real_lines_the_pass_is_synthetic_only(self):
        rows, report = build_dataset.training_mix([], self.rows("s", 50), self.mix())
        self.assertEqual((len(rows), report["real_samples"], report["real_share"]), (50, 0, 0.0))

    def test_mixing_changes_no_manifest(self):
        workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        workspace.annotate(REAL_TRAIN, ["t1"], 4)
        quiet(workspace.build)
        before = {split: dataset.manifest_path(split, workspace.root).read_bytes() for split in dataset.SPLITS}
        mix = workspace.root / "mix.yml"
        mix.write_text("real_to_synthetic: [3, 1]\nmethod: oversample_real\nmax_real_repeats: 2\nseed: 5\n", encoding="utf-8")
        quiet(workspace.build, "--mix", str(mix))
        self.assertEqual({split: dataset.manifest_path(split, workspace.root).read_bytes() for split in dataset.SPLITS}, before)
        lines = (workspace.root / "manifests" / "vietocr" / "train_mix_annotation.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4 * 2 + len(workspace.splits()[SYNTHETIC_TRAIN]))

    def test_an_invalid_mix_is_refused(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mix.yml"
            path.write_text("real_to_synthetic: [1, 2]\nmethod: something_else\nmax_real_repeats: 3\nseed: 1\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                build_dataset.load_mix(path)


class BlindTestLock(unittest.TestCase):
    def setUp(self):
        self.workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        self.workspace.annotate(REAL_TRAIN, ["t1"], 4)
        self.workspace.annotate(REAL_VAL, ["v1"], 4)
        self.workspace.annotate(BLIND_TEST, ["b1"], 4)
        quiet(self.workspace.build)
        self.predictions = self.workspace.root / "predictions.jsonl"
        rows = []
        for split in (REAL_VAL, BLIND_TEST, SYNTHETIC_VAL):
            for index, row in enumerate(self.workspace.splits()[split]):
                text = row["text"][:-1] if index == 0 else row["text"]  # one character dropped in the first line
                rows.append({"id": row["id"], "prediction": text, "confidence": None, "runtime_ms": 1})
        bakeoff.write_jsonl(self.predictions, rows)

    def score(self, *extra: str):
        return quiet(evaluate_splits.main, ["score", "--root", str(self.workspace.root), "--predictions", str(self.predictions),
                                            "--label", "candidate", *extra])  # fmt: skip

    def results(self) -> dict:
        return json.loads((self.workspace.root / "manifests" / "evaluations" / "candidate.json").read_text(encoding="utf-8"))["results"]

    def test_blind_scores_are_not_computed_by_default(self):
        status, output = self.score()
        self.assertEqual(status, 0)
        self.assertIn("blind_test: LOCKED (4 prediction(s) present, not scored)", output)
        blind = self.results()[BLIND_TEST]
        self.assertEqual(blind, {"lines": 4, "status": "LOCKED", "predictions_not_scored": 4})
        self.assertFalse(any(key.startswith(("cer", "wer", "exact")) for key in blind))
        self.assertEqual(evaluate_splits.blind_test_unlocks(self.workspace.root), [])

    def test_other_sets_are_scored_separately(self):
        _, output = self.score()
        results = self.results()
        characters = sum(len(row["text"]) for row in self.workspace.splits()[REAL_VAL])
        self.assertAlmostEqual(results[REAL_VAL]["cer_nfc"], 1 / characters)
        self.assertEqual(results[REAL_VAL]["exact_line_nfc"], 0.75)
        self.assertIn(SYNTHETIC_VAL, results)
        self.assertRegex(output, r"real_val: 4/4 lines \| CER raw=0\.\d+")

    def test_decoder_limit_hits_and_runtime_are_reported_per_set(self):
        rows = bakeoff.read_jsonl(self.predictions)
        validation = {row["id"] for row in self.workspace.splits()[REAL_VAL]}
        for index, row in enumerate(rows):
            row.update(hit_decoder_limit=row["id"] in validation and index < 2, runtime_ms=500.0)
        bakeoff.write_jsonl(self.predictions, rows)
        bakeoff.write_json(self.predictions.with_suffix(".meta.json"), {"decoder_max_seq_length": 128, "image_max_width": 512,
                                                                         "project_config": "exp_a_width512.yml", "ignored": "x"})  # fmt: skip
        _, output = self.score()
        results = self.results()
        self.assertEqual((results[REAL_VAL]["decoder_limit_hits"], results[REAL_VAL]["runtime_seconds"]), (2, 2.0))
        self.assertEqual(results[SYNTHETIC_VAL]["decoder_limit_hits"], 0)
        self.assertNotIn("decoder_limit_hits", results[BLIND_TEST])  # locked: nothing about it is computed
        self.assertRegex(output, r"real_val: 4/4 lines .* decoder limit hits=2 \| 2\.0 s")
        report = json.loads((self.workspace.root / "manifests" / "evaluations" / "candidate.json").read_text(encoding="utf-8"))
        self.assertEqual(report["run"], {"project_config": "exp_a_width512.yml", "image_max_width": 512, "decoder_max_seq_length": 128})

    def test_predictions_without_those_fields_are_scored_as_before(self):
        self.score()
        self.assertNotIn("decoder_limit_hits", self.results()[REAL_VAL])
        self.assertIn("runtime_seconds", self.results()[REAL_VAL])  # the fixture records a runtime

    def test_unlocking_needs_a_reason_and_leaves_a_trace(self):
        with self.assertRaises(SystemExit):
            self.score("--unlock-blind-test")
        self.assertEqual(evaluate_splits.blind_test_unlocks(self.workspace.root), [])
        _, output = self.score("--unlock-blind-test", "--reason", "final check of the selected config", "--by", "tester")
        self.assertRegex(output, r"blind_test: 4/4 lines \| CER")
        self.assertIn("cer_nfc", self.results()[BLIND_TEST])
        unlocks = evaluate_splits.blind_test_unlocks(self.workspace.root)
        self.assertEqual([(entry["label"], entry["reason"], entry["by"]) for entry in unlocks],
                         [("candidate", "final check of the selected config", "tester")])  # fmt: skip

    def test_inputs_leave_the_blind_test_out_unless_unlocked(self):
        output = self.workspace.root / "inputs.jsonl"
        quiet(evaluate_splits.main, ["inputs", "--root", str(self.workspace.root), "--output", str(output)])
        self.assertNotIn(BLIND_TEST, {row["split"] for row in bakeoff.read_jsonl(output)})
        self.assertEqual({row["split"] for row in bakeoff.read_jsonl(output)}, {REAL_VAL, SYNTHETIC_VAL, BAKEOFF_REGRESSION})
        with self.assertRaises(SystemExit) as refusal:
            quiet(evaluate_splits.main, ["inputs", "--root", str(self.workspace.root), "--splits", BLIND_TEST, "--output", str(output)])
        self.assertIn("locked", str(refusal.exception))

    def test_the_audit_says_nothing_about_blind_lines(self):
        report = self.workspace.audit()
        self.assertNotIn(BLIND_TEST, report["sets"])
        self.assertEqual(set(report["blind_test"]), {"samples", "documents", "frozen", "content"})
        self.assertNotIn(BLIND_TEST, report["vietnamese_letters"]["covered"])
        self.assertNotIn(BLIND_TEST, {row["split"] for row in report["resize"]})
        self.assertNotIn(BLIND_TEST, next(iter(report["letter_counts"].values())))

    def test_freezing_the_blind_test(self):
        arguments = ["--directory", str(self.workspace.root), "--documents", str(self.workspace.documents_path),
                     "--annotation-dir", str(self.workspace.work_dir / "annotation"), "--lines", str(self.workspace.work_dir / "manifest.jsonl")]  # fmt: skip
        status, output = quiet(freeze_evaluation_set.main, [BLIND_TEST, *arguments])
        self.assertEqual(status, 0)
        frozen = dataset.load_frozen(BLIND_TEST, dataset.frozen_path(BLIND_TEST, self.workspace.root))
        self.assertEqual({(row["split"], row["frozen"], row["blind"]) for row in frozen}, {(BLIND_TEST, "true", "true")})
        self.assertEqual(len(frozen), 4)
        with self.assertRaises(SystemExit):
            quiet(freeze_evaluation_set.main, [BLIND_TEST, *arguments])  # never a second time
        # A blind line verified after the freeze does not slip into the frozen set.
        self.workspace.annotate(BLIND_TEST, ["b1"], 6)
        quiet(self.workspace.build)
        self.assertEqual(len(self.workspace.splits()[BLIND_TEST]), 4)
        report = self.workspace.audit()
        self.assertTrue(report["blind_test"]["frozen"])
        self.assertEqual(report["result"], "PASS")

    def test_only_blind_documents_can_be_frozen_as_blind_test(self):
        self.workspace.annotate(BLIND_TEST, ["b1", "t1"], 2)
        with self.assertRaises(SystemExit) as refusal:
            quiet(freeze_evaluation_set.main, [BLIND_TEST, "--directory", str(self.workspace.root), "--documents", str(self.workspace.documents_path),
                                               "--annotation-dir", str(self.workspace.work_dir / "annotation"),
                                               "--lines", str(self.workspace.work_dir / "manifest.jsonl")])  # fmt: skip
        self.assertIn("Not blind documents", str(refusal.exception))
        self.assertFalse(dataset.frozen_path(BLIND_TEST, self.workspace.root).exists())

    def test_every_look_at_the_real_blind_test_is_accounted_for(self):
        for entry in evaluate_splits.blind_test_unlocks():
            self.assertTrue(entry["reason"] and entry["by"] and entry["label"], entry)


class TrainingReadiness(unittest.TestCase):
    def test_the_gate_is_the_one_agreed(self):
        import audit_dataset

        self.assertEqual(audit_dataset.READINESS, {
            "real_train_verified": 400, "real_val_verified": 100, "blind_test_verified": 100,
            "train_documents": 6, "val_documents": 2, "blind_documents": 2,
        })  # fmt: skip

    def test_a_small_dataset_is_not_ready(self):
        workspace = Workspace(self, {"t1": ("train", 6), "v1": ("val", 6), "b1": ("blind", 6)})
        workspace.annotate(REAL_TRAIN, ["t1"], 4)
        workspace.annotate(REAL_VAL, ["v1"], 4)
        workspace.annotate(BLIND_TEST, ["b1"], 4)
        quiet(workspace.build)
        gate = workspace.audit()["readiness"]
        self.assertFalse(gate["ready"])
        self.assertEqual({name: c["found"] for name, c in gate["conditions"].items()}, {
            "real_train_verified": 4, "real_val_verified": 4, "blind_test_verified": 4,
            "train_documents": 1, "val_documents": 1, "blind_documents": 1, "no_document_or_image_leak": 0,
        })  # fmt: skip
        self.assertTrue(gate["conditions"]["no_document_or_image_leak"]["met"])

    def big(self) -> Workspace:
        documents = {f"t{i}": ("train", 70) for i in range(6)} | {f"v{i}": ("val", 55) for i in range(2)} | {f"b{i}": ("blind", 55) for i in range(2)}
        workspace = Workspace(self, documents)
        workspace.annotate(REAL_TRAIN, [f"t{i}" for i in range(6)], 67)   # 402 lines
        workspace.annotate(REAL_VAL, ["v0", "v1"], 50)                    # 100 lines
        workspace.annotate(BLIND_TEST, ["b0", "b1"], 50)                  # 100 lines
        quiet(workspace.build)
        return workspace

    def test_ready_when_every_condition_holds(self):
        report = self.big().audit()
        self.assertEqual(report["result"], "PASS")
        self.assertTrue(all(condition["met"] for condition in report["readiness"]["conditions"].values()))
        self.assertTrue(report["readiness"]["ready"])

    def test_one_missing_condition_is_enough_to_say_no(self):
        workspace = self.big()
        workspace.rewrite(REAL_VAL, lambda rows: rows.pop())  # 99 validation lines
        gate = workspace.audit()["readiness"]
        self.assertFalse(gate["conditions"]["real_val_verified"]["met"])
        self.assertFalse(gate["ready"])

    def test_a_leak_makes_a_large_dataset_not_ready(self):
        workspace = self.big()
        stray = workspace.splits()[BLIND_TEST][0]
        workspace.rewrite(REAL_TRAIN, lambda rows: rows.append({**stray, "id": "stray", "crop_sha256": "e" * 64, "split": REAL_TRAIN, "blind": "false"}))
        report = workspace.audit()
        self.assertFalse(report["readiness"]["conditions"]["no_document_or_image_leak"]["met"])
        self.assertFalse(report["readiness"]["ready"])

    def test_on_the_real_dataset_the_verdict_follows_the_counts(self):
        import audit_dataset

        report = audit_dataset.audit(dataset.DATASET_DIR, VOCABULARY, check_images=False)
        gate = report["readiness"]
        for name, required in audit_dataset.READINESS.items():
            self.assertEqual(gate["conditions"][name]["met"], gate["conditions"][name]["found"] >= required, name)
        self.assertEqual(gate["conditions"]["real_train_verified"]["found"],
                         sum(row["subset"] != "out_of_vocabulary" for row in dataset.read_splits()[REAL_TRAIN]))  # fmt: skip
        everything = all(condition["met"] for condition in gate["conditions"].values())
        self.assertEqual(gate["ready"], everything and report["result"] == "PASS")


class TrainingCodeLivesInOnePlace(unittest.TestCase):
    def test_only_the_training_wrapper_takes_gradient_steps(self):
        forbidden = re.compile(r"\.backward\(|optimizer\.step\(|\.train\(\)")
        found = [path.name for path in sorted(dataset.DATASET_DIR.glob("*.py")) if forbidden.search(path.read_text(encoding="utf-8"))]
        self.assertEqual(found, ["train_vietocr.py"])

    def test_nothing_calls_the_vendored_or_the_pinned_trainer(self):
        forbidden = re.compile(r"\bTrainer\(|tools/train\.py|from vietocr\.model\.trainer|import vietocr\.model\.trainer")
        for path in sorted(dataset.DATASET_DIR.glob("*.py")):
            self.assertIsNone(forbidden.search(path.read_text(encoding="utf-8")), path.name)


if __name__ == "__main__":
    unittest.main()
