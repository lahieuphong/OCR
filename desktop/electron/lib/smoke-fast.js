'use strict';
// Opt-in internal QA of the real fast UI and its actual downloads. No fixture-specific
// document values or expected recognition text enter the production extraction path.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const KEYS = ['docId','arcDocCode','maintenance','typeName','codeNumber','codeNotation','issuedDate','organName',
  'subject','language','numberOfPage','inforSign','keyword','mode','confidenceLevel','autograph','format','process',
  'riskRecovery','riskRecoveryStatus','description','isCan'];

function validateFastScope(result) {
  assert.equal(result.method, 'metadata_fast');
  assert.equal(result.partial_result, true);
  assert.ok(Number.isInteger(result.source_page_count) && result.source_page_count >= 1 && result.source_page_count <= 6);
  assert.deepEqual(result.inspected_pages, [1], 'fast mode must not silently inspect later pages');
  assert.ok(Array.isArray(result.processed_pages));
  assert.ok(result.processed_pages.length <= 1 && result.processed_pages.every(page => page === 1), 'fast mode must never OCR appendices');
  assert.equal(result.used_ocr, result.processed_pages.length === 1);
  assert.equal(result.page_count, result.pages.length);
  assert.equal(result.pages.length, 1);
  assert.equal(result.pages[0].page, 1);
  assert.equal(result.text, result.pages[0].text);
  return {source_page_count: result.source_page_count, inspected_pages: result.inspected_pages,
    processed_pages: result.processed_pages, partial_result: result.partial_result, line_count: result.line_count};
}

