'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { checkReport } = require('../scripts/check-smoke-report');

function passingNoModels() {
  return {
    checks: {
      ui: { title: 'VietDoc OCR', pill_class: 'server-pill not-ready' },
      startup: { visible_windows: 1, main_window_visible: true, status_window_created: false, state: 'limited' },
      renderer_has_node: false, external_fetch_blocked: true, external_navigation_blocked: true,
      request_without_token_status: 403, request_localhost_host_status: 403,
      ui_file_selected: 'synthetic.pdf', ui_preview: { rendered: true },
      app_menu: { platform: 'win32', native_menu_bar: false, title_bar_overlay: true, version_shown: true,
        items: ['Trạng thái hệ thống', 'Mở thư mục nhật ký', 'Thoát VietDoc OCR'], zoom_after_plus: 110, zoom_after_reset: 100,
        zoom_shortcut: 110, escape_closes: true },
      ui_fast_only: { mode_inputs: 0, bulk_mode: false, queued_mode: 'metadata_fast', run_fast: true },
      ui_fast_pdf: { ok: false, error: 'Không thể hoàn tất thao tácBản desktop chặn OCR: Missing/invalid ONNX files.' },
      ui_fast_flow: { file: 'officialLetter.pdf', ok: true },
      metadata: { fields: 22, export_exact_schema: true, manual_edits_and_reset: true },
      export: { both_saved: true, txt_labels_partial_and_keeps_text: true, json_method: 'metadata_fast', partial_result: true },
      ocr_allowed: false,
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
  const result = checkReport(r, { expect: 'no-models', withPdf: true });
  assert.equal(result.ok, false);
  assert.ok(result.failures.some((f) => f.includes('503')));
});

test('without models the smoke PDF is read from its text layer or refused, and the fixture flow must pass', () => {
  const read = passingNoModels();
  read.checks.ui_fast_pdf = { ok: true };
  delete read.checks.ui_fast_flow;
  assert.deepEqual(checkReport(read, { expect: 'no-models', withPdf: true }).failures, []);
  const crashed = passingNoModels();
  crashed.checks.ui_fast_pdf = { ok: false, error: 'Không thể hoàn tất thao tácInternal Server Error' };
  assert.ok(checkReport(crashed, { expect: 'no-models', withPdf: true }).failures.some((f) => f.startsWith('fast extraction without models')));
  const noFlow = passingNoModels();
  noFlow.checks.ui_fast_flow = { file: 'officialLetter.pdf', ok: false, error: 'x' };
  assert.ok(checkReport(noFlow, { expect: 'no-models', withPdf: true }).failures.some((f) => f.includes('text-layer fixture')));
});

test('a native menu bar, a system title bar on Windows or a broken app menu fails', () => {
  for (const change of [{ native_menu_bar: true }, { title_bar_overlay: false }, { items: ['Thoát VietDoc OCR'] },
    { zoom_after_plus: null }, { zoom_shortcut: null }, { escape_closes: false }, { version_shown: false }]) {
    const r = passingNoModels();
    r.checks.app_menu = { ...r.checks.app_menu, ...change };
    assert.ok(checkReport(r, { expect: 'no-models', withPdf: true }).failures.some((f) => f.startsWith('app menu')), JSON.stringify(change));
  }
  const r = passingNoModels();
  delete r.checks.app_menu;
  assert.equal(checkReport(r, { expect: 'no-models' }).ok, false);
  // macOS keeps its system menu bar and frame; Linux keeps its frame.
  for (const platform of [['darwin', { native_menu_bar: true, title_bar_overlay: false }], ['linux', { title_bar_overlay: false }]]) {
    const s = passingNoModels();
    s.checks.app_menu = { ...s.checks.app_menu, platform: platform[0], ...platform[1] };
    assert.deepEqual(checkReport(s, { expect: 'no-models', withPdf: true }).failures, [], platform[0]);
  }
});

test('a method choice in the UI, a missing form check or a full-text export fails', () => {
  for (const [key, value] of [['ui_fast_only', { mode_inputs: 4, bulk_mode: true, queued_mode: 'metadata_fast', run_fast: true }],
    ['ui_fast_only', { mode_inputs: 0, bulk_mode: false, queued_mode: 'native_text', run_fast: false }],
    ['metadata', { fields: 22, export_exact_schema: true }],
    ['export', { both_saved: true, txt_labels_partial_and_keeps_text: true, json_method: 'native_text', partial_result: true }],
    ['export', { both_saved: true, txt_labels_partial_and_keeps_text: false, json_method: 'metadata_fast', partial_result: true }]]) {
    const r = passingNoModels();
    r.checks[key] = value;
    assert.equal(checkReport(r, { expect: 'no-models', withPdf: true }).ok, false, `${key}: ${JSON.stringify(value)}`);
  }
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

test('an app that does not open as exactly one main window fails', () => {
  for (const startup of [undefined,
    { visible_windows: 2, main_window_visible: true, status_window_created: true, state: 'limited' },
    { visible_windows: 1, main_window_visible: true, status_window_created: true, state: 'limited' },
    { visible_windows: 1, main_window_visible: false, status_window_created: true, state: 'limited' }]) {
    const r = passingNoModels();
    r.checks.startup = startup;
    const result = checkReport(r, { expect: 'no-models', withPdf: true });
    assert.equal(result.ok, false, JSON.stringify(startup));
    assert.ok(result.failures.some((f) => f.startsWith('startup:')));
  }
});

test('a batch run without a working folder import fails', () => {
  for (const folder of [undefined, { ok: false, added: 0, supported: 10 }]) {
    const r = passingNoModels();
    r.checks.batch = { count: 3, max_concurrent: 1 };
    r.checks.folder_import = folder;
    assert.ok(checkReport(r, { expect: 'no-models', withPdf: true }).failures.some((f) => f.startsWith('folder import:')));
  }
  for (const folder of [{ ok: true, added: 10, supported: 10 }, { not_run: 'no --smoke-batch-dir' }]) {
    const r = passingNoModels();
    r.checks.batch = { count: 3, max_concurrent: 1 };
    r.checks.folder_import = folder;
    assert.deepEqual(checkReport(r, { expect: 'no-models', withPdf: true }).failures, [], JSON.stringify(folder));
  }
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

test('the OCR mode requires the fast extraction of the smoke PDF to succeed through the UI', () => {
  const r = passingNoModels();
  Object.assign(r.checks, {
    ui: { title: 'VietDoc OCR', pill_class: 'server-pill connected' }, ocr_allowed: true,
    backend_status: { ocr_allowed: true, model_downloads: 'disabled' }, ui_fast_pdf: { ok: true, elapsed_ms: 9000 },
  });
  delete r.checks.ui_fast_flow; delete r.checks.api_vietocr_ocr;
  for (const name of Object.keys(r.checks.images)) r.checks.images[name].run_disabled = false;
  assert.deepEqual(checkReport(r, { expect: 'ocr', withPdf: true }).failures, []);
  // With models a refusal is a failure, even when a fixture flow passed.
  r.checks.ui_fast_pdf = { ok: false, error: 'Bản desktop chặn OCR: x' };
  r.checks.ui_fast_flow = { ok: true };
  assert.ok(checkReport(r, { expect: 'ocr', withPdf: true }).failures.some((f) => f.startsWith('fast extraction through the UI failed')));
  assert.equal(checkReport(passingNoModels(), { expect: 'ocr', withPdf: true }).ok, false);
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
