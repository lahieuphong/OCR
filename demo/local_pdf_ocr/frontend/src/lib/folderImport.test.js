import {describe, expect, test} from "vitest";
import {describeImport, documentPath, dropHasFolder, filesFromDrop, MAX_BATCH_DOCUMENTS, MAX_UPLOAD_BYTES, planImport} from "./folderImport.js";
import {createBatchDocument, estimateRemainingMs, modeAllowed} from "./documentBatch.js";

function file(path, {size = 10, lastModified = 1} = {}) {
  const name = path.split("/").at(-1);
  const item = new File(["x".repeat(Math.min(size, 16))], name, {lastModified});
  Object.defineProperty(item, "size", {value: size});
  if (path !== name) Object.defineProperty(item, "webkitRelativePath", {value: path});
  return item;
}
// Minimal FileSystemEntry fakes; readEntries returns folders in chunks like Chromium.
function fileEntry(item) {return {isFile: true, isDirectory: false, name: item.name, file: resolve => resolve(item)};}
function folderEntry(name, children, chunk = 2) {
  return {isFile: false, isDirectory: true, name, createReader: () => {
    let offset = 0;
    return {readEntries: resolve => {const part = children.slice(offset, offset + chunk); offset += chunk; resolve(part);}};
  }};
}

describe("folder import", () => {
  test("orders folder files naturally and keeps paths of subfolders", () => {
    const {accepted, skipped} = planImport([file("Hồ sơ/10.pdf"), file("Hồ sơ/2.pdf"), file("Hồ sơ/con/1.PDF"), file("Hồ sơ/a.jpg")], {fromFolder: true});
    expect(accepted.map(documentPath)).toEqual(["Hồ sơ/2.pdf", "Hồ sơ/10.pdf", "Hồ sơ/a.jpg", "Hồ sơ/con/1.PDF"]);
    expect(skipped).toEqual([]);
  });
  test("skips unsupported, empty and oversized files with a reason; system files silently", () => {
    const plan = planImport([file("d/a.pdf"), file("d/b.docx"), file("d/c.pdf", {size: 0}), file("d/big.pdf", {size: MAX_UPLOAD_BYTES + 1}),
      file("d/Thumbs.db"), file("d/desktop.ini"), file("d/.hidden.pdf"), file("d/~$tmp.pdf")], {fromFolder: true});
    expect(plan.accepted.map(documentPath)).toEqual(["d/a.pdf"]);
    expect(plan.skipped).toEqual([{path: "d/b.docx", reason: "unsupported"}, {path: "d/big.pdf", reason: "tooLarge"}, {path: "d/c.pdf", reason: "empty"}]);
    const message = describeImport(plan, {fromFolder: true});
    expect(message).toContain("Đã thêm 1 tài liệu, bỏ qua 3 tệp: 1 không phải PDF/PNG/JPG, 1 lớn hơn 15 MB, 1 tệp rỗng.");
    expect(message).toContain("d/big.pdf: Giới hạn kích thước tệp là 15 MB.");
  });
  test("a folder added twice does not duplicate documents; single files keep duplicate names", () => {
    const first = file("d/a.pdf");
    expect(planImport([file("d/a.pdf"), file("d/b.pdf")], {existing: [first], fromFolder: true}).skipped).toEqual([{path: "d/a.pdf", reason: "duplicate"}]);
    expect(planImport([new File(["%PDF"], "same.pdf")], {existing: [new File(["%PDF"], "same.pdf")]}).accepted).toHaveLength(1);
  });
  test("the list is capped and the rest reported, never silently dropped", () => {
    const existing = Array.from({length: MAX_BATCH_DOCUMENTS - 1}, (_, i) => file(`old/${i}.pdf`));
    const plan = planImport([file("n/1.pdf"), file("n/2.pdf"), file("n/3.pdf")], {existing, fromFolder: true});
    expect(plan.accepted).toHaveLength(1);
    expect(plan.skipped.map(item => item.reason)).toEqual(["limit", "limit"]);
    const many = describeImport({accepted: [], skipped: Array.from({length: 9}, (_, i) => ({path: `x${i}.zip`, reason: "unsupported"}))});
    expect(many).toContain("… và 4 tệp khác.");
    expect(many.split("\n")).toHaveLength(7);
  });
  test("a dropped folder is read recursively in chunks; plain drops stay plain", async () => {
    const a = new File(["%PDF"], "a.pdf"), b = new File(["%PDF"], "b.pdf"), c = new File(["%PDF"], "c.png"), loose = new File(["%PDF"], "loose.pdf");
    const drop = {files: [], items: [
      {kind: "file", webkitGetAsEntry: () => folderEntry("Hồ sơ", [fileEntry(a), folderEntry("con", [fileEntry(b)]), fileEntry(c)])},
      {kind: "file", webkitGetAsEntry: () => fileEntry(loose)}]};
    expect(dropHasFolder(drop)).toBe(true);
    const {files, fromFolder} = await filesFromDrop(drop);
    expect(fromFolder).toBe(true);
    expect(files.map(documentPath)).toEqual(["Hồ sơ/a.pdf", "Hồ sơ/con/b.pdf", "Hồ sơ/c.png", "loose.pdf"]);
    const plain = {files: [loose], items: [{kind: "file", webkitGetAsEntry: () => fileEntry(loose)}]};
    expect(dropHasFolder(plain)).toBe(false);
    expect(await filesFromDrop(plain)).toEqual({files: [loose], fromFolder: false});
  });
});

describe("batch helpers", () => {
  test("documents take a requested mode only when their type allows it", () => {
    expect(createBatchDocument(new File(["%PDF"], "a.pdf"), "1", {mode: "metadata_fast", path: "d/a.pdf"})).toMatchObject({mode: "metadata_fast", path: "d/a.pdf"});
    expect(createBatchDocument(new File(["x"], "a.png"), "2", {mode: "native_text"}).mode).toBe("vietocr_ocr");
    expect(createBatchDocument(new File(["%PDF"], "b.pdf"), "3")).toMatchObject({mode: "native_text", path: "b.pdf"});
    expect(modeAllowed("a.jpg", "metadata_fast")).toBe(true);
    expect(modeAllowed("a.jpg", "hybrid_h1")).toBe(false);
    expect(modeAllowed("a.pdf", "unknown")).toBe(false);
  });
  test("remaining time comes from the documents finished in this run", () => {
    expect(estimateRemainingMs(0, 0, 10, 5000)).toBeNull();
    expect(estimateRemainingMs(0, 2, 10, 20_000)).toBe(80_000);
    expect(estimateRemainingMs(0, 10, 10, 20_000)).toBeNull();
  });
});
