import {afterEach, describe, expect, test} from "vitest";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import ExcelJS from "exceljs";
import {createDocumentWorkbook} from "./excelExport.js";
import {createBatchDocument} from "./documentBatch.js";
import {createDocumentDraft, documentValues, editDocumentField} from "./documentFields.js";
import {SYNTHETIC_CASES, syntheticDocument} from "../test/fixtures/administrativeDocuments.js";
import {fastMetadataDocument, DECREE_SUBJECT} from "../test/fixtures/fastMetadata.js";
import {STAMP_TEST_SUBJECT,stampSubjectDocument} from "../test/fixtures/stampSubject.js";

const folders = [];
afterEach(async () => {for (const folder of folders.splice(0)) await fs.rm(folder,{recursive:true,force:true});});
function records() {
  return ["officialLetter","decision","resolution"].map((name, i) => {
    const doc = createBatchDocument({name:name + ".pdf"}, "test-" + i);
    doc.resultsByMode.native_text = SYNTHETIC_CASES[name];
    doc.metadataByMode.native_text = createDocumentDraft(SYNTHETIC_CASES[name]);
    return doc;
  });
}
async function reopen(docs = records()) {
  const folder = await fs.mkdtemp(path.join(os.tmpdir(),"vietdoc-xlsx-")); folders.push(folder);
  const file = path.join(folder,"Danh_sach_van_ban.xlsx");
  await fs.writeFile(file, Buffer.from(await createDocumentWorkbook(docs)));
  expect((await fs.readFile(file)).subarray(0,2).toString()).toBe("PK");
  const book = new ExcelJS.Workbook(); await book.xlsx.readFile(file);
  return {book,sheet:book.getWorksheet("Danh sách văn bản")};
}
describe("saved/reopened XLSX", () => {
  test("stamp-contaminated candidate is blank in XLSX until a manual subject is entered", async () => {
    const docs=[0,1].map(index=>{
      const doc=createBatchDocument({name:`fictional-stamp-${index}.pdf`},`stamp-${index}`),raw=stampSubjectDocument({stamp:true,merged:"mixed"});
      doc.mode="metadata_fast";doc.resultsByMode.metadata_fast=raw;doc.metadataByMode.metadata_fast=createDocumentDraft(raw);return doc;
    });
    docs[1].metadataByMode.metadata_fast=editDocumentField(docs[1].metadataByMode.metadata_fast,"subject",STAMP_TEST_SUBJECT);
    const before=docs.map(doc=>JSON.stringify(doc.resultsByMode.metadata_fast)),{book,sheet}=await reopen(docs);
    expect(sheet.columnCount).toBe(23);expect(sheet.getCell("J2").value).toBeNull();expect(sheet.getCell("J3").value).toBe(STAMP_TEST_SUBJECT);
    expect(sheet.getCell("F2").value).toBe("00042");expect(sheet.getCell("L2").value).toBe("6");
    for(const row of [2,3]) {expect(sheet.getCell(row,10).font).toMatchObject({name:"Times New Roman",size:13});expect(book.getWorksheet("Nguồn tài liệu").getCell(row,3).value).toBe("metadata_fast");}
    expect(JSON.stringify(book.worksheets.map(ws=>ws.getSheetValues()))).not.toContain("Ngày: 03/02/2025");
    expect(docs.map(doc=>JSON.stringify(doc.resultsByMode.metadata_fast))).toEqual(before);
  });
  test("fast six-page source round trips real XLSX and passes the independent provenance checker", async () => {
    const doc=createBatchDocument({name:"synthetic-fast.pdf"},"fast-six-source-pages"), raw=fastMetadataDocument({code:"00042/2025/NĐ-QA"});
    doc.mode="metadata_fast"; doc.resultsByMode.metadata_fast=raw;
    doc.metadataByMode.metadata_fast=editDocumentField(createDocumentDraft(raw),"description","=literal QA text");
    const values=documentValues(doc.metadataByMode.metadata_fast), before=JSON.stringify(raw);
    expect(values.numberOfPage).toBe("6"); expect(values.codeNumber).toBe("00042"); expect(values.typeName).toBe("");
    expect(values.subject).toBe(DECREE_SUBJECT); expect(values.mode).toBe("");
    const folder=await fs.mkdtemp(path.join(os.tmpdir(),"vietdoc-fast-xlsx-checker-")); folders.push(folder);
    const workbook=path.join(folder,"Danh_sach_van_ban.xlsx"),expected=path.join(folder,"expected.json");
    await fs.writeFile(workbook,Buffer.from(await createDocumentWorkbook([doc])));
    await fs.writeFile(expected,JSON.stringify([values]),"utf8");
    const book=new ExcelJS.Workbook();await book.xlsx.readFile(workbook);
    const sheet=book.getWorksheet("Danh sách văn bản");
    expect(sheet.columnCount).toBe(23); expect(sheet.getCell("A2").value).toBe(1);
    expect(sheet.getCell("F2").value).toBe("00042"); expect(sheet.getCell("L2").value).toBe("6");
    expect(sheet.getCell("V2").value).toBe("=literal QA text"); expect(sheet.getCell("V2").formula).toBeUndefined();
    expect(book.getWorksheet("Nguồn tài liệu").getCell("C2").value).toBe("metadata_fast");
    const checker=fileURLToPath(new URL("../../../../../desktop/scripts/check_excel_export.py",import.meta.url));
    const result=spawnSync(process.env.VIETDOC_TEST_PYTHON||"python",["-B","-X","utf8",checker,workbook,"--rows=1","--expected-json",expected],{encoding:"utf8"});
    expect(result.error).toBeUndefined(); expect(result.status,result.stderr).toBe(0);
    expect(JSON.parse(result.stdout)).toMatchObject({status:"PASS",columns:23,ui_values_equal:true});
    expect(JSON.stringify(raw)).toBe(before);
  });
  test.each([{mode:"hybrid_h1", accepted:true}, {mode:"unknown_method", accepted:false}])(
    "independent XLSX checker validates $mode processing provenance", async ({mode,accepted}) => {
      const doc = createBatchDocument({name:"synthetic-hybrid.pdf"}, "checker-provenance");
      const raw = {...syntheticDocument({method:"hybrid_h1"}), experimental:true,
        ocr_result:syntheticDocument({method:"vietocr_ocr"})};
      doc.mode = mode;
      doc.resultsByMode[mode] = raw;
      doc.metadataByMode[mode] = createDocumentDraft(raw);
      const values = documentValues(doc.metadataByMode[mode]);
      // Access-classification metadata is independent of the source processing method.
      expect(values.mode).toBe("");
      const folder = await fs.mkdtemp(path.join(os.tmpdir(),"vietdoc-xlsx-checker-")); folders.push(folder);
      const workbook = path.join(folder,"Danh_sach_van_ban.xlsx");
      const expected = path.join(folder,"expected.json");
      await fs.writeFile(workbook,Buffer.from(await createDocumentWorkbook([doc])));
      await fs.writeFile(expected,JSON.stringify([values]),"utf8");
      const checker = fileURLToPath(new URL("../../../../../desktop/scripts/check_excel_export.py",import.meta.url));
      const result = spawnSync(process.env.VIETDOC_TEST_PYTHON || "python",
        ["-B","-X","utf8",checker,workbook,"--rows=1","--expected-json",expected],{encoding:"utf8"});
      expect(result.error).toBeUndefined();
      if (accepted) {
        expect(result.status, result.stderr).toBe(0);
        expect(JSON.parse(result.stdout)).toMatchObject({status:"PASS",columns:23,ui_values_equal:true});
      } else {
        expect(result.status).not.toBe(0);
        expect(result.stderr).toContain("AssertionError");
      }
    });
  test("has exactly 23 columns, one header row and three ordered document rows", async () => {
    const {sheet} = await reopen();
    expect(sheet.columnCount).toBe(23); expect(sheet.rowCount).toBe(4);
    expect(sheet.getRow(1).values.slice(1)).toEqual(["STT","Mã tài liệu","Mã văn bản","Thời hạn lưu trữ","Loại tài liệu","Số tài liệu","Ký hiệu văn bản","Ngày ban hành","Cơ quan ban hành","Trích yếu nội dung","Ngôn ngữ","Số trang","Ký hiệu thông tin","Từ khóa","Chế độ sử dụng","Mức độ tin cậy","Bút tích","Tình trạng vật lý","Quy trình xử lý","Chế độ dự phòng","Tình trạng dự phòng","Ghi chú","Màu con dấu"]);
    expect([2,3,4].map(row => sheet.getCell(row,1).value)).toEqual([1,2,3]);
    expect([2,3,4].map(row => sheet.getCell(row,3).value)).toEqual(["00103/TEST-CN","00002/QĐ-TEST","00321/NQ-TEST"]);
    expect(sheet.model.merges).toEqual([]);
  });
  test("every cell including blank cells uses Times New Roman 13, borders and wrap", async () => {
    const {book,sheet} = await reopen();
    for (const ws of book.worksheets) ws.eachRow({includeEmpty:true}, row => {
      for (let c=1;c<=ws.columnCount;c++) {
        const cell=row.getCell(c);
        expect(cell.font.name).toBe("Times New Roman"); expect(cell.font.size).toBe(13);
        expect(cell.border.top.style).toBe("thin"); expect(cell.alignment.wrapText).toBe(true);
      }
    });
    expect(sheet.getCell("A1").font.bold).toBe(true); expect(sheet.getCell("A1").fill.fgColor.argb).toBe("FFDBEAFE");
    expect(sheet.getCell("A2").alignment.horizontal).toBe("center"); expect(sheet.getCell("J2").alignment.horizontal).toBe("left");
    expect(sheet.getCell("J2").fill.fgColor.argb).toBe("FFFFFFFF");
  });
  test("preserves codes, Unicode, blank docId and unambiguous text dates", async () => {
    const docs=records(); docs[0].metadataByMode.native_text=editDocumentField(docs[0].metadataByMode.native_text,"maintenance","01");
    const {sheet}=await reopen(docs);
    expect(sheet.getCell("D2").value).toBe("01"); expect(sheet.getCell("E3").value).toBe("02");
    expect(sheet.getCell("F2").value).toBe("00103"); expect(sheet.getCell("G3").value).toBe("QĐ-TEST");
    expect(sheet.getCell("H2").value).toBe("08-10-2026"); expect(sheet.getCell("H2").numFmt).toBe("@");
    expect(sheet.getCell("I2").value).toBe("VĂN PHÒNG KIỂM THỬ");
    expect(sheet.getCell("B2").value).toBeNull(); expect(sheet.getCell("M2").value).toBeNull();
    expect(sheet.getCell("L2").value).toBe("1");
  });
  test("freeze panes and AutoFilter cover the actual table", async () => {
    const {sheet}=await reopen();
    expect(sheet.views[0]).toMatchObject({state:"frozen",xSplit:1,ySplit:1,topLeftCell:"B2"});
    expect(sheet.autoFilter).toBe("A1:W4");
    expect(sheet.getColumn(10).width).toBeGreaterThan(40); expect(sheet.getColumn(10).width).toBeLessThanOrEqual(70);
  });
  test.each(["=HYPERLINK(\"https://invalid.example\",\"x\")","+cmd|' /C calc'!A0","-1+1","@SUM(A1:A2)","\t=1+1"])("stores %s as literal text, never a formula", async text => {
    const docs=records(); docs[0].metadataByMode.native_text=editDocumentField(docs[0].metadataByMode.native_text,"description",text);
    const {sheet}=await reopen(docs);
    expect(sheet.getCell("V2").value).toBe(text); expect(sheet.getCell("V2").formula).toBeUndefined(); expect(sheet.getCell("V2").type).toBe(ExcelJS.ValueType.String);
  });
  test("keeps long text intact and bounds display row height", async () => {
    const docs=records(), text="Tiếng Việt dài có dấu. ".repeat(300);
    docs[0].metadataByMode.native_text=editDocumentField(docs[0].metadataByMode.native_text,"subject",text);
    const {sheet}=await reopen(docs);
    expect(sheet.getCell("J2").value).toBe(text); expect(sheet.getRow(2).height).toBeLessThanOrEqual(120);
    expect(sheet.getCell("J2").alignment.wrapText).toBe(true);
  });
  test("rejects overflow and invalid control characters instead of silently dropping text", async () => {
    const docs=records(); docs[0].metadataByMode.native_text=editDocumentField(docs[0].metadataByMode.native_text,"description","a".repeat(32768));
    await expect(createDocumentWorkbook(docs)).rejects.toThrow("32.767");
    docs[0].metadataByMode.native_text=editDocumentField(docs[0].metadataByMode.native_text,"description","bad\u0000text");
    await expect(createDocumentWorkbook(docs)).rejects.toThrow("ký tự điều khiển");
  });
  test("omits pending/error/unselected rows and renumbers the remaining documents", async () => {
    const docs=records(); docs[1].errorsByMode.native_text="synthetic error";
    docs.push(createBatchDocument({name:"pending.pdf"},"pending"));
    const {sheet}=await reopen(docs);
    expect(sheet.rowCount).toBe(3); expect(sheet.getCell("A3").value).toBe(2); expect(sheet.getCell("C3").value).toBe("00321/NQ-TEST");
    docs[0].includeInExport=false; docs[2].includeInExport=false;
    await expect(createDocumentWorkbook(docs)).rejects.toThrow("Chưa có");
  });
  test("exports only approved metadata and basename provenance, without raw/context secrets", async () => {
    const docs=records(); docs[0].name="C:\\private\\folder\\same.pdf";
    docs[0].resultsByMode.native_text={...docs[0].resultsByMode.native_text,token:"secret-test-token",model_hash:"private-hash",path:"C:/private/context"};
    const before=JSON.stringify(docs[0].resultsByMode.native_text);
    const {book}=await reopen(docs);
    const strings=JSON.stringify(book.worksheets.map(s=>s.getSheetValues()));
    expect(strings).not.toContain("secret-test-token"); expect(strings).not.toContain("private-hash"); expect(strings).not.toContain("private\\");
    expect(book.getWorksheet("Nguồn tài liệu").getCell("B2").value).toBe("same.pdf");
    expect(JSON.stringify(docs[0].resultsByMode.native_text)).toBe(before);
  });
});
