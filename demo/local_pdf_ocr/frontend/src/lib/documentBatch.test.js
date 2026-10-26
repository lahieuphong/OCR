import {describe, expect, test, vi} from "vitest";
import {batchDocumentStatus, batchExportState, batchReducer, createBatchDocument, requestDocumentOcr, runDocumentQueue} from "./documentBatch.js";
import {syntheticDocument} from "../test/fixtures/administrativeDocuments.js";
import {editDocumentField} from "./documentFields.js";

const make = (id = "1", name = `${id}.pdf`) => createBatchDocument(new File(["%PDF"], name), id);
const response = (data, ok = true) => ({ok, json:async () => data});
const deferred = () => {let resolve; const promise = new Promise(r => {resolve = r;}); return {promise,resolve};};

describe("document queue", () => {
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
