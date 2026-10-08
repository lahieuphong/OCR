"""State of an annotation session: which crop comes next and what a decision records.

Shared by the browser and the terminal front end of ``annotate.py``. Nothing in
here decides what the ground truth is. Every way of verifying a row is an
action a person takes on that row; the table is saved after each one.
"""

from __future__ import annotations

import json
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import bakeoff_common as bakeoff

TARGET_VERIFIED = 100
# Recognizer -> prefix of its prediction column in the annotation table.
PREDICTION_COLUMN = {bakeoff.PPOCR: "ppocr_prediction", bakeoff.VIETOCR: "vietocr_prediction"}
ACCEPTED_SOURCE = {bakeoff.PPOCR: "ppocr_accepted", bakeoff.VIETOCR: "vietocr_accepted"}
TYPED_SOURCE = "typed"
# Why a person set a crop aside. Such a row is never scored.
SKIP_REASONS = {
    "handwriting": "chữ ký tay hoặc chữ viết tay",
    "stamp": "con dấu che chữ",
    "unreadable": "không đọc được chắc chắn",
    "bad_crop": "crop lỗi nặng hoặc không có chữ",
    "unsure": "không xác định được ground truth đáng tin",
}
# Kinds of line the verified set must contain before a session may stop, where
# the table has any. Judged from the predictions, like the sampling strata.
COVERAGE_TAGS = ("header", "body", "digits_symbols", "long_line", "short_line", "missing_chars", "random")
SHORT_LINE_MAX_CHARACTERS = 30
STRATUM_ORDER = (
    "header", "small_text", "digits_symbols", "long_line",
    "complex_diacritics", "missing_chars", "body", "random",
)  # fmt: skip


class ActionError(ValueError):
    """An action that cannot be applied; the message is shown to the annotator."""


