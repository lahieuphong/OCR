// @vitest-environment jsdom
import React from "react";
import {afterEach, beforeEach, describe, expect, test, vi} from "vitest";
import {render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import {FIELD_KEYS} from "./lib/documentFields.js";
import {syntheticDocument} from "./test/fixtures/administrativeDocuments.js";
import {fastMetadataDocument, DECREE_SUBJECT} from "./test/fixtures/fastMetadata.js";
import {FAST_MODE_LABEL, FAST_MODE_DESCRIPTION} from "./lib/processingModes.js";
import {pick} from "./test/select.js";
import {STAMP_TEST_SUBJECT,stampSubjectDocument} from "./test/fixtures/stampSubject.js";

let blobs, apiResults;
const jsonResponse = (data, ok = true) => ({ok, json: async () => structuredClone(data)});
beforeEach(() => {
  blobs = []; apiResults = [];
  vi.stubGlobal("fetch", vi.fn(async (url, options) => {
    if (url === "/api/health") return jsonResponse({state:"ready_to_initialize"});
    const mode = options.body.get("mode");
    return apiResults.length ? apiResults.shift() : jsonResponse(syntheticDocument({method:mode,code:mode === "native_text" ? "00103/TEST-CN" : "002/OCR-TEST"}));
  }));
  URL.createObjectURL = vi.fn(blob => {blobs.push(blob); return `blob:http://127.0.0.1/test-${blobs.length}`;});
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

function hybridResponse() {
  const original = syntheticDocument({method:"vietocr_ocr",code:"002/OCR-TEST"});
  const result = syntheticDocument({method:"hybrid_h1",code:"003/MIX-TEST"});
  result.used_ocr = true; result.experimental = true; result.ocr_result = original;
  result.h1 = {native_lines:1,ocr_lines:result.line_count - 1};
  for (const page of result.pages) page.lines.forEach((line,i) => {
    line.ocr_text = original.pages[0].lines[i].text;
    line.text_source = i === 3 ? "pdf_text" : "ocr";
  });
  return result;
}

describe("explicit experimental PDF/OCR selection", () => {
  test("is off by default, keeps baseline separately and compares raw OCR without editing it", async () => {
    const user = await start(), hybrid = hybridResponse(), rawBytes = JSON.stringify(hybrid.ocr_result);
    const choice = document.querySelector('input[name=mode][value=hybrid_h1]');
    expect(choice.checked).toBe(false);
    apiResults.push(jsonResponse(hybrid));
    await user.click(choice);
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    await waitFor(() => expect(field("arcDocCode")?.value).toBe("003/MIX-TEST"));
    expect(fetch.mock.calls.at(-1)[1].body.get("mode")).toBe("hybrid_h1");
    expect(field("arcDocCode").closest(".metadata-field").textContent).toContain("Cần kiểm tra");
    await user.click(screen.getByRole("tab", {name:"So sánh"}));
    const texts = [...document.querySelectorAll(".comparison-columns pre")].map(el => el.textContent);
    expect(texts).toEqual([hybrid.text, hybrid.ocr_result.text]);
    await user.click(screen.getByTitle("Tải báo cáo JSON"));
    const saved = JSON.parse(await readBlob(blobs.find(b => b.type.startsWith("application/json"))));
    expect(JSON.stringify(saved.ocr_result)).toBe(rawBytes);
    await user.click(document.querySelector('input[name=mode][value=vietocr_ocr]'));
    expect(field("arcDocCode").value).toBe("002/OCR-TEST");
    expect(fetch.mock.calls.filter(([url])=>url === "/api/ocr")).toHaveLength(2);
  });
  test("a new hybrid run never replaces existing OCR metadata edits", async () => {
    const user = await start();
    await user.click(document.querySelector('input[name=mode][value=vietocr_ocr]'));
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    await waitFor(() => expect(field("arcDocCode")?.value).toBe("002/OCR-TEST"));
    await user.type(field("arcDocCode"), "-KEEP");
    const hybrid = hybridResponse();
    hybrid.ocr_result = syntheticDocument({method:"vietocr_ocr",code:"007/FRESH-TEST"});
    apiResults.push(jsonResponse(hybrid));
    await user.click(document.querySelector('input[name=mode][value=hybrid_h1]'));
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    await waitFor(() => expect(field("arcDocCode")?.value).toBe("003/MIX-TEST"));
    await user.click(screen.getByRole("tab", {name:"So sánh"}));
    expect([...document.querySelectorAll(".comparison-columns pre")][1].textContent).toBe(hybrid.ocr_result.text);
    await user.click(document.querySelector('input[name=mode][value=vietocr_ocr]'));
    expect(field("arcDocCode").value).toBe("002/OCR-TEST-KEEP");
  });
});
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});
const file = (name = "synthetic.pdf") => new File(["%PDF synthetic test"], name, {type:"application/pdf"});
const field = key => document.getElementById(`metadata-${key}`);
const readBlob = blob => new Promise(resolve => {const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(blob, "utf-8");});
async function start() {
  const user = userEvent.setup(); render(<App/>);
  await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), file());
  // New documents start in the fast header mode; these cases exercise the full-text metadata path.
  expect(document.querySelector('input[name=mode]:checked').value).toBe("metadata_fast");
  await user.click(document.querySelector('input[name=mode][value=native_text]'));
  await waitFor(() => expect(document.querySelector(".run-button").disabled).toBe(false));
  await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
  await screen.findByRole("tab", {name:"Thông tin văn bản", selected:true});
  return user;
}

