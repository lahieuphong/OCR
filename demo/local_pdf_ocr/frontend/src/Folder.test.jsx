// @vitest-environment jsdom
import React from "react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import {syntheticDocument} from "./test/fixtures/administrativeDocuments.js";
import {fastMetadataDocument} from "./test/fixtures/fastMetadata.js";

function folderFile(path, size) {
  // Same lastModified for the same path: the file the folder picker returns again.
  const item = new File(["%PDF synthetic"], path.split("/").at(-1), {type: path.endsWith(".pdf") ? "application/pdf" : "", lastModified: 1});
  Object.defineProperty(item, "webkitRelativePath", {value: path});
  if (size) Object.defineProperty(item, "size", {value: size});
  return item;
}
let calls, failures, gate;
beforeEach(() => {
  calls = []; failures = new Set(); gate = null;
  vi.stubGlobal("fetch", vi.fn(async (url, options) => {
    if (url === "/api/health") return {ok: true, json: async () => ({state: "ready_to_initialize"})};
    const name = options.body.get("file").name, mode = options.body.get("mode"); calls.push({name, mode});
    if (gate) await gate.promise;
    const failed = failures.has(name);
    return {ok: !failed, json: async () => failed ? {detail: `Lỗi thử nghiệm ${name}`} : mode === "metadata_fast"
      ? fastMetadataDocument({code: `00${name[0]}/FAST`}) : syntheticDocument({method: mode, code: `00${name[0]}/${mode}`})};
  }));
  URL.createObjectURL = vi.fn(() => "blob:http://127.0.0.1/synthetic"); URL.revokeObjectURL = vi.fn();
});
afterEach(() => {vi.restoreAllMocks(); vi.unstubAllGlobals();});

async function chooseFolder(files) {
  const user = userEvent.setup(); render(<App/>);
  await waitFor(() => expect(document.querySelector(".server-pill").className).toContain("connected"));
  await user.upload(screen.getByLabelText("Chọn thư mục tài liệu"), files);
  return user;
}
const queued = () => Array.from(document.querySelectorAll(".input-queue li .select-queued-file"),
  item => `${item.querySelector(".queue-index").textContent}. ${item.querySelector(".queue-name").firstChild.textContent}`);
