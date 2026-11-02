'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { checkReport } = require('../scripts/check-smoke-report');

function passingNoModels() {
  return {
    checks: {
      ui: { title: 'VietDoc OCR', pill_class: 'server-pill not-ready' },
      renderer_has_node: false, external_fetch_blocked: true, external_navigation_blocked: true,
      request_without_token_status: 403, request_localhost_host_status: 403,
      ui_file_selected: 'synthetic.pdf', ui_preview: { rendered: true },
      ui_native_text: { ok: true },
      export: { both_saved: true, txt_equals_json_text: true, json_method: 'native_text' },
      ocr_allowed: false, ui_ocr_run_button_disabled: true,
      api_vietocr_ocr: { status: 503, detail: 'Bản desktop chặn OCR: Missing/invalid ONNX files.' },
      images: { 'synthetic_ui.png': { preview_px: [800, 500], run_disabled: true }, 'synthetic_ui.jpg': { preview_px: [800, 500], run_disabled: true } },
      ui_oversize: 'Giới hạn kích thước tệp là 15 MB.', api_oversize: { status: 400 },
      backend_status: { ocr_allowed: false, model_downloads: 'disabled' },
      crash: { detected: true, server_alive_after: false, port_closed_after: true },
      recovery: { restarted: true, port_changed: true, ui: { title: 'VietDoc OCR' } },
      shutdown: { graceful: true, exit: { code: 0 }, launcher_alive_after: false, server_alive_after: false, port_closed_after: true },
    },
  };
}

test('a complete model-free run passes', () => {
  const result = checkReport(passingNoModels(), { expect: 'no-models', withPdf: true });
  assert.deepEqual(result.failures, []);
  assert.equal(result.ok, true);
});

test('OCR that is not refused without models fails', () => {
  const r = passingNoModels();
  r.checks.api_vietocr_ocr = { status: 200, detail: null };
  r.checks.ui_ocr_run_button_disabled = false;
  const result = checkReport(r, { expect: 'no-models', withPdf: true });
  assert.equal(result.ok, false);
  assert.ok(result.failures.some((f) => f.includes('503')));
  assert.ok(result.failures.some((f) => f.includes('OCR button is enabled')));
});

test('security, crash and shutdown regressions fail', () => {
  for (const [key, value] of [['request_without_token_status', 200], ['renderer_has_node', true], ['external_fetch_blocked', false],
    ['crash', { detected: true, server_alive_after: true, port_closed_after: true }],
    ['shutdown', { graceful: true, exit: { code: 0 }, launcher_alive_after: false, server_alive_after: false, port_closed_after: false }]]) {
    const r = passingNoModels();
    r.checks[key] = value;
    assert.equal(checkReport(r, { expect: 'no-models', withPdf: true }).ok, false, key);
  }
  const r = passingNoModels();
  r.error = 'watchdog: smoke test did not finish in 300 s';
  assert.equal(checkReport(r, { expect: 'no-models' }).ok, false);
});

test('a missing image check or a downloads flag other than disabled fails', () => {
  const r = passingNoModels();
  delete r.checks.images['synthetic_ui.jpg'];
  assert.equal(checkReport(r, { expect: 'no-models' }).ok, false);
  const s = passingNoModels();
  s.checks.backend_status.model_downloads = 'enabled';
  assert.equal(checkReport(s, { expect: 'no-models' }).ok, false);
});

test('screenshots and preview pixels are warnings, never failures', () => {
  const r = passingNoModels();
  r.capture_errors = [{ name: '04_ui_after_restart.png', error: 'UnknownVizError' }];
  r.checks.ui_preview = { rendered: false };
  const result = checkReport(r, { expect: 'no-models', withPdf: true });
  assert.equal(result.ok, true);
  assert.equal(result.warnings.length, 2);
});

test('a status-window capture error is a warning; the same error outside a screenshot still fails the run', () => {
  const r = passingNoModels();
  r.capture_errors = [{ name: '05_status_window.png', error: 'UnknownVizError: Failed to capture' }];
  const warned = checkReport(r, { expect: 'no-models', withPdf: true });
  assert.equal(warned.ok, true);
  assert.ok(warned.warnings.some((w) => w.includes('05_status_window.png')));
  // A run aborted by the error (no crash/recovery/shutdown checks recorded) is never rescued by the warning.
  const aborted = passingNoModels();
  aborted.capture_errors = r.capture_errors;
  aborted.error = 'Error: UnknownVizError: Failed to capture';
  delete aborted.checks.crash;
  delete aborted.checks.recovery;
  const failed = checkReport(aborted, { expect: 'no-models', withPdf: true });
  assert.equal(failed.ok, false);
  assert.ok(failed.failures.some((f) => f.includes('smoke run error')));
  assert.ok(failed.failures.some((f) => f.includes('crash handling')));
});

