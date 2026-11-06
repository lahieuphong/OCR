// @vitest-environment jsdom
import React, {useState} from "react";
import {afterEach, beforeEach, describe, expect, test, vi} from "vitest";
import {render, screen, waitFor} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import NumberCodeReview from "./NumberCodeReview.jsx";
import DocumentMetadata from "./DocumentMetadata.jsx";
import {createDocumentDraft, editDocumentField, confirmDocumentField, serializeDocumentFields, FIELD_KEYS} from "@/lib/documentFields.js";

const line = (line_index, text, x = 210, y = 233, w = 270) => ({line_index, text,
  polygon: [[x, y], [x + w, y], [x + w, y + 31], [x, y + 31]]});
const result = (text = "Số: 4H7/TEST", extra = []) => ({method: "vietocr_ocr", used_ocr: true,
  filename: "synthetic.pdf", page_count: 1, line_count: 2, text: `${text}\nTài liệu kiểm thử`,
  pages: [{page: 1, width: 1192, height: 1686, lines: [line(1, text),
    line(2, "Hà Nội, ngày 12 tháng 3 năm 2025", 650, 235, 400), ...extra]}]});
const file = name => new File(["%PDF synthetic test"], name || "synthetic.pdf", {type: "application/pdf"});
const pngResponse = () => ({ok: true, blob: async () => new Blob(["synthetic PNG response"], {type: "image/png"})});
let fetchMock;
beforeEach(() => {
  fetchMock = vi.fn(async () => pngResponse()); vi.stubGlobal("fetch", fetchMock);
  URL.createObjectURL = vi.fn(() => "blob:synthetic-number-crop"); URL.revokeObjectURL = vi.fn();
});
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});