def normalise(raw: str) -> str:
    """Ground truth as stored: Unicode NFC, without leading or trailing whitespace."""
    return unicodedata.normalize("NFC", raw.strip())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_selection(path: Path) -> dict[str, dict]:
    """Per row: the stratum that selected it and its tags (empty without the file)."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["lines"]


def interleave(queues: list[list]) -> list:
    """One item from each queue in turn, until all are empty."""
    queues = [list(queue) for queue in queues]
    merged = []
    while any(queues):
        for queue in queues:
            if queue:
                merged.append(queue.pop(0))
    return merged


def annotation_order(rows: list[dict], selection: dict[str, dict]) -> list[str]:
    """Row ids in the order they are shown.

    Documents alternate, pages alternate within a document and sampling strata
    alternate within a page. Any prefix of this order is therefore spread over
    documents, pages and kinds of line, so stopping at a target does not leave
    the last document unseen.
    """

    def rank(stratum: str) -> int:
        return STRATUM_ORDER.index(stratum) if stratum in STRATUM_ORDER else len(STRATUM_ORDER)

    pages: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for row in rows:
        stratum = selection.get(row["id"], {}).get("selected_by", "")
        pages[row["document"]][row["page"]][stratum].append(row["id"])
    return interleave(
        [
            interleave(
                [
                    interleave([strata[name] for name in sorted(strata, key=rank)])
                    for _, strata in sorted(document_pages.items(), key=lambda item: int(item[0]))
                ]
            )
            for _, document_pages in sorted(pages.items())
        ]
    )


def row_categories(row: dict, selection: dict[str, dict]) -> set[str]:
    """What verifying this row adds to the coverage of the verified set."""
    line = selection.get(row["id"], {})
    categories = {f"document {row['document']}", f"page {row['document']} p{row['page']}"}
    categories.update(tag for tag in line.get("tags", ()) if tag in COVERAGE_TAGS)
    if line.get("selected_by") == "random":
        categories.add("random")
    if max(len(row["ppocr_prediction"]), len(row["vietocr_prediction"])) <= SHORT_LINE_MAX_CHARACTERS:
        categories.add("short_line")
    return categories


class AnnotationStore:
    """The annotation table plus the rules for moving through it."""

    def __init__(
        self,
        table_path: Path,
        log_path: Path,
        annotator: str,
        *,
        target: int = TARGET_VERIFIED,
        selection: dict[str, dict] | None = None,
        only_ids: list[str] | None = None,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        if not annotator.strip():
            raise SystemExit("An annotator name is required.")
        self.table_path, self.log_path = table_path, log_path
        self.annotator, self.target, self.clock = annotator.strip(), target, clock
        self.selection = selection or {}
        self.rows = bakeoff.read_annotation(table_path)
        self.by_id = {row["id"]: row for row in self.rows}
        self.order = annotation_order(self.rows, self.selection)
        # Rows named explicitly are shown whatever their state: that is the
        # only way a verified ground truth can be changed.
        self.only_ids = only_ids
        if only_ids:
            unknown = sorted(set(only_ids) - set(self.by_id))
            if unknown:
                raise SystemExit(f"Not in {table_path}: {', '.join(unknown)}")
        self.handled: list[str] = []
        self.history: list[tuple[str, dict]] = []
        self.stopped = False

    # --- where the session stands -------------------------------------------

    def verified(self) -> list[dict]:
        return [row for row in self.rows if bakeoff.is_verified(row)]

    def missing_coverage(self) -> set[str]:
        required = set().union(*(row_categories(row, self.selection) for row in self.rows))
        covered = set().union(set(), *(row_categories(row, self.selection) for row in self.verified()))
        return required - covered

    def current(self) -> dict | None:
        """The row to show next, or None when the session is over."""
        if self.stopped:
            return None
        if self.only_ids:
            remaining = [key for key in self.only_ids if key not in self.handled]
            return self.by_id[remaining[0]] if remaining else None

        pending = [self.by_id[key] for key in self.order if bakeoff.is_pending(self.by_id[key])]
        if len(self.verified()) < self.target:
            return pending[0] if pending else None
        # Target reached: go on only for rows that fill a gap in the coverage.
        missing = self.missing_coverage()
        return next((row for row in pending if row_categories(row, self.selection) & missing), None)

    def progress(self) -> dict:
        verified = self.verified()
        skipped = sum(bakeoff.is_excluded(row) for row in self.rows)
        return {
            "selected": len(self.rows),
            "verified": len(verified),
            "skipped": skipped,
            "inspected": len(verified) + skipped,
            "pending": sum(bakeoff.is_pending(row) for row in self.rows),
            "target": self.target,
            "documents": len({row["document"] for row in verified}),
            "pages": len({(row["document"], row["page"]) for row in verified}),
            "missing_coverage": sorted(self.missing_coverage()),
            "can_undo": bool(self.history),
        }

    def stop_reason(self) -> str:
        progress = self.progress()
        if self.stopped:
            return "stopped by the annotator"
        if self.only_ids:
            return "the requested rows are done"
        if progress["verified"] >= self.target:
            return f"{progress['verified']} verified readable lines reached"
        return "no line left to annotate"

    # --- what a person can do with the current row --------------------------

    def accept(self, row_id: str, recognizer: str) -> dict:
        """The annotator states that this recognizer's text matches the crop exactly."""
        row = self._current_row(row_id)
        text = row[PREDICTION_COLUMN[recognizer]]
        if not normalise(text):
            raise ActionError("That prediction is empty; type the text or skip the line.")
        return self._verify(row, text, ACCEPTED_SOURCE[recognizer], f"accept_{recognizer}")

    def enter(self, row_id: str, raw: str) -> dict:
        """The annotator typed (or edited) the exact text of the crop."""
        row = self._current_row(row_id)
        if any(separator in raw for separator in "\t\r\n"):
            raise ActionError("The text contains a tab or a line break; remove it.")
        if not normalise(raw):
            raise ActionError("Nothing was typed. Type the text of the crop, or skip the line.")
        return self._verify(row, raw, TYPED_SOURCE, "enter")

    def skip(self, row_id: str, reason: str) -> dict:
        """Set the row aside: it stays unverified and is never scored."""
        row = self._current_row(row_id)
        if reason not in SKIP_REASONS:
            raise ActionError(f"Choose a reason: {', '.join(SKIP_REASONS)}.")
        self._remember(row)
        row.update(
            {
                "ground_truth": "",
                "verified": "false",
                "excluded_reason": reason,
                "ground_truth_source": "",
                "annotator": self.annotator,
                "verified_at": "",
                "ground_truth_sha256": "",
            }
        )
        self._save(row, "skip", raw="")
        return row

    def undo(self) -> dict:
        """Take back the latest action of this session."""
        if not self.history:
            raise ActionError("Nothing to undo in this session.")
        row_id, before = self.history.pop()
        row = self.by_id[row_id]
        row.update(before)
        if row_id in self.handled:
            self.handled.remove(row_id)
        self._save(row, "undo", raw="")
        return row

    def stop(self) -> None:
        self.stopped = True

    # --- internals ------------------------------------------------------------

    def _current_row(self, row_id: str) -> dict:
        row = self.current()
        if row is None or row["id"] != row_id:
            # A repeated click or a stale page: never apply it to another row.
            raise ActionError("That line is no longer the current one; the page was refreshed.")
        return row

    def _remember(self, row: dict) -> None:
        self.history.append((row["id"], dict(row)))
        self.handled.append(row["id"])

    def _verify(self, row: dict, raw: str, source: str, action: str) -> dict:
        text = normalise(raw)
        self._remember(row)
        row.update(
            {
                "ground_truth": text,
                "verified": "true",
                "excluded_reason": "",
                "ground_truth_source": source,
                "annotator": self.annotator,
                "verified_at": self.clock(),
                "ground_truth_sha256": bakeoff.text_sha256(text),
            }
        )
        self._save(row, action, raw)
        return row

    def _save(self, row: dict, action: str, raw: str) -> None:
        bakeoff.write_annotation(self.table_path, self.rows)
        entry = {
            "id": row["id"],
            "action": action,
            "raw_input": raw,
            "ground_truth": row["ground_truth"],
            "verified": row["verified"],
            "excluded_reason": row["excluded_reason"],
            "annotator": self.annotator,
            "timestamp": self.clock(),
        }
        with self.log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