test('the OCR mode requires a real OCR run and export through the UI', () => {
  const r = passingNoModels();
  Object.assign(r.checks, {
    ui: { title: 'VietDoc OCR', pill_class: 'server-pill connected' }, ocr_allowed: true, ui_ocr_run_button_disabled: false,
    backend_status: { ocr_allowed: true, model_downloads: 'disabled' },
    ui_vietocr_ocr: { ok: true },
    ocr_export: { both_saved: true, txt_equals_json_text: true, json_method: 'vietocr_ocr', decoder_limit_hits: 0, model: 'phase4_exp_b_width1024' },
    ocr_copy: { copied: true, chars: 1200, equals_full_text: false, equals_page_text: true, ui_error: null },
  });
  for (const name of Object.keys(r.checks.images)) r.checks.images[name].run_disabled = false;
  assert.deepEqual(checkReport(r, { expect: 'ocr', withPdf: true }).failures, []);
  r.checks.ocr_export.decoder_limit_hits = 2;
  assert.equal(checkReport(r, { expect: 'ocr', withPdf: true }).ok, false);
  assert.equal(checkReport(passingNoModels(), { expect: 'ocr', withPdf: true }).ok, false);
});

test('the OCR mode runs the copy button: a UI copy error fails, an unconfirmed read-back only warns', () => {
  const r = passingNoModels();
  Object.assign(r.checks, {
    ui: { title: 'VietDoc OCR', pill_class: 'server-pill connected' }, ocr_allowed: true, ui_ocr_run_button_disabled: false,
    backend_status: { ocr_allowed: true, model_downloads: 'disabled' }, ui_vietocr_ocr: { ok: true },
    ocr_export: { both_saved: true, txt_equals_json_text: true, json_method: 'vietocr_ocr', decoder_limit_hits: 0, model: 'phase4_exp_b_width1024' },
  });
  for (const name of Object.keys(r.checks.images)) r.checks.images[name].run_disabled = false;
  const result = (copy) => checkReport({ ...r, checks: { ...r.checks, ocr_copy: copy } }, { expect: 'ocr', withPdf: true });
  const fails = (copy) => result(copy).failures.some((f) => f.includes('copy button'));
  const warns = (copy) => result(copy).warnings.some((w) => w.includes('copy button'));
  assert.equal(fails(undefined), true, 'the check must have run');
  assert.equal(fails({ copied: true, equals_full_text: true, ui_error: 'Không thể sao chép bằng Clipboard.' }), true);
  assert.equal(fails({ copied: false, chars: 0, ui_error: null }), false);
  assert.equal(warns({ copied: false, chars: 0, ui_error: null }), true);
  assert.equal(warns({ copied: true, equals_full_text: false, equals_page_text: false, ui_error: null }), true);
  assert.equal(fails({ copied: true, equals_full_text: true, ui_error: null }), false);
  assert.equal(warns({ copied: true, equals_full_text: true, ui_error: null }), false);
  assert.equal(result({ copied: true, equals_page_text: true, ui_error: null }).ok, true);
  // Without models there is no OCR result to copy: the no-models mode does not ask for it.
  assert.equal(checkReport(passingNoModels(), { expect: 'no-models', withPdf: true }).ok, true);
});

test('fast smoke requires partial downloads, actual batch, source scope and preserved raw/edit evidence', () => {
  const r = passingNoModels();
  const scope = {source_page_count:6, partial_result:true, inspected_pages:[1], processed_pages:[1]};
  r.checks.fast = {...scope, partial_ui_label:true, partial_exports:true, metadata_export_22:true, raw_preserved_after_edit:true};
  r.checks.fast_batch = {count:3, max_concurrent:1, metadata_fields:22, edits_preserved:true, raw_text_preserved:true,
    xlsx_saved:true, scopes:[scope,scope,scope]};
  assert.equal(checkReport(r, {withFast:true}).ok, true);
  for (const change of [{partial_result:false}, {processed_pages:[1,4,5,6]}, {partial_exports:false}, {metadata_export_22:false}]) {
    assert.equal(checkReport({...r, checks:{...r.checks,fast:{...r.checks.fast,...change}}}, {withFast:true}).ok, false);
  }
  for (const change of [{max_concurrent:2}, {edits_preserved:false}, {xlsx_saved:false}, {scopes:[{...scope,inspected_pages:[1,4]}]}]) {
    assert.equal(checkReport({...r, checks:{...r.checks,fast_batch:{...r.checks.fast_batch,...change}}}, {withFast:true}).ok, false);
  }
  assert.equal(checkReport(passingNoModels(), {withFast:true}).ok, false);
});

test('stamp review gate rejects automatic contaminated or confirmed exports even if other smoke checks pass', () => {
  const r = passingNoModels();
  const review = {subject_blank:true, review_badge:true, candidate_visible:true, can_confirm:false,
    automatic_json_blank:true, core_fields_match_authored_gold:true};
  r.checks.fast = {automatic_subject_review:review};
  assert.equal(checkReport(r, {withSubjectReview:true}).ok, true);
  for (const change of [{subject_blank:false},{review_badge:false},{candidate_visible:false},{can_confirm:true},
    {automatic_json_blank:false},{core_fields_match_authored_gold:false}]) {
    const altered = {...r, checks:{...r.checks,fast:{automatic_subject_review:{...review,...change}}}};
    assert.equal(checkReport(altered, {withSubjectReview:true}).ok, false, JSON.stringify(change));
  }
  assert.equal(checkReport(passingNoModels(), {withSubjectReview:true}).ok, false);
});
