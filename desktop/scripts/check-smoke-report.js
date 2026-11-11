'use strict';
// Decides whether an Electron smoke run passed. The smoke test (electron/main.js --smoke-test) only
// records what it saw; this checker turns that record into PASS/FAIL for CI and for local runs.
//
//   node scripts/check-smoke-report.js <smoke_report.json> --expect=no-models|ocr [--with-pdf] [--with-fast] [--with-subject-review]
//
// no-models: the frozen recognizer/detector are absent, so OCR must be refused (CI, no downloads).
// ocr:       the models verified, so the fast header extraction must run through the UI (local DEV run).
//            Screenshots and the PDF preview pixels are evidence only: their failures are reported as
//            warnings, never as a pass or a fail.
const fs = require('node:fs');

function checkReport(report, { expect = 'no-models', withPdf = false, withFast = false, withSubjectReview = false } = {}) {
  const c = report.checks || {};
  const failures = [];
  const warnings = [];
  const need = (ok, what) => { if (!ok) failures.push(what); };

  need(!report.error, `smoke run error: ${report.error}`);
  need(!(report.main_errors && report.main_errors.length), `main-process errors: ${JSON.stringify(report.main_errors)}`);
  need(c.ui && c.ui.title, 'the UI did not render');
  // With the batch fixtures (--smoke-batch-dir) the folder picker must queue the folder's documents (fast
  // mode) and report the rest. Without them the smoke records that it did not run the folder step.
  if (c.batch) need(c.folder_import && (c.folder_import.ok === true || c.folder_import.not_run === 'no --smoke-batch-dir'),
    `folder import: ${JSON.stringify(c.folder_import)}`);
  // The app opens as exactly one window, also without models: no status window next to the main window.
  need(c.startup && c.startup.visible_windows === 1 && c.startup.main_window_visible === true
    && c.startup.status_window_created === false,
    `startup: the app did not open as one main window: ${JSON.stringify(c.startup)}`);
  need(c.renderer_has_node === false, 'the renderer can reach Node (require/process)');
  need(c.external_fetch_blocked === true, 'a fetch to the Internet was not blocked');
  need(c.external_navigation_blocked === true, 'navigation/new window to the Internet was not blocked');
  need(c.request_without_token_status === 403, `request without token: ${c.request_without_token_status} (403 expected)`);
  const localhost = c.request_localhost_host_status;
  need(localhost === 403 || (typeof localhost === 'string' && localhost.startsWith('error:')),
    `request with Host localhost: ${localhost} (403 or no connection expected)`);
  need(c.backend_status && c.backend_status.model_downloads === 'disabled', 'model downloads are not reported as disabled');

  const ocr = expect === 'ocr';
  need(c.backend_status && c.backend_status.ocr_allowed === ocr, `backend ocr_allowed should be ${ocr}`);
  need(c.ui && (ocr ? /\bconnected\b/ : /\bnot-ready\b/).test(c.ui.pill_class || ''),
    `health pill should be ${ocr ? 'connected' : 'not-ready'} (got ${c.ui && c.ui.pill_class})`);

  if (withPdf) {
    need(Boolean(c.ui_file_selected), 'the PDF was not selected through the file input');
    const only = c.ui_fast_only || {};
    need(only.mode_inputs === 0 && only.bulk_mode === false && only.queued_mode === 'metadata_fast' && only.run_fast === true,
      `the app must offer the fast header mode only, with no method choice: ${JSON.stringify(c.ui_fast_only)}`);
    need(c.ocr_allowed === ocr, `UI-side ocr_allowed should be ${ocr}`);
    const first = c.ui_fast_pdf || {};
    if (ocr) {
      need(first.ok === true, `fast extraction through the UI failed: ${JSON.stringify(c.ui_fast_pdf)}`);
    } else {
      // Without models the smoke PDF is read from a genuine header in its text layer, or refused (never OCRed,
      // nothing downloaded); the form and export checks then ran on the text-layer fixture.
      // The packaged backend refuses with "Bản desktop chặn OCR: …", a source checkout with the missing-ONNX message.
      need(first.ok === true || /chặn OCR|Missing\/invalid ONNX/.test(first.error || ''),
        `fast extraction without models: ${JSON.stringify(c.ui_fast_pdf)} (a result or a missing-model refusal expected)`);
      need(first.ok === true || (c.ui_fast_flow && c.ui_fast_flow.ok === true),
        `fast extraction of the text-layer fixture: ${JSON.stringify(c.ui_fast_flow)}`);
      need(c.api_vietocr_ocr && c.api_vietocr_ocr.status === 503 && /chặn OCR/.test(c.api_vietocr_ocr.detail || ''),
        `OCR request without models: ${JSON.stringify(c.api_vietocr_ocr)} (503 "chặn OCR" expected)`);
    }
    const m = c.metadata || {};
    need(m.fields === 22 && m.export_exact_schema === true && m.manual_edits_and_reset === true,
      `22-field form and JSON export: ${JSON.stringify(c.metadata)}`);
    const e = c.export || {};
    need(e.both_saved && e.txt_labels_partial_and_keeps_text === true && e.json_method === 'metadata_fast' && e.partial_result === true,
      `partial TXT/JSON export of the header: ${JSON.stringify(c.export)}`);
    if (!(c.ui_preview && c.ui_preview.rendered)) warnings.push('PDF preview pixels not confirmed (evidence only)');
    // 0: the test document fits without scrolling. null: the style did not reach the PDF viewer.
    if (c.ui_preview && c.ui_preview.scrollbar_px === null) warnings.push('PDF preview has the default scrollbar (evidence only)');
  }

  if (withFast) {
    const fast = c.fast || {}, batch = c.fast_batch || {};
    need(fast.partial_result === true && Number.isInteger(fast.source_page_count) && fast.source_page_count >= 1
      && fast.source_page_count <= 6 && JSON.stringify(fast.inspected_pages) === '[1]'
      && Array.isArray(fast.processed_pages) && fast.processed_pages.length <= 1
      && fast.processed_pages.every(page => page === 1), 'fast extraction scope/counts or appendix exclusion failed');
    need(fast.partial_ui_label && fast.partial_exports && fast.metadata_export_22 && fast.raw_preserved_after_edit,
      'fast UI, partial TXT/JSON, metadata22 or raw preservation checks did not pass');
    need(batch.count === 3 && batch.max_concurrent === 1 && batch.metadata_fields === 22
      && batch.edits_preserved && batch.raw_text_preserved && batch.xlsx_saved, 'fast batch/Excel checks did not pass');
    need(Array.isArray(batch.scopes) && batch.scopes.length === 3 && batch.scopes.every(scope => scope.partial_result === true
      && JSON.stringify(scope.inspected_pages) === '[1]' && Array.isArray(scope.processed_pages)
      && scope.processed_pages.length <= 1 && scope.processed_pages.every(page => page === 1)), 'fast batch processed later pages or lost scope');
  }
  if (withSubjectReview) {
    const review = c.fast?.automatic_subject_review || {};
    need(review.subject_blank === true && review.review_badge === true && review.candidate_visible === true
      && review.can_confirm === false && review.automatic_json_blank === true && review.core_fields_match_authored_gold === true,
      'stamp-contaminated subject was not safely blank/reviewed before manual editing/export');
  }
  for (const name of ['synthetic_ui.png', 'synthetic_ui.jpg']) {
    const image = c.images && c.images[name];
    need(image && Array.isArray(image.preview_px) && image.preview_px[0] > 0, `${name} preview did not render`);
    if (image) need(image.run_disabled === !ocr, `${name}: OCR button disabled=${image.run_disabled}, expected ${!ocr}`);
  }
  need(typeof c.ui_oversize === 'string' && c.ui_oversize.includes('15 MB'), `UI 15 MB limit: ${c.ui_oversize}`);
  need(c.api_oversize && c.api_oversize.status === 400, `API 15 MB limit: ${JSON.stringify(c.api_oversize)}`);

  const crash = c.crash || {};
  need(crash.detected && crash.server_alive_after === false && crash.port_closed_after === true,
    `backend crash handling: ${JSON.stringify(crash)}`);
  const recovery = c.recovery || {};
  need(recovery.restarted && recovery.port_changed && recovery.ui, `restart after crash: ${JSON.stringify(recovery)}`);
  const stop = c.shutdown || {};
  need(stop.graceful && stop.exit && stop.exit.code === 0 && stop.launcher_alive_after === false
    && stop.server_alive_after === false && stop.port_closed_after === true, `shutdown: ${JSON.stringify(stop)}`);

  if (report.capture_errors && report.capture_errors.length) warnings.push(`screenshots not captured: ${JSON.stringify(report.capture_errors)}`);
  if (c.status_window_capture) warnings.push(`status window capture: ${c.status_window_capture}`);
  return { ok: failures.length === 0, failures, warnings };
}

function main(argv) {
  const file = argv.find((a) => !a.startsWith('--'));
  const expect = (argv.find((a) => a.startsWith('--expect=')) || '--expect=no-models').slice('--expect='.length);
  if (!file || !['no-models', 'ocr'].includes(expect)) {
    console.error('usage: node scripts/check-smoke-report.js <smoke_report.json> --expect=no-models|ocr [--with-pdf] [--with-fast] [--with-subject-review]');
    return 2;
  }
  let report;
  try {
    report = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    console.error(`SMOKE FAILED: no readable report at ${file} (${error.message})`);
    return 1;
  }
  const result = checkReport(report, { expect, withPdf: argv.includes('--with-pdf'), withFast: argv.includes('--with-fast'), withSubjectReview: argv.includes('--with-subject-review') });
  for (const w of result.warnings) console.log(`warning: ${w}`);
  if (!result.ok) {
    console.error(`SMOKE FAILED (${expect}):\n  ${result.failures.join('\n  ')}`);
    return 1;
  }
  console.log(`SMOKE PASSED (${expect}${argv.includes('--with-pdf') ? ', with PDF' : ''})`);
  return 0;
}

if (require.main === module) process.exit(main(process.argv.slice(2)));
module.exports = { checkReport };
