// @vitest-environment jsdom
import React from "react";
import {expect, test} from "vitest";
import {render, screen} from "@testing-library/react";
import DocumentMetadata, {visibleNote} from "./DocumentMetadata.jsx";
import {createDocumentDraft, confirmDocumentField} from "@/lib/documentFields.js";
import {fastMetadataDocument} from "@/test/fixtures/fastMetadata.js";
import {stampSubjectDocument} from "@/test/fixtures/stampSubject.js";

const ROUTINE = "Nguồn OCR: đối chiếu bản gốc trước khi xác nhận; không tự sửa chữ hoặc dấu.";
function view(raw, draft = createDocumentDraft(raw)) {
  render(<DocumentMetadata draft={draft} result={raw} onEdit={() => {}} onConfirmField={() => {}} onReset={() => {}} onExport={() => {}}/>);
  return draft;
}

test("the OCR reminder is stated once, not repeated under every field", () => {
  const raw = fastMetadataDocument(), draft = view(raw);
  expect(Object.values(draft.fields).filter(entry => entry.note.includes(ROUTINE)).length).toBeGreaterThan(3);
  expect(document.body.textContent).not.toContain(ROUTINE);
  expect(document.querySelectorAll(".metadata-hint")).toHaveLength(1);
  expect(document.querySelector(".metadata-hint").textContent).toContain("Giá trị từ OCR");
  // The full note stays available as the tooltip of the control.
  expect(document.getElementById("metadata-arcDocCode").title).toContain(ROUTINE);
});

test("only review and confirmed fields carry a status badge; empty fields rely on the placeholder", () => {
  const raw = fastMetadataDocument(), draft = createDocumentDraft(raw);
  view(raw, confirmDocumentField(draft, "issuedDate"));
  const badges = Array.from(document.querySelectorAll(".field-status"), badge => badge.textContent);
  expect(badges.every(text => ["Cần kiểm tra", "Đã xác nhận"].includes(text))).toBe(true);
  expect(badges).toContain("Đã xác nhận");
  for (const key of ["codeNumber", "codeNotation", "numberOfPage"]) expect(document.getElementById(`metadata-${key}`).closest(".metadata-field").querySelector(".field-status")).toBeNull();
  expect(document.body.textContent).not.toContain("Chưa xác định Mã tài liệu");
  expect(screen.getByPlaceholderText("Luôn để trống").id).toBe("metadata-docId");
  expect(document.querySelectorAll(".metadata-field input, .metadata-field [role=combobox], .metadata-field textarea")).toHaveLength(22);
});

test("a real warning stays visible next to its field", () => {
  const raw = stampSubjectDocument({stamp: true, merged: true});
  view(raw);
  const subject = document.getElementById("metadata-subject").closest(".metadata-field");
  expect(subject.querySelector(".field-note").textContent).toContain("Trích yếu chưa xác minh");
  expect(subject.querySelector(".metadata-unverified-candidate")).toBeTruthy();
});

test("routine notes are removed, other text kept", () => {
  expect(visibleNote(`Có ký tự OCR chưa chắc chắn; đối chiếu bản gốc. Không tự thay ký tự. ${ROUTINE}`))
    .toBe("Có ký tự OCR chưa chắc chắn; đối chiếu bản gốc. Không tự thay ký tự.");
  expect(visibleNote("Đã được người dùng kiểm tra và xác nhận.")).toBe("");
});
