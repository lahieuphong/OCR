import {describe, expect, test, vi} from "vitest";
import {batchDocumentStatus, batchExportState, batchReducer, createBatchDocument, requestDocumentOcr, runDocumentQueue} from "./documentBatch.js";
import {syntheticDocument} from "../test/fixtures/administrativeDocuments.js";
import {editDocumentField} from "./documentFields.js";
import {fastMetadataDocument} from "../test/fixtures/fastMetadata.js";

const make = (id = "1", name = `${id}.pdf`) => createBatchDocument(new File(["%PDF"], name), id);
const response = (data, ok = true) => ({ok, json:async () => data});
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise,resolve};};

describe("document queue", () => {
  test.each([false,true])("fast mode preserves six source pages and literal OCR scope (native=%s)", async native => {
    const doc=make(); doc.mode="metadata_fast";
    const raw=fastMetadataDocument({native}), snapshot=JSON.stringify(raw);
    const request=vi.fn(async()=>response(raw));
    const result=await requestDocumentOcr(doc,request);
    expect(request.mock.calls[0][1].body.get("mode")).toBe("metadata_fast");
    expect(result.draft.fields.numberOfPage.value).toBe("6");
    expect(result.raw.processed_pages).toEqual(native ? [] : [1]);
    expect(result.raw).toBe(raw); expect(JSON.stringify(raw)).toBe(snapshot);
  });
  test.each(["png","jpg"])("fast image %s is explicit and retains one source page", async ext => {
    const doc=make("img",`image.${ext}`); doc.mode="metadata_fast";
    const result=await requestDocumentOcr(doc,async()=>response(fastMetadataDocument({sourcePages:1})));
    expect(result.draft.fields.numberOfPage.value).toBe("1");
    await expect(requestDocumentOcr(doc,async()=>response(fastMetadataDocument({sourcePages:6})))).rejects.toThrow("Ảnh nguồn phải có đúng một trang");
  });
  test.each([
    ["missing source count",raw=>{delete raw.source_page_count;}],
    ["not partial",raw=>{raw.partial_result=false;}],
    ["invalid source count",raw=>{raw.source_page_count=0;}],
    ["source count over limit",raw=>{raw.source_page_count=1001;}],
    ["OCR beyond inspected pages",raw=>{raw.processed_pages=[2];}],
    ["page IDs do not match",raw=>{raw.pages[0].page=2;}],
    ["appendix substituted consistently",raw=>{raw.pages[0].page=2;raw.inspected_pages=[2];raw.processed_pages=[2];}],
    ["full two-page response disguised as fast",raw=>{raw.source_page_count=2;raw.page_count=2;raw.inspected_pages=[1,2];raw.processed_pages=[1,2];raw.pages.push({...raw.pages[0],page:2});}],
    ["full-page OCR ROI disguised as header",raw=>{raw.pages[0].roi[3]=raw.pages[0].height;}],
    ["ROI below allowed header extent",raw=>{raw.pages[0].roi[3]=raw.pages[0].height*.9;}],
    ["non-finite ROI",raw=>{raw.pages[0].roi[2]=NaN;}],
    ["unordered ROI",raw=>{raw.pages[0].roi[3]=0;}],
    ["ROI exceeds page width",raw=>{raw.pages[0].roi[2]=raw.pages[0].width+20;}],
    ["missing full-page dimensions",raw=>{delete raw.pages[0].height;}],
    ["wrong coordinate system",raw=>{raw.pages[0].coordinate_system="pdf_points";}],
    ["wrong line geometry source",raw=>{raw.pages[0].lines[0].geometry_source="native_text";}],
    ["full-text payload differs from header page",raw=>{raw.text+="\nUninspected appendix content";}],
    ["page payload differs from literal lines",raw=>{raw.pages[0].text="changed";}],
    ["invented line count",raw=>{raw.line_count++;}],
    ["missing line array",raw=>{delete raw.pages[0].lines;}],
    ["unstable line indices",raw=>{raw.pages[0].lines[0].line_index=20;}],
    ["invented OCR flag",raw=>{raw.used_ocr=false;}],
    ["unknown header source",raw=>{raw.source="native_text";}],
    ["missing review decision",raw=>{delete raw.fast_metadata.needs_review;}],
  ])("rejects malformed fast contract: %s", async (_label,mutate) => {
    const doc=make(); doc.mode="metadata_fast"; const raw=fastMetadataDocument(); mutate(raw);
    const request=vi.fn(async()=>response(raw));
    await expect(requestDocumentOcr(doc,request)).rejects.toThrow("số trang nguồn");
    expect(request).toHaveBeenCalledOnce();
  });
  test("fast contract accepts a long source PDF: only page 1 was read", async () => {
    const doc=make(); doc.mode="metadata_fast"; const raw=fastMetadataDocument(); raw.source_page_count=40;
    const {draft}=await requestDocumentOcr(doc,vi.fn(async()=>response(raw)));
    expect(draft.fields.numberOfPage.value).toBe("40");
  });
  test("fast queue continues after second failure and retry leaves prior manual drafts isolated", async () => {
    const docs=[make("1"),make("2"),make("3")]; docs.forEach(doc=>{doc.mode="metadata_fast";});
    let live=0,peak=0,index=0;
    const request=vi.fn(async()=>{peak=Math.max(peak,++live); const i=index++; await Promise.resolve(); live--;
      return i===1 ? response({detail:"Fast synthetic failure"},false) : response(fastMetadataDocument({code:`00${i+1}/TEST`}));});
    const handlers={request,onSuccess:(doc,{raw,draft})=>{doc.resultsByMode.metadata_fast=raw;doc.metadataByMode.metadata_fast=draft;},
      onError:(doc,error)=>{doc.errorsByMode.metadata_fast=error;}};
    await runDocumentQueue(docs,handlers);
    expect(peak).toBe(1); expect(request).toHaveBeenCalledTimes(3);
    expect(docs[1].errorsByMode.metadata_fast).toBe("Fast synthetic failure");
    docs[0].metadataByMode.metadata_fast=editDocumentField(docs[0].metadataByMode.metadata_fast,"subject","Manual draft kept");
    const retained=docs[0].metadataByMode.metadata_fast;
    await runDocumentQueue([docs[1]],handlers);
    expect(request).toHaveBeenCalledTimes(4); expect(docs[0].metadataByMode.metadata_fast).toBe(retained);
    expect(docs[2].metadataByMode.metadata_fast.fields.arcDocCode.value).toBe("003/TEST");
    expect(docs[1].metadataByMode.metadata_fast.fields.numberOfPage.value).toBe("6");
  });
  test("hybrid requires an explicit PDF selection and a retained OCR baseline", async () => {
    const doc = make(); doc.mode = "hybrid_h1";
    const raw = {...syntheticDocument({method:"hybrid_h1"}), experimental:true,
      ocr_result:syntheticDocument({method:"vietocr_ocr"})};
    const request = vi.fn(async () => response(raw));
    expect((await requestDocumentOcr(doc, request)).raw).toBe(raw);
    expect(request.mock.calls[0][1].body.get("mode")).toBe("hybrid_h1");
    await expect(requestDocumentOcr(doc, async()=>response({...raw,ocr_result:null}))).rejects.toThrow("OCR gốc");
    await expect(requestDocumentOcr({...doc,name:"image.png"},request)).rejects.toThrow("không phù hợp");
    expect(request).toHaveBeenCalledOnce();
  });
  test("one PDF sends exactly its chosen mode and keeps the untouched raw response", async () => {
    const doc = make(), raw = syntheticDocument(), snapshot = JSON.stringify(raw);
    const request = vi.fn(async () => response(raw));
    const result = await requestDocumentOcr(doc, request);
    expect(request).toHaveBeenCalledOnce();
    expect(request.mock.calls[0][0]).toBe("/api/ocr");
    const payload = request.mock.calls[0][1].body;
    expect(payload.get("file").name).toBe("1.pdf"); expect(payload.get("mode")).toBe("native_text");
    expect(result.raw).toBe(raw); expect(JSON.stringify(raw)).toBe(snapshot);
    expect(result.draft.fields.arcDocCode.value).toBe("00103/TEST-CN");
  });
  test("three PDFs are strictly sequential; failure at position two preserves successes and continues", async () => {
    const gates = [deferred(),deferred(),deferred()], docs = [make("1"),make("2"),make("3")];
    docs[2].mode = "vietocr_ocr";
    let live = 0, peak = 0;
    const modes = [], success = [], errors = [], progress = [];
    const request = vi.fn(async (_url, options) => {
      const index = modes.length; modes.push(options.body.get("mode")); peak = Math.max(peak,++live);
      await gates[index].promise; live--;
      return response(index === 1 ? {detail:"Synthetic failure"} : syntheticDocument({method:modes[index],code:`00${index+1}/TEST`}), index !== 1);
    });
    const job = runDocumentQueue(docs,{request,onSuccess:(doc,result)=>success.push([doc.id,result]),onError:(doc,error)=>errors.push([doc.id,error]),onProgress:(...args)=>progress.push(args)});
    expect(request).toHaveBeenCalledTimes(1);
    gates[0].resolve(); await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
    gates[1].resolve(); await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(3));
    gates[2].resolve(); await job;
    expect(peak).toBe(1); expect(modes).toEqual(["native_text","native_text","vietocr_ocr"]);
    expect(success.map(([id])=>id)).toEqual(["1","3"]);
    expect(success.map(([,result])=>result.draft.fields.arcDocCode.value)).toEqual(["001/TEST","003/TEST"]);
    expect(errors).toEqual([["2","Synthetic failure"]]); expect(progress).toEqual([[1,3],[2,3],[3,3]]);
  });
  test.each(["wrong-mode","invalid-pages","bad-json","empty-text"])("rejects %s without retry or fallback", async kind => {
    const request=vi.fn(async()=> kind === "bad-json" ? {ok:true,json:async()=>{throw Error("bad");}} : response({method:kind === "wrong-mode" ? "vietocr_ocr" : "native_text",pages:kind === "empty-text" ? [] : null,text:""}));
    await expect(requestDocumentOcr(make(),request)).rejects.toThrow();
    expect(request).toHaveBeenCalledOnce();
  });
  test("stops between requests when the owning UI has unmounted", async () => {
    let mounted=true; const request=vi.fn(async()=>response(syntheticDocument()));
    await runDocumentQueue([make("1"),make("2")],{request,shouldContinue:()=>mounted,onSuccess:()=>{mounted=false;}});
    expect(request).toHaveBeenCalledOnce();
  });
  test("duplicate names have distinct session IDs and immutable add/remove/update preserves order", () => {
    const first=createBatchDocument(new File(["a"],"same.pdf")), second=createBatchDocument(new File(["b"],"same.pdf"));
    expect(first.id).not.toBe(second.id);
    const added=batchReducer([],{type:"add",documents:[first,second]});
    const updated=batchReducer(added,{type:"update",id:first.id,update:doc=>({...doc,mode:"vietocr_ocr"})});
    expect(added[0].mode).toBe("native_text"); expect(updated[1]).toBe(second);
    expect(batchReducer(updated,{type:"remove",id:first.id})).toEqual([second]);
  });
  test("export eligibility follows selected mode, excludes invalid/error/unprocessed/unselected documents", async () => {
    const docs=Array.from({length:5},(_,i)=>make(String(i)));
    for (const doc of docs.slice(0,4)) {
      const {raw,draft}=await requestDocumentOcr(doc,async()=>response(syntheticDocument()));
      doc.resultsByMode.native_text=raw; doc.metadataByMode.native_text=draft;
    }
    docs[1].errorsByMode.native_text="error";
    docs[2].metadataByMode.native_text=editDocumentField(docs[2].metadataByMode.native_text,"issuedDate","31-02-2026");
    docs[3].includeInExport=false;
    expect(batchExportState(docs).ready.map(doc=>doc.id)).toEqual(["0"]);
    expect(batchExportState(docs).unresolved.map(doc=>doc.id)).toEqual(["1","2","4"]);
    expect(batchDocumentStatus(docs[0])).toBe("review");
    docs[0].confirmedByMode.native_text=true; expect(batchDocumentStatus(docs[0])).toBe("confirmed");
    docs[0].mode="vietocr_ocr"; expect(batchDocumentStatus(docs[0])).toBe("pending");
    expect(batchExportState(docs).ready).toHaveLength(0);
  });
});
