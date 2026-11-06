import {expect, test} from "vitest";
import {createBatchDocument} from "./documentBatch.js";
import {queueCounts, queueRows, searchKey, subfolder, visibleRows} from "./documentQueue.js";

const doc = (path, state = {}) => {
  const name = path.split("/").at(-1);
  return {...createBatchDocument(new File(["%PDF"], name), path, {path, mode:"metadata_fast"}), ...state};
};

test("search ignores accents, case and word order, and also reads the folder path", () => {
  expect(searchKey("Quyết Định ĐỒNG")).toBe("quyet dinh dong");
  const rows = queueRows([doc("Hồ sơ/2026/Quyết định 12.pdf"), doc("Hồ sơ/2025/Nghị định 136.pdf"), doc("Hồ sơ/2026/Thông báo.pdf")]);
  const names = options => visibleRows(rows, options).map(row => row.doc.name);
  expect(names({query:"quyet dinh"})).toEqual(["Quyết định 12.pdf"]);
  expect(names({query:"12 QUYẾT"})).toEqual(["Quyết định 12.pdf"]);
  expect(names({query:"2026"})).toEqual(["Quyết định 12.pdf", "Thông báo.pdf"]);
  expect(names({query:"  "})).toHaveLength(3);
  expect(names({query:"không có"})).toEqual([]);
});

test("a row keeps its place in the whole list when the view is filtered", () => {
  const rows = queueRows([doc("a.pdf"), doc("b.pdf"), doc("c.pdf")]);
  expect(visibleRows(rows, {query:"c.pdf"}).map(row => row.index)).toEqual([2]);
});

test("every status falls into one filter, and a running document still counts as not processed", () => {
  const rows = queueRows([doc("pending.pdf"), doc("running.pdf", {statesByMode:{metadata_fast:"processing"}}), doc("failed.pdf", {errorsByMode:{metadata_fast:"Lỗi"}})]);
  expect(rows.map(row => row.status)).toEqual(["pending", "processing", "error"]);
  expect(queueCounts(rows)).toEqual({pending:2,done:0,review:0,error:1});
  expect(visibleRows(rows, {filter:"pending"}).map(row => row.doc.name)).toEqual(["pending.pdf", "running.pdf"]);
  expect(visibleRows(rows, {filter:"error"}).map(row => row.doc.name)).toEqual(["failed.pdf"]);
  expect(visibleRows(rows, {filter:"all"})).toHaveLength(3);
});

test("only the folders below the chosen one are shown on a row", () => {
  expect(subfolder("a.pdf")).toBe("");
  expect(subfolder("Hồ sơ/a.pdf")).toBe("");
  expect(subfolder("Hồ sơ/con/a.pdf")).toBe("con");
  expect(subfolder("Hồ sơ/2026/tháng 3/a.pdf")).toBe("2026/tháng 3");
  expect(subfolder(undefined)).toBe("");
});