describe("number code image review", () => {
  test("loads only on demand and sends source geometry, never OCR text or metadata", async () => {
    const raw = result(), sourceFile = file(), user = userEvent.setup();
    render(<NumberCodeReview result={raw} sourceFile={sourceFile}/>);
    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}));
    expect(await screen.findByRole("img")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
    const [url, request] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/number-review/preview"); expect(request.method).toBe("POST");
    expect([...request.body.keys()]).toEqual(["file", "page", "polygon", "render_width", "render_height"]);
    expect(request.body.get("page")).toBe("1"); expect(request.body.get("render_width")).toBe("1192");
    expect(JSON.parse(request.body.get("polygon"))).toEqual(raw.pages[0].lines[0].polygon);
  });
  test("switching source aborts a pending request and ignores a late response", async () => {
    let resolveFirst;
    fetchMock.mockImplementationOnce(() => new Promise(resolve => {resolveFirst = resolve;}));
    const raw = result(), first = file("first.pdf"), second = file("second.pdf"), user = userEvent.setup();
    const view = render(<NumberCodeReview result={raw} sourceFile={first}/>);
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}));
    const signal = fetchMock.mock.calls[0][1].signal;
    view.rerender(<NumberCodeReview result={raw} sourceFile={second}/>);
    expect(signal.aborted).toBe(true); resolveFirst(pngResponse());
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(URL.createObjectURL).not.toHaveBeenCalled(); expect(screen.queryByRole("img")).toBeNull();
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}));
    expect(await screen.findByRole("img")).toBeTruthy();
    expect(fetchMock.mock.calls[1][1].body.get("file").name).toBe("second.pdf");
  });
  test("a new result hides and revokes the previous image before another request", async () => {
    const sourceFile = file(), user = userEvent.setup();
    const view = render(<NumberCodeReview result={result()} sourceFile={sourceFile}/>);
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}));
    await screen.findByRole("img");
    view.rerender(<NumberCodeReview result={result("Số: 7O8/NEW")} sourceFile={sourceFile}/>);
    expect(screen.queryByRole("img")).toBeNull();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-number-crop");
    expect(screen.getByText("Số: 7O8/NEW")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  test("changing candidates cancels the current crop and unmount revokes an opened image", async () => {
    const raw = result("Số: 4H7/TEST", [line(3, "Số: 7O8/OTHER", 210, 300)]), user = userEvent.setup();
    const view = render(<NumberCodeReview result={raw} sourceFile={file()}/>);
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"})); await screen.findByRole("img");
    await user.click(screen.getByRole("button", {name: "Dòng 3 · cần kiểm tra"}));
    expect(screen.queryByRole("img")).toBeNull(); expect(URL.revokeObjectURL).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"})); await screen.findByRole("img");
    view.unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledTimes(2);
  });
  test("native text and unlocated rows show source guidance without requesting a crop", () => {
    const raw = result(), sourceFile = file();
    const view = render(<NumberCodeReview result={{...raw, method: "native_text", used_ocr: false}} sourceFile={sourceFile}/>);
    expect(screen.queryByRole("button", {name: "Xem ảnh đối chiếu"})).toBeNull();
    expect(screen.getByText(/Đối chiếu số\/ký hiệu với tài liệu gốc/)).toBeTruthy();
    view.rerender(<NumberCodeReview result={result("Nội dung không định vị được")} sourceFile={sourceFile}/>);
    expect(screen.getByText(/Chưa có vị trí đáng tin cậy/)).toBeTruthy(); expect(fetchMock).not.toHaveBeenCalled();
  });
  test("disabled or missing source cannot send a preview request", () => {
    const raw = result(), sourceFile = file();
    const view = render(<NumberCodeReview result={raw} sourceFile={sourceFile} disabled/>);
    expect(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}).disabled).toBe(true);
    view.rerender(<NumberCodeReview result={raw}/>);
    expect(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}).disabled).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  test.each(["http", "mime"])("%s failure never displays an invalid image", async failure => {
    fetchMock.mockResolvedValueOnce(failure === "http"
      ? {ok: false, json: async () => ({detail: "Vị trí ảnh không khớp tài liệu."})}
      : {ok: true, blob: async () => new Blob(["not an image"], {type: "text/html"})});
    render(<NumberCodeReview result={result()} sourceFile={file()}/>);
    await userEvent.setup().click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"}));
    expect(await screen.findByRole("alert")).toBeTruthy(); expect(screen.queryByRole("img")).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
  test("image review leaves the 22-field edit/confirm/export flow and original OCR independent", async () => {
    const raw = result(), before = JSON.stringify(raw), sourceFile = file();
    let currentDraft;
    function Harness() {
      const [draft, setDraft] = useState(() => createDocumentDraft(raw)); currentDraft = draft;
      return <DocumentMetadata draft={draft} result={raw} sourceFile={sourceFile}
        onEdit={(key, value) => setDraft(old => editDocumentField(old, key, value))}
        onConfirmField={key => setDraft(old => confirmDocumentField(old, key))} onReset={() => {}} onExport={() => {}}/>;
    }
    render(<Harness/>); const user = userEvent.setup();
    expect(document.querySelectorAll(".metadata-field input, .metadata-field [role=combobox], .metadata-field textarea")).toHaveLength(22);
    await user.click(screen.getByRole("button", {name: "Xem ảnh đối chiếu"})); await screen.findByRole("img");
    expect(currentDraft.fields.arcDocCode.status).toBe("review");
    await user.click(screen.getByRole("button", {name: "Xác nhận Mã văn bản"}));
    expect(currentDraft.fields.arcDocCode.status).toBe("confirmed");
    const code = screen.getByLabelText("Mã văn bản"); await user.clear(code); await user.type(code, "47/TEST");
    const exported = JSON.parse(serializeDocumentFields(currentDraft));
    expect(Object.keys(exported)).toEqual(FIELD_KEYS); expect(exported.arcDocCode).toBe("47/TEST");
    expect(exported.codeNumber).toBe("47"); expect(exported.codeNotation).toBe("TEST");
    expect(JSON.stringify(raw)).toBe(before);
  });
});