async function runFastSmoke({wc, js, clickResultTab, setInputFile, waitFor, screenshot, smokeDir, pdf, batchDir, goldFile, checks}) {
  const downloads = path.join(smokeDir, 'downloads');
  const wait = async (condition, message, timeout = 10_000) => assert.ok(await waitFor(async () => condition(), timeout), message);
  async function acceptDialog() {
    if (await js(`Boolean(document.querySelector('dialog[open]'))`)) {
      await js(`document.querySelector('dialog .confirm-actions button:last-child').click(); true`);
    }
  }
  async function clearQueue() {
    while (await js(`document.querySelectorAll('.remove-document').length`)) {
      const count = await js(`document.querySelectorAll('.remove-document').length`);
      await js(`document.querySelector('.remove-document').click(); true`);
      await wait(() => js(`document.querySelectorAll('.remove-document').length < ${count} || Boolean(document.querySelector('dialog[open]'))`), 'remove confirmation did not render');
      await acceptDialog();
      await wait(() => js(`document.querySelectorAll('.remove-document').length < ${count}`), 'input was not removed');
    }
  }
  async function values() {
    await wait(() => js(`document.querySelectorAll('.metadata-field input, .metadata-field select, .metadata-field textarea').length === 22`), 'fast metadata form must have22fields');
    return js(`Object.fromEntries(${JSON.stringify(KEYS)}.map(key => [key, document.querySelector('#metadata-'+key).value]))`);
  }
  async function editSubject(value) {
    await js(`(() => { const field = document.querySelector('#metadata-subject');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, ${JSON.stringify(value)});
      field.dispatchEvent(new Event('input', {bubbles:true})); })()`);
    await wait(() => js(`document.querySelector('#metadata-subject').value === ${JSON.stringify(value)}`), 'fast edit not retained');
  }
  await clearQueue();
  await js(`(() => {
    const original = window.fetch;
    window.__vietdocFastQA = {original, active:0, peak:0, requests:[]};
    window.fetch = async function(url, options) {
      if (url !== '/api/ocr') return original.call(this, url, options);
      const qa = window.__vietdocFastQA;
      qa.peak = Math.max(qa.peak, ++qa.active);
      const entry = {name:options.body.get('file').name, mode:options.body.get('mode')};
      qa.requests.push(entry);
      try { const response = await original.call(this, url, options); entry.status=response.status;
        entry.result=await response.clone().json(); return response; }
      finally { qa.active--; }
    };
  })()`);
  try {
    await setInputFile(wc, pdf);
    await wait(() => js(`Boolean(document.querySelector('input[name=mode][value=metadata_fast]'))`), 'fast mode is missing');
    assert.equal(await js(`document.querySelector('input[name=mode]:checked').value`), 'metadata_fast', 'a new PDF must default to the fast header mode');
    await js(`document.querySelector('input[name=mode][value=metadata_fast]').click(); true`);
    await wait(() => js(`document.querySelector('.run-button').textContent.includes('Bóc tách nhanh văn bản này')`), 'fast action must be explicit');
    const started = Date.now();
    await js(`document.querySelector('.run-button').click(); true`);
    await wait(() => js(`Boolean(window.__vietdocFastQA.requests[0]?.result) && !document.querySelector('.run-button').disabled`), 'fast extraction did not finish', 180_000);
    const raw = await js(`window.__vietdocFastQA.requests[0].result`);
    assert.equal(await js(`window.__vietdocFastQA.requests[0].status`), 200);
    checks.fast = {...validateFastScope(raw), elapsed_ms:Date.now()-started, timings_ms:raw.timings_ms};
    fs.writeFileSync(path.join(smokeDir, 'fast_result.raw.json'), JSON.stringify(raw, null, 2), 'utf8');
    assert.equal(await js(`document.querySelector('[role=tab][data-state=active]')?.textContent`), 'Thông tin văn bản');
    checks.fast.automatic_metadata = await values();
    assert.equal(checks.fast.automatic_metadata.docId, '');
    assert.equal(checks.fast.automatic_metadata.numberOfPage, String(raw.source_page_count));
    const authoredFixture = goldFile ? JSON.parse(fs.readFileSync(goldFile, 'utf8')) : null;
    if (authoredFixture?.require_unverified_subject === true) {
      const review = await js(`(() => {const root=document.querySelector('#metadata-subject').closest('.metadata-field');
        return {subject_blank:document.querySelector('#metadata-subject').value === '',
          review_badge:Boolean(root.querySelector('.field-status.review')),
          candidate_visible:Boolean(root.querySelector('.metadata-unverified-candidate')),
          candidate_text:root.querySelector('.metadata-unverified-candidate')?.textContent || '',
          can_confirm:Boolean(root.querySelector('.confirm-field'))};})()`);
      assert.equal(review.subject_blank, true, 'uncertain stamp text must not enter the automatic subject');
      assert.equal(review.review_badge, true);
      assert.equal(review.candidate_visible, true);
      assert.ok(review.candidate_text.includes('chưa xác minh'));
      assert.equal(review.can_confirm, false, 'an empty unverified subject cannot be auto-confirmed');
      for (const key of authoredFixture.known_fields.filter(key => key !== 'subject')) {
        assert.equal(checks.fast.automatic_metadata[key], authoredFixture.expected_metadata22[key], key+' changed');
      }
      assert.equal(checks.fast.automatic_metadata.typeName, '');
      await js(`document.querySelector('button[title="Xuất JSON 22 trường"]').click(); true`);
      await wait(() => js(`Boolean(document.querySelector('dialog[open]'))`), 'automatic unverified export must warn');
      await acceptDialog();
      const automaticFile = path.join(downloads, path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_metadata_fast_metadata.json');
      await wait(() => fs.existsSync(automaticFile), 'automatic metadata export missing');
      const automatic = JSON.parse(fs.readFileSync(automaticFile, 'utf8'));
      assert.deepEqual(Object.keys(automatic), KEYS);
      assert.equal(automatic.subject, '');
      fs.renameSync(automaticFile, automaticFile.replace(/_metadata\.json$/, '_automatic_metadata.json'));
      checks.fast.automatic_subject_review = {...review, automatic_json_blank:true, core_fields_match_authored_gold:true};
    }
    assert.ok(await js(`Boolean(document.querySelector('.result-origin.fast-origin') && document.querySelector('.partial-result-notice'))`), 'partial result must be visible');
    checks.fast.partial_ui_label = true;
    await screenshot('07_fast_metadata.png');
    // An optional owner-authored external QA fixture drives a manual form edit,
    // never recognition or production metadata extraction.
    const subject = authoredFixture ? authoredFixture.expected_metadata22.subject
      : '=1+1; kiểm thử metadata nhanh — chỉnh sửa riêng';
    assert.equal(typeof subject, 'string');
    assert.ok(subject.length > 0);
    checks.fast.manual_subject_from_authored_fixture = Boolean(goldFile);
    await editSubject(subject);
    await clickResultTab('Header (một phần)');
    assert.equal(await js(`document.querySelector('.text-output pre').textContent`), raw.text, 'fast metadata edit must not rewrite raw OCR');
    await screenshot('07b_fast_partial_text.png');
    await js(`document.querySelector('button[title="Tải TXT header (một phần)"]').click(); true`);
    await js(`document.querySelector('button[title="Tải JSON header (một phần)"]').click(); true`);
    const stem = path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_metadata_fast_partial';
    const txt = path.join(downloads, stem+'.txt'), json = path.join(downloads, stem+'.json');
    await wait(() => fs.existsSync(txt) && fs.existsSync(json), 'partial TXT/JSON downloads missing', 20_000);
    const exported = JSON.parse(fs.readFileSync(json, 'utf8'));
    assert.deepEqual(exported, raw);
    const text = fs.readFileSync(txt, 'utf8');
    assert.ok(text.includes(raw.text) && text !== raw.text && /một phần/i.test(text), 'fast TXT must label partial scope and retain raw text');
    checks.fast.partial_exports = true;
    await clickResultTab('Thông tin văn bản');
    assert.equal((await values()).subject, subject);
    await js(`document.querySelector('button[title="Xuất JSON 22 trường"]').click(); true`);
    await wait(() => js(`Boolean(document.querySelector('dialog[open]'))`), 'draft metadata export must confirm');
    await acceptDialog();
    const metadataFile = path.join(downloads, path.basename(pdf).replace(/\.[^.]+$/, '').replace(/[\\/:*?"<>|]/g, '_') + '_metadata_fast_metadata.json');
    await wait(() => fs.existsSync(metadataFile), 'fast metadata download missing');
    const metadata = JSON.parse(fs.readFileSync(metadataFile, 'utf8'));
    assert.deepEqual(Object.keys(metadata), KEYS);
    assert.equal(metadata.subject, subject);
    assert.equal(metadata.numberOfPage, String(raw.source_page_count));
    checks.fast.metadata_export_22 = true;
    checks.fast.raw_preserved_after_edit = true;

    await clearQueue();
    const files = [pdf, path.join(batchDir, 'decision.pdf'), path.join(batchDir, 'resolution.pdf')];
    await setInputFile(wc, files);
    await wait(() => js(`document.querySelectorAll('.input-queue li').length === 3`), 'three fast inputs were not selected');
    assert.deepEqual(await js(`Array.from(document.querySelectorAll('.input-queue li'), row=>row.dataset.mode)`), ['metadata_fast','metadata_fast','metadata_fast']);
    await js(`window.__vietdocFastQA.requests=[]; window.__vietdocFastQA.peak=0; document.querySelector('.batch-run-button').click(); true`);
    await wait(() => js(`document.querySelectorAll('.batch-table tbody tr').length === 3
      && document.querySelectorAll('.batch-status.review, .batch-status.extracted').length === 3`), 'fast batch did not complete', 180_000);
    const requests = await js(`window.__vietdocFastQA.requests`);
    assert.equal(requests.length, 3);
    const scope = requests.map((entry, index) => {
      assert.equal(entry.status, 200); assert.equal(entry.mode, 'metadata_fast');
      assert.equal(entry.name, path.basename(files[index]));
      return validateFastScope(entry.result);
    });
    assert.equal(await js(`window.__vietdocFastQA.peak`), 1);
    const expected = [];
    for (let index=0; index<3; index++) {
      await js(`document.querySelectorAll('.open-document')[${index}].click(); true`);
      await values();
      if (index === 0) await editSubject(subject);
      if (index === 1) await editSubject('=1+1; kiểm thử chuỗi literal của tài liệu thứ hai');
      const row = await values();
      assert.equal(row.numberOfPage, String(scope[index].source_page_count));
      expected.push(row);
      await clickResultTab('Header (một phần)');
      assert.equal(await js(`document.querySelector('.text-output pre').textContent`), requests[index].result.text);
      await clickResultTab('Danh sách văn bản');
    }
    await js(`document.querySelector('.open-document').click(); true`);
    assert.equal((await values()).subject, subject, 'fast document edits must survive switches');
    // The result panel's document switcher: "next" opens File 2 on the same tab, with its own values.
    await js(`document.querySelector('.document-nav button[aria-label="Tài liệu sau"]').click(); true`);
    await wait(() => js(`document.querySelector('.document-nav select')?.selectedOptions[0]?.textContent.startsWith('File 2/3')`), 'document switcher did not open File 2');
    assert.equal((await values()).arcDocCode, expected[1].arcDocCode, 'File 2 must show its own metadata');
    // Evidence only: a DevTools capture renders a fresh frame (capturePage can return a stale one here).
    try {
      wc.debugger.attach('1.3');
      const shot = await wc.debugger.sendCommand('Page.captureScreenshot', {format: 'png'});
      fs.writeFileSync(path.join(smokeDir, '08a_document_switcher.png'), Buffer.from(shot.data, 'base64'));
    } catch { await screenshot('08a_document_switcher.png'); } finally { try { wc.debugger.detach(); } catch { /* not attached */ } }
    checks.fast_document_switcher = {options:await js(`document.querySelectorAll('.document-nav option').length`), file2:true};
    fs.writeFileSync(path.join(smokeDir, 'fast_batch_expected.json'), JSON.stringify(expected, null, 2), 'utf8');
    fs.writeFileSync(path.join(smokeDir, 'fast_batch_responses.json'), JSON.stringify(requests, null, 2), 'utf8');
    await clickResultTab('Danh sách văn bản');
    await screenshot('08_fast_batch.png');
    const workbook = path.join(downloads, 'Danh_sach_van_ban.xlsx');
    if (fs.existsSync(workbook)) fs.renameSync(workbook, path.join(downloads, 'Danh_sach_van_ban_native.xlsx'));
    await js(`document.querySelector('.excel-export-button').click(); true`);
    await wait(() => js(`Boolean(document.querySelector('dialog[open]'))`), 'fast draft Excel export must confirm');
    await acceptDialog();
    await wait(() => fs.existsSync(workbook) && fs.statSync(workbook).size > 0, 'fast XLSX was not downloaded', 20_000);
    assert.equal(fs.readFileSync(workbook).subarray(0,2).toString(), 'PK');
    fs.renameSync(workbook, path.join(downloads, 'Danh_sach_van_ban_fast.xlsx'));
    checks.fast_batch = {count:3, max_concurrent:1, scopes:scope, edits_preserved:true, raw_text_preserved:true,
      metadata_fields:KEYS.length, xlsx_saved:true};
  } finally {
    await js(`window.fetch=window.__vietdocFastQA.original; delete window.__vietdocFastQA; true`);
  }
}

module.exports = {runFastSmoke, validateFastScope};