const modes = () => Array.from(document.querySelectorAll(".input-queue li select"), item => item.value);
const runAll = user => user.click(screen.getByRole("button", {name: /^Bóc tách tất cả \(/}));

test("a chosen folder adds its PDFs and images in folder order, fast mode by default, and reports skipped files", async () => {
  const user = await chooseFolder([folderFile("Hồ sơ/10.pdf"), folderFile("Hồ sơ/2.pdf"), folderFile("Hồ sơ/con/3.png"),
    folderFile("Hồ sơ/ghi chú.docx"), folderFile("Hồ sơ/lớn.pdf", 16 * 1024 * 1024), folderFile("Hồ sơ/Thumbs.db")]);
  expect(queued()).toEqual(["1. 2.pdf", "2. 10.pdf", "3. 3.png"]);
  expect(modes()).toEqual(["metadata_fast", "metadata_fast", "metadata_fast"]);
  expect(document.querySelector(".input-queue li:nth-child(3) small").textContent).toContain("Hồ sơ/con/3.png");
  expect(document.querySelector(".error-box")).toBeNull();
  const error = document.querySelector(".import-notice").textContent;
  expect(error).toContain("Đã thêm 3 tài liệu, bỏ qua 2 tệp: 1 không phải PDF/PNG/JPG, 1 lớn hơn 15 MB.");
  expect(error).toContain("Hồ sơ/lớn.pdf: Giới hạn kích thước tệp là 15 MB.");
  expect(error).not.toContain("Thumbs.db");
  await user.upload(screen.getByLabelText("Chọn thư mục tài liệu"), [folderFile("Hồ sơ/2.pdf"), folderFile("Hồ sơ/11.pdf")]);
  expect(queued()).toEqual(["1. 2.pdf", "2. 10.pdf", "3. 3.png", "4. 11.pdf"]);
  await runAll(user);
  await waitFor(() => expect(calls).toHaveLength(4));
  expect(calls.every(call => call.mode === "metadata_fast")).toBe(true);
  expect(calls.map(call => call.name)).toEqual(["2.pdf", "10.pdf", "3.png", "11.pdf"]);
});

test("one method can be applied to every document; images keep a mode they support", async () => {
  const user = await chooseFolder([folderFile("d/1.pdf"), folderFile("d/2.png"), folderFile("d/3.pdf")]);
  await user.selectOptions(screen.getByLabelText("Phương pháp cho tất cả tài liệu"), "native_text");
  expect(modes()).toEqual(["native_text", "metadata_fast", "native_text"]);
  await user.selectOptions(screen.getByLabelText("Phương pháp cho tất cả tài liệu"), "vietocr_ocr");
  expect(modes()).toEqual(["vietocr_ocr", "vietocr_ocr", "vietocr_ocr"]);
});

test("pause stops after the current document, continue runs only the rest, failed ones retry alone", async () => {
  failures.add("2.pdf");
  let release; gate = {promise: new Promise(resolve => {release = resolve;})};
  const user = await chooseFolder(["1", "2", "3", "4"].map(name => folderFile(`d/${name}.pdf`)));
  await runAll(user);
  await waitFor(() => expect(calls).toHaveLength(1));
  await user.click(screen.getByRole("button", {name: "Tạm dừng hàng chờ"}));
  expect(screen.getByRole("button", {name: "Sẽ dừng sau tài liệu đang xử lý…"}).disabled).toBe(true);
  gate = null; release();
  await waitFor(() => expect(document.querySelector(".queue-progress").textContent).toContain("Đã tạm dừng, còn 3 tài liệu"));
  expect(calls.map(call => call.name)).toEqual(["1.pdf"]);
  expect(document.querySelector(".queue-progress").textContent).toContain("Đã xử lý 1/4");
  await user.click(screen.getByRole("button", {name: "Tiếp tục (3 tài liệu còn lại)"}));
  await waitFor(() => expect(document.querySelector(".queue-progress").textContent).toContain("Đã xử lý 3/3"));
  expect(calls.map(call => call.name)).toEqual(["1.pdf", "2.pdf", "3.pdf", "4.pdf"]);
  failures.clear();
  await user.click(screen.getByRole("button", {name: "Chạy lại 1 tài liệu lỗi"}));
  await waitFor(() => expect(calls).toHaveLength(5));
  expect(calls.at(-1).name).toBe("2.pdf");
  await waitFor(() => expect(screen.queryByRole("button", {name: /tài liệu lỗi/})).toBeNull());
});

test("a dropped folder is read with its subfolders; dropped files are still added at once", async () => {
  render(<App/>);
  const pdf = name => new File(["%PDF synthetic"], name, {type: "application/pdf"});
  const entry = item => ({isFile: true, isDirectory: false, name: item.name, file: resolve => resolve(item)});
  const folder = (name, children) => ({isFile: false, isDirectory: true, name, createReader: () => {
    let done = false; return {readEntries: resolve => {resolve(done ? [] : children); done = true;}};
  }});
  fireEvent.drop(document.querySelector(".dropzone"), {dataTransfer: {files: [], items: [
    {kind: "file", webkitGetAsEntry: () => folder("Lô", [entry(pdf("b.pdf")), folder("con", [entry(pdf("a.pdf"))])])}]}});
  await waitFor(() => expect(queued()).toEqual(["1. b.pdf", "2. a.pdf"]));
  expect(modes()).toEqual(["metadata_fast", "metadata_fast"]);
  fireEvent.drop(document.querySelector(".dropzone"), {dataTransfer: {files: [pdf("c.pdf")]}});
  expect(queued()).toHaveLength(3);
  expect(modes()[2]).toBe("metadata_fast");
});

test("without models a new PDF can run the fast header from its text layer; a new image cannot", async () => {
  fetch.mockImplementation(async url => url === "/api/health" ? {ok: true, json: async () => ({state: "missing_model_files"})} : {ok: false, json: async () => ({})});
  const user = userEvent.setup(); render(<App/>);
  await screen.findByText("Thiếu model OCR");
  await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), [new File(["%PDF synthetic"], "a.pdf", {type: "application/pdf"}), new File(["png"], "b.png", {type: "image/png"})]);
  expect(modes()).toEqual(["metadata_fast", "metadata_fast"]);
  expect(document.querySelector(".run-button").disabled).toBe(false);
  await user.click(document.querySelectorAll(".input-queue li .select-queued-file")[1]);
  expect(document.querySelector(".run-button").disabled).toBe(true);
  expect(screen.getByRole("button", {name: /^Bóc tách tất cả \(/}).disabled).toBe(true);
});

test("one button runs only the selected document; the emphasized second button runs every document", async () => {
  const user = await chooseFolder([folderFile("d/1.pdf"), folderFile("d/2.pdf"), folderFile("d/3.pdf")]);
  const one = screen.getByRole("button", {name: "Bóc tách nhanh văn bản này"});
  expect(one.dataset.variant).toBe("outline");
  expect(screen.getByRole("button", {name: "Bóc tách tất cả (3 tài liệu)"}).dataset.variant).toBe("default");
  await user.click(one);
  await waitFor(() => expect(calls.map(call => call.name)).toEqual(["1.pdf"]));
  // Still all three: the processed one is run again, after a confirmation.
  await waitFor(() => expect(screen.getByRole("button", {name: "Bóc tách tất cả (3 tài liệu)"}).disabled).toBe(false));
  await runAll(user);
  const dialog = screen.getByRole("alertdialog");
  expect(dialog.textContent).toContain("1/3 tài liệu đã có kết quả");
  await user.click(within(dialog).getByRole("button", {name: "Bóc tách tất cả"}));
  await waitFor(() => expect(calls.map(call => call.name)).toEqual(["1.pdf", "1.pdf", "2.pdf", "3.pdf"]));
  await runAll(user);
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button", {name: "Hủy"}));
  expect(calls).toHaveLength(4);
});

test("a single document keeps one main button", async () => {
  const user = userEvent.setup(); render(<App/>);
  await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"), new File(["%PDF synthetic"], "a.pdf", {type: "application/pdf"}));
  expect(screen.getByRole("button", {name: "Bóc tách nhanh văn bản này"}).dataset.variant).toBe("default");
  expect(screen.queryByRole("button", {name: /^Bóc tách tất cả/})).toBeNull();
});
