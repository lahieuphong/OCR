"""The annotation table, the session rules, and the two front ends of annotate.py."""

import json
import tempfile
import threading
import unicodedata
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import _paths  # noqa: F401
import annotate
import annotation_server
import bakeoff_common as bakeoff
from annotation_store import SKIP_REASONS, ActionError, AnnotationStore, annotation_order, normalise


def blank_row(key: str, document: str = "d", page: int = 1, **changes) -> dict:
    row = {
        "id": key, "document": document, "page": str(page), "crop_path": f"{key}.png",
        "ppocr_prediction": "Vit Nam", "vietocr_prediction": "Việt Nam",
        "ground_truth": "", "verified": "false", **dict.fromkeys(bakeoff.REVIEW_COLUMNS, ""),
    }  # fmt: skip
    row.update(changes)
    return row


class TableFile(unittest.TestCase):
    """Base class: a table on disk plus a store reading it."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.table, self.log = self.root / "manifest.tsv", self.root / "annotation_log.jsonl"

    def store(self, rows: list[dict] | None = None, **options) -> AnnotationStore:
        if rows is not None:
            bakeoff.write_annotation(self.table, rows)
        ticks = iter(range(10_000))
        options.setdefault("clock", lambda: f"2026-01-01T00:00:{next(ticks) % 60:02d}+00:00")
        return AnnotationStore(self.table, self.log, options.pop("annotator", "tester"), **options)

    def saved(self) -> dict[str, dict]:
        return {row["id"]: row for row in bakeoff.read_annotation(self.table)}

    def log_entries(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class AnnotationTable(TableFile):
    def test_round_trip_keeps_quotes_and_unicode(self):
        rows = [blank_row("a", ppocr_prediction='He said "x"', vietocr_prediction="ệ, 'y'"),
                blank_row("b", ground_truth='"Việt" Nam', verified="true")]  # fmt: skip
        bakeoff.write_annotation(self.table, rows)
        self.assertEqual(bakeoff.read_annotation(self.table), rows)
        header = self.table.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header, "\t".join(bakeoff.ANNOTATION_COLUMNS))

    def test_tab_in_a_field_is_refused(self):
        with self.assertRaises(ValueError):
            bakeoff.write_annotation(self.table, [blank_row("a", ground_truth="a\tb")])

    def test_table_from_before_the_review_columns_is_upgraded(self):
        legacy = ["\t".join(bakeoff.SELECTION_COLUMNS), "a\td\t1\ta.png\tVit Nam\tViệt Nam\t\tfalse"]
        self.table.write_text("\n".join(legacy) + "\n", encoding="utf-8")
        self.assertEqual(bakeoff.read_annotation(self.table), [blank_row("a")])
        store = self.store()
        store.accept("a", bakeoff.VIETOCR)
        self.assertEqual(
            self.table.read_text(encoding="utf-8").splitlines()[0], "\t".join(bakeoff.ANNOTATION_COLUMNS)
        )

    def test_row_states(self):
        pending, verified = blank_row("a"), blank_row("b", ground_truth="x", verified="true")
        excluded = blank_row("c", excluded_reason="stamp")
        self.assertEqual([bakeoff.is_pending(r) for r in (pending, verified, excluded)], [True, False, False])
        self.assertEqual([bakeoff.is_verified(r) for r in (pending, verified, excluded)], [False, True, False])
        self.assertEqual([bakeoff.is_excluded(r) for r in (pending, verified, excluded)], [False, False, True])


class Order(unittest.TestCase):
    def test_documents_pages_and_strata_alternate(self):
        rows, selection = [], {}
        for document, pages in (("a", (1, 2)), ("b", (1,)), ("c", (1,))):
            for page in pages:
                for line in range(4):
                    key = f"{document}{page}{line}"
                    rows.append(blank_row(key, document, page))
                    selection[key] = {"selected_by": "header" if line < 2 else "body", "tags": []}
        order = annotation_order(rows, selection)
        self.assertEqual(sorted(order), sorted(row["id"] for row in rows))
        # Every document within the first three rows, every page within the first four of "a".
        self.assertEqual({key[0] for key in order[:3]}, {"a", "b", "c"})
        first_of_a = [key for key in order if key[0] == "a"][:2]
        self.assertEqual({key[1] for key in first_of_a}, {"1", "2"})
        # Within a page the strata alternate: header, body, header, body.
        self.assertEqual([key for key in order if key.startswith("b1")], ["b10", "b12", "b11", "b13"])

    def test_order_is_deterministic(self):
        rows = [blank_row(f"k{index}", "d", 1 + index % 3) for index in range(12)]
        self.assertEqual(annotation_order(rows, {}), annotation_order(list(reversed(rows))[::-1], {}))


class Actions(TableFile):
    def test_accepting_a_prediction_records_who_when_and_how(self):
        store = self.store([blank_row("a"), blank_row("b")])
        store.accept("a", bakeoff.VIETOCR)
        row = self.saved()["a"]
        self.assertEqual((row["ground_truth"], row["verified"]), ("Việt Nam", "true"))
        self.assertEqual(row["ground_truth_source"], "vietocr_accepted")
        self.assertEqual(row["annotator"], "tester")
        self.assertTrue(row["verified_at"].startswith("2026-01-01T"))
        self.assertEqual(row["ground_truth_sha256"], bakeoff.text_sha256("Việt Nam"))
        self.assertEqual(self.saved()["b"]["verified"], "false")

    def test_accepting_ppocr_uses_the_ppocr_text(self):
        store = self.store([blank_row("a")])
        store.accept("a", bakeoff.PPOCR)
        row = self.saved()["a"]
        self.assertEqual((row["ground_truth"], row["ground_truth_source"]), ("Vit Nam", "ppocr_accepted"))

    def test_typed_text_is_stored_in_nfc_and_the_keystrokes_are_logged(self):
        store = self.store([blank_row("a")])
        typed = unicodedata.normalize("NFD", "  Việt Nam ")
        store.enter("a", typed)
        row = self.saved()["a"]
        self.assertEqual(row["ground_truth"], "Việt Nam")
        self.assertTrue(unicodedata.is_normalized("NFC", row["ground_truth"]))
        self.assertEqual(row["ground_truth_source"], "typed")
        self.assertEqual(row["ground_truth_sha256"], bakeoff.text_sha256("Việt Nam"))
        entry = self.log_entries()[-1]
        self.assertEqual((entry["action"], entry["raw_input"], entry["ground_truth"]), ("enter", typed, "Việt Nam"))

    def test_empty_or_broken_text_is_refused(self):
        store = self.store([blank_row("a")])
        for bad in ("", "   ", "a\tb", "a\nb"):
            with self.assertRaises(ActionError):
                store.enter("a", bad)
        self.assertEqual(self.saved()["a"]["verified"], "false")
        self.assertFalse(self.log.exists())

    def test_an_empty_prediction_cannot_be_accepted(self):
        store = self.store([blank_row("a", ppocr_prediction="")])
        with self.assertRaises(ActionError):
            store.accept("a", bakeoff.PPOCR)

    def test_skipped_row_is_excluded_not_verified(self):
        store = self.store([blank_row("a"), blank_row("b")])
        store.skip("a", "stamp")
        row = self.saved()["a"]
        self.assertEqual((row["verified"], row["excluded_reason"], row["ground_truth"]), ("false", "stamp", ""))
        self.assertTrue(bakeoff.is_excluded(row))
        self.assertEqual(store.current()["id"], "b")
        with self.assertRaises(ActionError):
            store.skip("b", "because")

    def test_only_the_current_row_can_be_changed(self):
        store = self.store([blank_row("a"), blank_row("b")])
        store.accept("a", bakeoff.VIETOCR)
        # A second click on the same button must not overwrite "a" or hit "b".
        with self.assertRaises(ActionError):
            store.accept("a", bakeoff.PPOCR)
        self.assertEqual(self.saved()["a"]["ground_truth_source"], "vietocr_accepted")
        self.assertEqual(self.saved()["b"]["verified"], "false")

    def test_undo_restores_the_row(self):
        store = self.store([blank_row("a"), blank_row("b")])
        store.accept("a", bakeoff.VIETOCR)
        store.undo()
        self.assertEqual(self.saved()["a"], blank_row("a"))
        self.assertEqual(store.current()["id"], "a")
        with self.assertRaises(ActionError):
            store.undo()
        self.assertEqual([entry["action"] for entry in self.log_entries()], ["accept_vietocr", "undo"])


class SaveAndResume(TableFile):
    def rows(self) -> list[dict]:
        return [blank_row(f"k{index}") for index in range(6)]

    def test_every_action_is_on_disk_before_the_next_one(self):
        store = self.store(self.rows())
        first = store.current()["id"]
        store.accept(first, bakeoff.VIETOCR)
        self.assertEqual(self.saved()[first]["verified"], "true")
        second = store.current()["id"]
        store.skip(second, "unreadable")
        self.assertEqual(self.saved()[second]["excluded_reason"], "unreadable")

    def test_a_new_session_resumes_at_the_next_pending_row(self):
        store = self.store(self.rows())
        done = []
        for action in ("accept", "skip", "enter"):
            key = store.current()["id"]
            done.append(key)
            if action == "accept":
                store.accept(key, bakeoff.VIETOCR)
            elif action == "skip":
                store.skip(key, "handwriting")
            else:
                store.enter(key, "Việt Nam!")
        expected_next = store.current()["id"]
        del store  # the terminal was closed

        resumed = self.store()
        self.assertEqual(resumed.current()["id"], expected_next)
        self.assertNotIn(expected_next, done)
        progress = resumed.progress()
        self.assertEqual((progress["verified"], progress["skipped"], progress["pending"]), (2, 1, 3))
        self.assertFalse(progress["can_undo"])  # undo never reaches into an earlier session

    def test_a_verified_row_is_only_reopened_by_name(self):
        rows = self.rows()
        store = self.store(rows)
        key = store.current()["id"]
        store.enter(key, "first version")
        again = self.store(only_ids=[key])
        self.assertEqual(again.current()["id"], key)
        again.enter(key, "second version")
        self.assertIsNone(again.current())
        self.assertEqual(self.saved()[key]["ground_truth"], "second version")
        self.assertEqual(self.saved()[key]["ground_truth_sha256"], bakeoff.text_sha256("second version"))

    def test_unknown_id_is_rejected(self):
        with self.assertRaises(SystemExit):
            self.store(self.rows(), only_ids=["nope"])


class Recheck(TableFile):
    def rows(self) -> list[dict]:
        return [
            blank_row("a", ground_truth="Việt Nam", verified="true", ground_truth_source="vietocr_accepted"),
            blank_row("b", ground_truth="gõ tay", verified="true", ground_truth_source="typed"),
            blank_row("c", ground_truth="Việt Nam", verified="true", ground_truth_source="vietocr_accepted"),
            blank_row("d"),
        ]

    def test_lines_verified_one_way_are_reopened_and_nothing_else(self):
        bakeoff.write_annotation(self.table, self.rows())
        self.assertEqual(annotate.rows_to_reopen(self.table, None, "vietocr_accepted"), ["a", "c"])
        self.assertEqual(annotate.rows_to_reopen(self.table, ["b"], "vietocr_accepted"), ["b", "a", "c"])
        self.assertIsNone(annotate.rows_to_reopen(self.table, None, None))
        with self.assertRaises(SystemExit):
            annotate.rows_to_reopen(self.table, None, "ppocr_accepted")

    def test_a_rechecked_line_can_be_corrected_or_confirmed(self):
        store = self.store(self.rows(), only_ids=["a", "c"])
        self.assertEqual(store.current()["ground_truth"], "Việt Nam")  # shown for editing
        store.enter("a", "VIỆT NAM")
        store.accept("c", bakeoff.VIETOCR)
        self.assertIsNone(store.current())
        saved = self.saved()
        self.assertEqual((saved["a"]["ground_truth"], saved["a"]["ground_truth_source"]), ("VIỆT NAM", "typed"))
        self.assertEqual(saved["a"]["ground_truth_sha256"], bakeoff.text_sha256("VIỆT NAM"))
        self.assertEqual(saved["c"]["ground_truth_source"], "vietocr_accepted")
        self.assertEqual(saved["b"]["ground_truth"], "gõ tay")
        self.assertEqual(saved["d"], blank_row("d"))


class TargetAndCoverage(TableFile):
    def build(self) -> tuple[list[dict], dict]:
        rows, selection = [], {}
        for document in ("a", "b", "c"):
            for line in range(6):
                key = f"{document}{line}"
                rows.append(blank_row(key, document))
                selection[key] = {"selected_by": "body", "tags": ["body"]}
        # One line is also a header, and nothing in the order brings it forward:
        # it is the last line of the last document.
        selection["c5"] = {"selected_by": "body", "tags": ["body", "header"]}
        return rows, selection

    def verify_until_done(self, store: AnnotationStore) -> list[str]:
        seen = []
        while (row := store.current()) is not None:
            seen.append(row["id"])
            store.accept(row["id"], bakeoff.VIETOCR)
        return seen

    def test_session_stops_at_the_target(self):
        rows, _ = self.build()
        store = self.store(rows, target=5)
        self.assertEqual(len(self.verify_until_done(store)), 5)
        self.assertIn("5 verified readable lines reached", store.stop_reason())

    def test_first_lines_cover_every_document(self):
        rows, selection = self.build()
        store = self.store(rows, target=6, selection=selection)
        self.assertEqual({key[0] for key in self.verify_until_done(store)[:3]}, {"a", "b", "c"})

    def test_skipped_lines_do_not_count_towards_the_target(self):
        rows, _ = self.build()
        store = self.store(rows, target=4)
        for _ in range(3):
            store.skip(store.current()["id"], "unreadable")
        self.assertEqual(len(self.verify_until_done(store)), 4)
        self.assertEqual((store.progress()["verified"], store.progress()["skipped"]), (4, 3))

    def test_session_goes_on_until_a_missing_kind_of_line_is_covered(self):
        rows, selection = self.build()
        store = self.store(rows, target=3, selection=selection)
        seen = self.verify_until_done(store)
        # Three lines reach the target, but the only header line is not among
        # them: the session continues with exactly that line, then stops.
        self.assertEqual(len(seen), 4)
        self.assertEqual(seen[-1], "c5")
        self.assertEqual(store.progress()["missing_coverage"], [])

    def test_a_kind_that_was_skipped_entirely_does_not_block_the_end(self):
        rows, selection = self.build()
        store = self.store(rows, target=3, selection=selection)
        for _ in range(3):
            store.accept(store.current()["id"], bakeoff.VIETOCR)
        self.assertEqual(store.current()["id"], "c5")
        store.skip("c5", "stamp")
        self.assertIsNone(store.current())
        self.assertEqual(store.progress()["missing_coverage"], ["header"])

    def test_quit_stops_the_session(self):
        rows, _ = self.build()
        store = self.store(rows)
        store.stop()
        self.assertIsNone(store.current())


class DuplicateOfAFrozenImage(TableFile):
    """A readable crop whose file is also a frozen evaluation line: set aside by a person, with its own reason."""

    REASON = "duplicate_frozen_image"

    def rows(self) -> list[dict]:
        done = {"ground_truth": "Việt Nam", "verified": "true", "ground_truth_source": "typed", "annotator": "tester",
                "verified_at": "2026-01-01T00:00:00+00:00", "ground_truth_sha256": bakeoff.text_sha256("Việt Nam")}  # fmt: skip
        return [blank_row(key, **done) for key in "ab"] + [blank_row(key) for key in "cdef"]

    def test_it_is_an_official_reason_with_its_label(self):
        self.assertEqual(SKIP_REASONS[self.REASON], "ảnh crop trùng byte với một dòng trong tập đánh giá đã đóng băng")
        # Appended after the others: the numbers of the older reasons in the menu keep their meaning.
        self.assertEqual(list(SKIP_REASONS), ["handwriting", "stamp", "unreadable", "bad_crop", "unsure", self.REASON])

    def test_skipping_with_it_sets_the_row_aside(self):
        store = self.store([blank_row("a"), blank_row("b")])
        store.skip("a", self.REASON)
        saved = self.saved()["a"]
        self.assertEqual((saved["verified"], saved["excluded_reason"], saved["ground_truth"]), ("false", self.REASON, ""))
        self.assertEqual(saved["annotator"], "tester")
        self.assertTrue(bakeoff.is_excluded(saved))
        self.assertFalse(bakeoff.is_verified(saved) or bakeoff.is_pending(saved))
        entry = self.log_entries()[-1]
        self.assertEqual((entry["id"], entry["action"], entry["excluded_reason"]), ("a", "skip", self.REASON))
        self.assertEqual(store.current()["id"], "b")
        self.assertEqual(store.progress()["skipped"], 1)

    def test_a_misspelt_reason_is_refused_and_saves_nothing(self):
        store = self.store([blank_row("a")])
        for wrong in ("duplicate", "duplicate_frozen", "DUPLICATE_FROZEN_IMAGE", ""):
            with self.assertRaises(ActionError):
                store.skip("a", wrong)
        self.assertEqual(self.saved()["a"], blank_row("a"))
        self.assertFalse(self.log.exists())

    def test_no_row_is_set_aside_unless_a_person_does_it(self):
        self.store(self.rows())
        before = self.table.read_bytes()
        # Opening a session, ordinary or by name, and looking at its state changes nothing.
        for options in ({}, {"target": 2}, {"only_ids": ["a", "b"]}, {"show_predictions": False}):
            store = self.store(**options)
            store.current(), store.progress(), store.stop_reason()
        self.assertEqual(self.table.read_bytes(), before)
        self.assertFalse(self.log.exists())
        # And the reason applies to the one row on screen, never to another row or to several.
        store = self.store()
        self.assertEqual(store.current()["id"], "c")
        with self.assertRaises(ActionError):
            store.skip("a", self.REASON)
        self.assertEqual(self.table.read_bytes(), before)

    def test_a_verified_row_reopened_by_name_can_be_set_aside(self):
        store = self.store(self.rows(), only_ids=["a", "b"], target=2)
        self.assertEqual(store.progress()["verified"], 2)
        self.assertEqual(store.current()["id"], "a")
        store.skip("a", self.REASON)
        self.assertEqual(store.current()["id"], "b")
        store.skip("b", self.REASON)
        self.assertIsNone(store.current())
        self.assertEqual(store.stop_reason(), "the requested rows are done")
        progress = store.progress()
        self.assertEqual((progress["verified"], progress["skipped"], progress["pending"]), (0, 2, 4))
        saved = self.saved()
        for key in "ab":
            self.assertEqual((saved[key]["verified"], saved[key]["excluded_reason"], saved[key]["ground_truth"],
                              saved[key]["ground_truth_sha256"]), ("false", self.REASON, "", ""))  # fmt: skip
        self.assertEqual({key: saved[key] for key in "cdef"}, {key: blank_row(key) for key in "cdef"})

    def test_undo_brings_the_verified_label_back(self):
        store = self.store(self.rows(), only_ids=["a"])
        before = dict(self.saved()["a"])
        store.skip("a", self.REASON)
        self.assertEqual(self.saved()["a"]["excluded_reason"], self.REASON)
        store.undo()
        self.assertEqual(self.saved()["a"], before)
        self.assertEqual(store.current()["id"], "a")

    def test_an_ordinary_session_then_verifies_replacements_up_to_the_target(self):
        reopened = self.store(self.rows(), only_ids=["a", "b"], target=2)
        reopened.skip("a", self.REASON)
        reopened.skip("b", self.REASON)
        session = self.store(target=2)
        shown = []
        while (row := session.current()) is not None:
            shown.append(row["id"])
            session.enter(row["id"], "Việt Nam")
        self.assertEqual(len(shown), 2)  # exactly as many as were set aside
        self.assertEqual(set(shown) & {"a", "b"}, set())  # a row set aside is not offered again
        progress = session.progress()
        self.assertEqual((progress["verified"], progress["skipped"], progress["pending"]), (2, 2, 2))
        self.assertEqual(session.stop_reason(), "2 verified readable lines reached")

    def test_the_terminal_menu_offers_it(self):
        store = self.store([blank_row("a"), blank_row("b")])
        replies, shown = iter(["s", str(len(SKIP_REASONS)), "q"]), []
        annotate.run_cli(store, lambda row: Path("crops") / row["crop_path"], ask=lambda prompt: next(replies),
                         say=shown.append, opener=lambda path: None)  # fmt: skip
        self.assertIn(f"  [{len(SKIP_REASONS)}] {SKIP_REASONS[self.REASON]}", shown)
        self.assertEqual((self.saved()["a"]["verified"], self.saved()["a"]["excluded_reason"]), ("false", self.REASON))
        self.assertEqual(self.saved()["b"], blank_row("b"))

    def test_the_browser_page_offers_it(self):
        (self.root / "a.png").write_bytes(b"crop")
        app = annotation_server.AnnotationApp(self.store([blank_row("a"), blank_row("b")]), lambda row: self.root / row["crop_path"])
        self.assertEqual(app.state()["skip_reasons"][self.REASON], SKIP_REASONS[self.REASON])
        state = app.act({"id": "a", "action": "skip", "reason": self.REASON})
        self.assertEqual((state["item"]["id"], state["progress"]["skipped"]), ("b", 1))
        self.assertEqual(self.saved()["a"]["excluded_reason"], self.REASON)


class TerminalFrontEnd(TableFile):
    def run_cli(self, answers: list[str], rows: list[dict] | None = None, **options):
        store = self.store(rows if rows is not None else [blank_row("a"), blank_row("b")], **options)
        replies, shown, opened = iter(answers), [], []

        def ask(prompt: str) -> str:
            try:
                return next(replies)
            except StopIteration:
                raise EOFError from None  # what input() raises when the terminal closes

        annotate.run_cli(
            store, lambda row: Path("crops") / row["crop_path"], ask=ask, say=shown.append, opener=opened.append
        )
        return store, "\n".join(shown), opened

    def test_screen_shows_the_fields_and_the_menu(self):
        _, screen, _ = self.run_cli(["q"])
        for expected in ("ID:\na", "Document:\nd", "Page:\n1", "PP-OCRv6:\nVit Nam", "VietOCR:\nViệt Nam",
                         "Image:\ncrops/a.png", "[p] accept PP-OCRv6 text", "[v] accept VietOCR text",
                         "[e] enter/edit exact ground truth", "[s] skip this line", "[q] save and quit"):  # fmt: skip
            self.assertIn(expected, screen)

    def test_enter_alone_accepts_nothing(self):
        store, screen, _ = self.run_cli(["", "", "q"])
        self.assertEqual(store.progress()["verified"], 0)
        self.assertEqual(self.saved()["a"], blank_row("a"))
        self.assertIn("Nothing was saved", screen)

    def test_p_and_v_verify_with_that_text(self):
        self.run_cli(["p", "v"])
        saved = self.saved()
        self.assertEqual((saved["a"]["ground_truth"], saved["a"]["ground_truth_source"]), ("Vit Nam", "ppocr_accepted"))
        self.assertEqual((saved["b"]["ground_truth"], saved["b"]["ground_truth_source"]), ("Việt Nam", "vietocr_accepted"))

    def test_e_needs_typed_text_and_a_confirmation(self):
        self.run_cli(["e", "Viet Nam", "r", "Việt Nam.", "y", "e", "", "e", "abc", "c", "q"])
        saved = self.saved()
        self.assertEqual((saved["a"]["ground_truth"], saved["a"]["ground_truth_source"]), ("Việt Nam.", "typed"))
        self.assertEqual(saved["b"], blank_row("b"))  # empty text, then a cancelled one

    def test_s_asks_for_a_reason(self):
        self.run_cli(["s", "", "s", "2", "q"])
        saved = self.saved()
        self.assertEqual((saved["a"]["verified"], saved["a"]["excluded_reason"]), ("false", "stamp"))

    def test_o_opens_the_image_only_on_request(self):
        _, _, opened = self.run_cli(["p", "o", "q"])
        self.assertEqual(opened, [Path("crops/b.png")])

    def test_u_undoes_and_q_keeps_what_was_saved(self):
        rows = [blank_row("a"), blank_row("b"), blank_row("c")]
        store, _, _ = self.run_cli(["v", "v", "u", "q"], rows)
        self.assertEqual(store.progress()["verified"], 1)
        self.assertEqual(self.saved()["b"], blank_row("b"))
        self.assertEqual(store.current(), None)

    def test_closed_terminal_loses_nothing(self):
        store, _, _ = self.run_cli(["v"])  # input ends while "b" is on screen
        self.assertEqual(self.saved()["a"]["verified"], "true")
        self.assertEqual(store.stop_reason(), "stopped by the annotator")

    def test_session_ends_by_itself_at_the_target(self):
        rows = [blank_row(f"k{index}") for index in range(5)]
        store, _, _ = self.run_cli(["v"] * 5, rows, target=2)
        self.assertEqual(store.progress()["verified"], 2)


class BrowserFrontEnd(TableFile):
    def setUp(self):
        super().setUp()
        (self.root / "a.png").write_bytes(b"\x89PNG crop a")
        self.app = annotation_server.AnnotationApp(
            self.store([blank_row("a"), blank_row("b")], target=2), lambda row: self.root / row["crop_path"]
        )
        self.finished = threading.Event()
        hosts: set[str] = set()
        self.server = annotation_server.ThreadingHTTPServer(
            (annotation_server.HOST, 0), annotation_server.make_handler(self.app, hosts, self.finished.set)
        )
        self.port = self.server.server_address[1]
        hosts.add(f"127.0.0.1:{self.port}")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path: str, body: dict | None = None, **headers):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def post(self, body: dict, token: str | None = None):
        status, payload = self.request(
            "/api/action", body, **{"Content-Type": "application/json", "X-Annotation-Token": token or self.app.token}
        )
        return status, json.loads(payload)

    def test_page_carries_the_token_and_the_five_actions(self):
        status, page = self.request("/")
        text = page.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn(self.app.token, text)
        self.assertNotIn("__TOKEN__", text)
        for action in ("accept_ppocr", "accept_vietocr", '"enter"', '"skip"', '"quit"'):
            self.assertIn(action, text)

    def test_state_and_crop(self):
        status, payload = self.request("/api/state")
        state = json.loads(payload)
        self.assertEqual((status, state["item"]["id"], state["done"]), (200, "a", False))
        self.assertEqual((state["item"]["ppocr"], state["item"]["vietocr"]), ("Vit Nam", "Việt Nam"))
        self.assertEqual(self.request(state["item"]["image"]), (200, b"\x89PNG crop a"))
        self.assertEqual(self.request("/crop/..%2Fmanifest.tsv")[0], 404)

    def test_changes_need_the_token_of_the_page(self):
        status, _ = self.post({"id": "a", "action": "accept_vietocr"}, token="guess")
        self.assertEqual(status, 403)
        self.assertEqual(self.saved()["a"]["verified"], "false")

    def test_requests_under_another_host_name_are_refused(self):
        self.assertEqual(self.request("/api/state", Host="evil.example")[0], 403)

    def test_actions_save_and_the_session_ends_at_the_target(self):
        status, state = self.post({"id": "a", "action": "enter", "text": "Việt Nam,"})
        self.assertEqual((status, state["item"]["id"], state["progress"]["verified"]), (200, "b", 1))
        self.assertEqual(self.saved()["a"]["ground_truth"], "Việt Nam,")
        self.assertFalse(self.finished.is_set())

        status, state = self.post({"id": "a", "action": "accept_ppocr"})  # stale: "a" is done
        self.assertEqual((status, state["item"]["id"]), (409, "b"))
        self.assertIn("error", state)
        self.assertEqual(self.saved()["a"]["ground_truth"], "Việt Nam,")

        status, state = self.post({"id": "b", "action": "accept_vietocr"})
        self.assertEqual((status, state["done"], state["progress"]["verified"]), (200, True, 2))
        self.assertTrue(self.finished.wait(2))

    def test_skip_undo_and_quit(self):
        _, state = self.post({"id": "a", "action": "skip", "reason": "handwriting"})
        self.assertEqual((state["item"]["id"], state["progress"]["skipped"]), ("b", 1))
        _, state = self.post({"id": "b", "action": "undo"})
        self.assertEqual((state["item"]["id"], state["progress"]["skipped"]), ("a", 0))
        _, state = self.post({"id": "a", "action": "quit"})
        self.assertTrue(state["done"])
        self.assertEqual(self.saved()["a"], blank_row("a"))

    def test_empty_text_is_an_error_not_a_save(self):
        status, state = self.post({"id": "a", "action": "enter", "text": "  "})
        self.assertEqual((status, state["item"]["id"]), (409, "a"))
        self.assertEqual(self.saved()["a"]["verified"], "false")


class Normalisation(unittest.TestCase):
    def test_nfc_and_trimmed(self):
        self.assertEqual(normalise(unicodedata.normalize("NFD", " Việt  Nam ")), "Việt  Nam")


if __name__ == "__main__":
    unittest.main()