describe("explicit fast metadata mode", () => {
  test("stamp candidate is visibly unverified, excluded from JSON, and manual edits survive modes and raw exports", async () => {
    const user=await start(),raw=stampSubjectDocument({stamp:true,merged:true}),snapshot=JSON.stringify(raw);
    apiResults.push(jsonResponse(raw));const fast=document.querySelector('input[name=mode][value=metadata_fast]');
    await user.click(fast);await user.click(screen.getByRole("button",{name:"Bóc tách nhanh văn bản này"}));
    await waitFor(()=>expect(field("arcDocCode")?.value).toBe("00042/2025/NĐ-QA"));
    expect(field("subject").value).toBe("");
    const subject=field("subject").closest(".metadata-field");expect(subject.querySelector(".field-status").textContent).toBe("Cần kiểm tra");
    expect(subject.querySelector(".confirm-field")).toBeNull();
    const candidate=subject.querySelector(".metadata-unverified-candidate");
    expect(candidate.querySelector("summary").textContent).toBe("Ứng viên chưa xác minh — dấu đóng chồng");
    expect(candidate.textContent).toContain("Ngày: 03/02/2025,");expect(subject.textContent).toContain("Trích yếu chưa xác minh");
    await user.click(screen.getByRole("button",{name:"Xuất JSON 22 trường"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Xuất bản nháp"}));
    const blank=JSON.parse(await readBlob(blobs.filter(blob=>blob.type.startsWith("application/json")).at(-1)));
    expect(Object.keys(blank)).toEqual(FIELD_KEYS);expect(blank.subject).toBe("");expect(JSON.stringify(blank)).not.toContain("Ngày: 03/02/2025,");
    await user.click(field("subject"));await user.paste(STAMP_TEST_SUBJECT);
    await user.click(document.querySelector('input[name=mode][value=native_text]'));await user.click(fast);
    expect(field("subject").value).toBe(STAMP_TEST_SUBJECT);expect(field("subject").closest(".metadata-field").querySelector(".field-status").textContent).toBe("Đã xác nhận");
    await user.click(screen.getByRole("button",{name:"Xuất JSON 22 trường"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Xuất bản nháp"}));
    const edited=JSON.parse(await readBlob(blobs.filter(blob=>blob.type.startsWith("application/json")).at(-1)));
    expect(Object.keys(edited)).toEqual(FIELD_KEYS);expect(edited.subject).toBe(STAMP_TEST_SUBJECT);
    await user.click(screen.getByRole("tab",{name:"Header (một phần)"}));expect(document.querySelector(".text-output pre").textContent).toBe(raw.text);
    await user.click(screen.getByTitle("Tải JSON header (một phần)"));
    expect(JSON.stringify(JSON.parse(await readBlob(blobs.filter(blob=>blob.type.startsWith("application/json")).at(-1))))).toBe(snapshot);
  });
  test("is optional, preserves native defaults and edits, and labels every partial text export", async () => {
    const user=await start(), raw=fastMetadataDocument({stamp:true}), snapshot=JSON.stringify(raw);
    const choice=document.querySelector('input[name=mode][value=metadata_fast]');
    expect(choice.checked).toBe(false);
    await user.type(field("arcDocCode"),"-FULL-EDIT");
    apiResults.push(jsonResponse(raw)); await user.click(choice);
    expect(screen.getByText(FAST_MODE_DESCRIPTION)).toBeTruthy();
    await user.click(screen.getByRole("button",{name:"Bóc tách nhanh văn bản này"}));
    await waitFor(()=>expect(field("arcDocCode")?.value).toBe("00042/2025/NĐ-QA"));
    expect(fetch.mock.calls.at(-1)[1].body.get("mode")).toBe("metadata_fast");
    expect(field("numberOfPage").value).toBe("6"); expect(field("typeName").value).toBe("");
    expect(document.querySelector(".detected-document-type").textContent).toContain("Nghị định");
    expect(field("subject").value).toBe(DECREE_SUBJECT);
    expect(document.querySelector(".partial-result-notice").textContent).toContain("Nguồn 6 trang");
    expect(document.querySelector(".partial-result-notice").textContent).toContain("OCR trang 1");
    await user.type(field("arcDocCode"),"-FAST-EDIT");
    await user.click(screen.getByRole("tab",{name:"Header (một phần)"}));
    expect(document.querySelector(".text-output pre").textContent).toBe(raw.text);
    expect(screen.queryByRole("tab",{name:"Toàn văn"})).toBeNull();
    await user.click(screen.getByTitle("Tải TXT header (một phần)"));
    await user.click(screen.getByTitle("Tải JSON header (một phần)"));
    const txt=await readBlob(blobs.find(blob=>blob.type.startsWith("text/plain")));
    expect(txt).toContain("NỘI DUNG HEADER MỘT PHẦN");expect(txt).toContain("Nguồn 6 trang");expect(txt.endsWith(raw.text)).toBe(true);
    const saved=JSON.parse(await readBlob(blobs.find(blob=>blob.type.startsWith("application/json"))));
    expect(JSON.stringify(saved)).toBe(snapshot);expect(saved.processed_pages).toEqual([1]);
    await user.click(document.querySelector('input[name=mode][value=native_text]'));
    expect(field("arcDocCode").value).toBe("00103/TEST-CN-FULL-EDIT");
    await user.click(choice);expect(field("arcDocCode").value).toBe("00042/2025/NĐ-QA-FAST-EDIT");
    expect(fetch.mock.calls.filter(([url])=>url==="/api/ocr")).toHaveLength(2);
  });
  test("genuine native fast header works without models and a later OCR-needed error preserves edits", async () => {
    fetch.mockImplementation(async(url,options)=>url==="/api/health" ? jsonResponse({state:"not_ready"})
      : apiResults.shift() || jsonResponse(fastMetadataDocument({native:true})));
    const user=userEvent.setup();render(<App/>);
    await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"),file());
    await screen.findByText("Thiếu model OCR");
    await user.click(document.querySelector('input[name=mode][value=metadata_fast]'));
    const run=screen.getByRole("button",{name:"Bóc tách nhanh văn bản này"}); expect(run.disabled).toBe(false);
    await user.click(run);await waitFor(()=>expect(field("numberOfPage")?.value).toBe("6"));
    expect(document.querySelector(".partial-result-notice").textContent).toContain("không chạy OCR");
    await user.type(field("arcDocCode"),"-KEEP");
    apiResults.push(jsonResponse({detail:"Cần model OCR để đọc header ảnh; không dùng lớp chữ ký."},false));
    await user.click(run);await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Thay thế bản nháp"}));
    await screen.findByText("Cần model OCR để đọc header ảnh; không dùng lớp chữ ký.");
    expect(field("arcDocCode").value).toBe("00042/2025/NĐ-QA-KEEP");
    await user.click(document.querySelector('input[name=mode][value=vietocr_ocr]'));
    expect(document.querySelector(".run-button").disabled).toBe(true);
  });
});

describe("metadata UI integration", () => {
  test("opens metadata after successful extraction and renders the exact 22 labeled controls", async () => {
    await start();
    expect(document.querySelectorAll(".metadata-field input, .metadata-field [role=combobox], .metadata-field textarea").length).toBe(22);
    expect(field("arcDocCode").value).toBe("00103/TEST-CN");
    expect(field("issuedDate").value).toBe("08-10-2026");
    expect(field("docId").readOnly).toBe(true); expect(field("docId").value).toBe("");
    expect(field("isCan").value).toBe(""); expect(field("confidenceLevel").value).toBe("02");
    expect(screen.getByTitle("Số trường có bằng chứng, không phải độ chính xác OCR.")).toBeTruthy();
  });
  test("shows literal page/line evidence without fake highlights", async () => {
    const user = await start();
    const source = field("arcDocCode").closest(".metadata-field").querySelector(".field-evidence summary");
    await user.click(source);
    expect(within(field("arcDocCode").closest(".metadata-field")).getByText("Số: 00103/TEST-CN", {exact:false})).toBeTruthy();
    expect(source.textContent).toContain("trang 1, dòng 4");
  });
  test("tab switching preserves edits and original TXT/JSON bytes", async () => {
    const user = await start();
    const raw = syntheticDocument();
    await user.clear(field("subject")); await user.type(field("subject"), "Nguyễn Văn A – chỉnh sửa metadata");
    await user.click(screen.getByRole("tab", {name:"Toàn văn"}));
    expect(document.querySelector(".text-output pre").textContent).toBe(raw.text);
    await user.click(screen.getByTitle("Tải TXT")); await user.click(screen.getByTitle("Tải báo cáo JSON"));
    expect(await readBlob(blobs.find(b => b.type.startsWith("text/plain")))).toBe(raw.text);
    expect(await readBlob(blobs.find(b => b.type.startsWith("application/json")))).toBe(JSON.stringify(raw, null, 2));
    await user.click(screen.getByRole("tab", {name:"Thông tin văn bản"}));
    expect(field("subject").value).toBe("Nguyễn Văn A – chỉnh sửa metadata");
  });
  test("warns about missing access classification before either JSON export or copy", async () => {
    const user = await start();
    const clipboard = vi.spyOn(navigator.clipboard, "writeText");
    await user.click(screen.getByRole("button", {name:"Sao chép JSON"}));
    const dialog = screen.getByRole("alertdialog");
    expect(dialog.textContent).toContain("01 · Công khai"); expect(clipboard).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", {name:"Sao chép bản nháp"}));
    await waitFor(() => expect(clipboard).toHaveBeenCalledOnce());
    const parsed = JSON.parse(clipboard.mock.calls[0][0]);
    expect(Object.keys(parsed)).toEqual(FIELD_KEYS); expect(parsed.mode).toBe("");
    await user.click(screen.getByRole("button", {name:"Xuất JSON 22 trường"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Xuất bản nháp"}));
    const saved = JSON.parse(await readBlob(blobs.find(b => b.type.startsWith("application/json"))));
    expect(saved).toEqual(parsed);
  });
  test("invalid calendar dates block metadata export", async () => {
    const user = await start();
    await user.clear(field("issuedDate")); await user.type(field("issuedDate"), "31-02-2026");
    await user.click(screen.getByRole("button", {name:"Xuất JSON 22 trường"}));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(field("issuedDate").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Ngày phải hợp lệ, theo DD-MM-YYYY.")).toBeTruthy();
    expect(blobs.filter(b => b.type.startsWith("application/json"))).toHaveLength(0);
  });
  test("restoring automated values requires confirmation and supports cancel", async () => {
    const user = await start();
    await user.clear(field("subject")); await user.type(field("subject"), "Bản sửa được bảo vệ");
    await user.click(screen.getByRole("button", {name:"Khôi phục giá trị tự động"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Hủy"}));
    expect(field("subject").value).toBe("Bản sửa được bảo vệ");
    await user.click(screen.getByRole("button", {name:"Khôi phục giá trị tự động"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Thay thế bản nháp"}));
    expect(field("subject").value).toContain("kiểm thử trích xuất thông tin");
  });
  test("rerunning protects dirty metadata and failed requests preserve the prior result/draft", async () => {
    const user = await start();
    await user.type(field("arcDocCode"), "-EDIT");
    const before = fetch.mock.calls.length;
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    expect(fetch.mock.calls.length).toBe(before);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Hủy"}));
    apiResults.push(jsonResponse({detail:"Lỗi tổng hợp để kiểm tra giữ bản nháp"}, false));
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Thay thế bản nháp"}));
    await screen.findByText("Lỗi tổng hợp để kiểm tra giữ bản nháp");
    expect(field("arcDocCode").value).toBe("00103/TEST-CN-EDIT");
  });
  test("replacing a document resets metadata only after accepting loss of edits", async () => {
    const user = await start();
    await user.type(field("arcDocCode"), "-EDIT");
    await user.click(screen.getByRole("button", {name:"Đổi tệp"}));
    await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), file("second.pdf"));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Hủy"}));
    expect(document.querySelector(".selected-file strong").textContent).toBe("synthetic.pdf");
    await user.click(screen.getByRole("button", {name:"Đổi tệp"}));
    await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), file("second.pdf"));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Thay thế bản nháp"}));
    expect(document.querySelector(".selected-file strong").textContent).toBe("second.pdf");
    expect(document.querySelector(".document-metadata")).toBeNull();
  });
  test("independent OCR modes keep separate drafts and retain comparison", async () => {
    const user = await start();
    await user.type(field("arcDocCode"), "-MANUAL");
    await user.click(document.querySelector('input[name=mode][value=vietocr_ocr]'));
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản này"}));
    await waitFor(() => expect(field("arcDocCode")?.value).toBe("002/OCR-TEST"));
    await user.click(screen.getByRole("tab", {name:"So sánh"}));
    expect(document.querySelectorAll(".comparison-columns pre")).toHaveLength(2);
    await user.click(document.querySelector('input[name=mode][value=native_text]'));
    expect(field("arcDocCode").value).toBe("00103/TEST-CN-MANUAL");
  });
  test("manual stamp choice recomputes the business code and never stores document data", async () => {
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const user = await start();
    await user.click(screen.getByText("Tình trạng và xử lý", {exact:true}));
    await pick(user, field("isCan"), "0");
    expect(field("confidenceLevel").value).toBe("01");
    await pick(user, field("isCan"), "1");
    expect(field("confidenceLevel").value).toBe("02");
    expect(storage).not.toHaveBeenCalled();
    expect(fetch.mock.calls.every(([url]) => ["/api/health","/api/ocr"].includes(url))).toBe(true);
  });
});
