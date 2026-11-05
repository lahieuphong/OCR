// @vitest-environment jsdom
import React from "react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App.jsx";
import {syntheticDocument} from "./test/fixtures/administrativeDocuments.js";
import {fastMetadataDocument} from "./test/fixtures/fastMetadata.js";

const file=name=>new File(["%PDF synthetic"],name,{type:"application/pdf"});
const field=key=>document.getElementById(`metadata-${key}`);
const list=()=>screen.getByRole("tab",{name:"Danh sách văn bản"});
let calls, failures;
beforeEach(()=>{
  calls=[]; failures=new Set();
  vi.stubGlobal("fetch",vi.fn(async(url,options)=>{
    if(url==="/api/health")return {ok:true,json:async()=>({state:"ready_to_initialize"})};
    const name=options.body.get("file").name,mode=options.body.get("mode"); calls.push({name,mode});
    const failed=failures.delete(name);
    return {ok:!failed,json:async()=>failed ? {detail:`Lỗi thử nghiệm ${name}`} : mode === "metadata_fast"
      ? fastMetadataDocument({code:`00${name[0]}/FAST`}) : syntheticDocument({method:mode,code:`00${name[0]}/${mode === "native_text" ? "NATIVE" : "OCR"}`})};
  }));
  URL.createObjectURL=vi.fn(()=>"blob:http://127.0.0.1/synthetic"); URL.revokeObjectURL=vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{});
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
async function setup(names=["1.pdf","2.pdf","3.pdf"]){
  const user=userEvent.setup(); render(<App/>);
  await user.upload(screen.getByLabelText("Chọn tài liệu PDF hoặc ảnh"),names.map(file));
  // New documents start in the fast header mode; one choice switches every pending document.
  expect(Array.from(document.querySelectorAll(".input-queue li select"),s=>s.value).every(v=>v==="metadata_fast")).toBe(true);
  await user.selectOptions(screen.getByLabelText("Phương pháp cho tất cả tài liệu"),"native_text");
  await waitFor(()=>expect(document.querySelector(".run-button").disabled).toBe(false));
  return user;
}
async function runBatch(user){
  await user.click(screen.getByRole("button",{name:/^Bóc tách tất cả \(/}));
  await screen.findByRole("tab",{name:"Danh sách văn bản",selected:true});
}
test("picker accepts duplicate names independently, add/drop/remove works before processing, export starts disabled",async()=>{
  const user=await setup(["same.pdf","same.pdf"]);
  await user.click(list()); expect(screen.getByRole("button",{name:"Xuất danh sách Excel"}).disabled).toBe(true);
  expect(document.querySelectorAll(".input-queue li")).toHaveLength(2);
  const ids=Array.from(document.querySelectorAll(".batch-table tbody tr"),tr=>tr.dataset.documentId);
  expect(new Set(ids).size).toBe(2);
  fireEvent.drop(document.querySelector(".dropzone"),{dataTransfer:{files:[file("3.pdf"),file("4.pdf")]}});
  expect(document.querySelectorAll(".input-queue li")).toHaveLength(4);
  await user.click(screen.getByRole("button",{name:"Xóa tài liệu 2: same.pdf"}));
  await user.click(list());
  expect(document.querySelectorAll(".batch-table tbody tr")).toHaveLength(3);
  expect(calls).toEqual([]);
});
test("three PDF results retain per-file modes and manual metadata across documents and tabs",async()=>{
  const user=await setup();
  await user.selectOptions(screen.getByLabelText("Phương pháp tài liệu 2"),"vietocr_ocr");
  await runBatch(user);
  expect(calls).toEqual([{name:"1.pdf",mode:"native_text"},{name:"2.pdf",mode:"vietocr_ocr"},{name:"3.pdf",mode:"native_text"}]);
  expect(document.querySelectorAll(".batch-table tbody tr")).toHaveLength(3);
  await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  await user.clear(field("subject")); await user.type(field("subject"),"Chỉnh riêng tài liệu một");
  await user.click(list()); await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 2: 2.pdf"}));
  expect(field("arcDocCode").value).toBe("002/OCR"); expect(field("subject").value).not.toBe("Chỉnh riêng tài liệu một");
  await user.click(list()); await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  expect(field("subject").value).toBe("Chỉnh riêng tài liệu một");
  await user.click(screen.getByRole("tab",{name:"Toàn văn"}));
  expect(document.querySelector(".text-output pre").textContent).not.toContain("Chỉnh riêng tài liệu một");
  await user.click(list()); await user.click(screen.getByRole("button",{name:"Xác nhận tài liệu 1"}));
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Đã kiểm tra"}));
  expect(document.querySelector(".batch-table tbody tr .batch-status").textContent).toBe("Đã xác nhận");
  await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  await user.type(field("subject")," sửa tiếp"); await user.click(list());
  expect(document.querySelector(".batch-table tbody tr .batch-status").textContent).toBe("Cần kiểm tra");
});
test.each(["native_text","metadata_fast"])("%s middle failure keeps results one/three, warns on partial export, retries only failed file",async mode=>{
  failures.add("2.pdf"); const user=await setup();
  if(mode==="metadata_fast")for(let i=1;i<=3;i++) await user.selectOptions(screen.getByLabelText(`Phương pháp tài liệu ${i}`),mode);
  await runBatch(user);
  expect(calls).toHaveLength(3);
  expect(calls.every(call=>call.mode===mode)).toBe(true);
  const rows=Array.from(document.querySelectorAll(".batch-table tbody tr"));
  expect(rows.map(row=>row.querySelector(".batch-status").textContent)).toEqual(["Cần kiểm tra","Lỗi","Cần kiểm tra"]);
  expect(within(rows[1]).getByRole("checkbox").disabled).toBe(true);
  await user.click(screen.getByRole("button",{name:"Xuất danh sách Excel"}));
  const dialog=screen.getByRole("alertdialog");
  expect(dialog.textContent).toContain("Xuất 2/3"); expect(dialog.textContent).toContain("1 tài liệu chưa xử lý, lỗi");
  expect(dialog.textContent).toContain("01 · Công khai");
  await user.click(within(dialog).getByRole("button",{name:"Hủy"}));
  await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  if(mode==="metadata_fast")expect(field("numberOfPage").value).toBe("6");
  await user.clear(field("subject")); await user.type(field("subject"),"Bản sửa riêng được giữ sau retry");
  await user.click(list());
  await user.click(screen.getByRole("button",{name:"Thử lại"}));
  await waitFor(()=>expect(field("arcDocCode")?.value).toBe(mode==="metadata_fast" ? "002/FAST" : "002/NATIVE"));
  expect(calls.map(call=>call.name)).toEqual(["1.pdf","2.pdf","3.pdf","2.pdf"]);
  await user.click(list()); expect(document.querySelectorAll(".batch-status.error")).toHaveLength(0);
  expect(document.querySelectorAll(".batch-table tbody tr")).toHaveLength(3);
  await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  expect(field("subject").value).toBe("Bản sửa riêng được giữ sau retry");
});
test("unprocessed PDF cannot become an export row; invalid dates disable export",async()=>{
  const user=await setup(["1.pdf","2.pdf"]);
  await user.click(screen.getByRole("button",{name:"Bóc tách văn bản này"}));
  await waitFor(()=>expect(field("arcDocCode")?.value).toBe("001/NATIVE"));
  await user.click(list()); await user.click(screen.getByRole("button",{name:"Xuất danh sách Excel"}));
  expect(screen.getByRole("alertdialog").textContent).toContain("Xuất 1/2");
  await user.click(within(screen.getByRole("alertdialog")).getByRole("button",{name:"Hủy"}));
  await user.click(screen.getByRole("button",{name:"Mở thông tin tài liệu 1: 1.pdf"}));
  await user.clear(field("issuedDate")); await user.type(field("issuedDate"),"31-02-2026"); await user.click(list());
  expect(screen.getByRole("button",{name:"Xuất danh sách Excel"}).disabled).toBe(true);
});
