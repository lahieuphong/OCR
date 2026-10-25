// @vitest-environment jsdom
import React from "react";
import {afterEach, beforeEach, describe, expect, test, vi} from "vitest";
import {render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import {FIELD_KEYS} from "./lib/documentFields.js";
import {syntheticDocument} from "./test/fixtures/administrativeDocuments.js";

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
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});
const file = (name = "synthetic.pdf") => new File(["%PDF synthetic test"], name, {type:"application/pdf"});
const field = key => document.getElementById(`metadata-${key}`);
const readBlob = blob => new Promise(resolve => {const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsText(blob, "utf-8");});
async function start() {
  const user = userEvent.setup(); render(<App/>);
  await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), file());
  await waitFor(() => expect(document.querySelector(".run-button").disabled).toBe(false));
  await user.click(screen.getByRole("button", {name:"Bóc tách văn bản"}));
  await screen.findByRole("tab", {name:"Thông tin văn bản", selected:true});
  return user;
}

describe("metadata UI integration", () => {
  test("opens metadata after successful extraction and renders the exact 22 labeled controls", async () => {
    await start();
    expect(document.querySelectorAll(".metadata-field input, .metadata-field select, .metadata-field textarea").length).toBe(22);
    expect(field("arcDocCode").value).toBe("00103/TEST-CN");
    expect(field("issuedDate").value).toBe("08-10-2026");
    expect(field("docId").readOnly).toBe(true); expect(field("docId").value).toBe("");
    expect(field("isCan").value).toBe(""); expect(field("confidenceLevel").value).toBe("02");
    expect(screen.getByText("Số trường có bằng chứng, không phải độ chính xác OCR.")).toBeTruthy();
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
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản"}));
    expect(fetch.mock.calls.length).toBe(before);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name:"Hủy"}));
    apiResults.push(jsonResponse({detail:"Lỗi tổng hợp để kiểm tra giữ bản nháp"}, false));
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản"}));
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
    await user.click(screen.getByRole("button", {name:"Bóc tách văn bản"}));
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
    await user.selectOptions(field("isCan"), "0");
    expect(field("confidenceLevel").value).toBe("01");
    await user.selectOptions(field("isCan"), "1");
    expect(field("confidenceLevel").value).toBe("02");
    expect(storage).not.toHaveBeenCalled();
    expect(fetch.mock.calls.every(([url]) => ["/api/health","/api/ocr"].includes(url))).toBe(true);
  });
});
