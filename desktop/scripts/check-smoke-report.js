'use strict';
// Decides whether an Electron smoke run passed. The smoke test (electron/main.js --smoke-test) only
// records what it saw; this checker turns that record into PASS/FAIL for CI and for local runs.
//
//   node scripts/check-smoke-report.js <smoke_report.json> --expect=no-models|ocr [--with-pdf]
//
// no-models: the frozen recognizer/detector are absent, so OCR must be refused (CI, no downloads).
// ocr:       the models verified, so OCR must run through the UI (local DEV run; compare the export
//            with the A0 baseline separately). Screenshots and the PDF preview pixels are evidence
//            only: their failures are reported as warnings, never as a pass or a fail.
const fs = require('node:fs');

function checkReport(report, { expect = 'no-models', withPdf = false } = {}) {
  const c = report.checks || {};
  const failures = [];
  const warnings = [];
  const need = (ok, what) => { if (!ok) failures.push(what); };

  need(!report.error, `smoke run error: ${report.error}`);
  need(!(report.main_errors && report.main_errors.length), `main-process errors: ${JSON.stringify(report.main_errors)}`);
  need(c.ui && c.ui.title, 'the UI did not render');
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
    need(c.ui_native_text && c.ui_native_text.ok, `text-layer extraction failed: ${JSON.stringify(c.ui_native_text)}`);
    need(c.export && c.export.both_saved && c.export.txt_equals_json_text && c.export.json_method === 'native_text',
      `TXT/JSON export of the text layer: ${JSON.stringify(c.export)}`);
    need(c.ocr_allowed === ocr, `UI-side ocr_allowed should be ${ocr}`);
    if (ocr) {
      need(c.ui_ocr_run_button_disabled === false, 'the OCR button is disabled although OCR is allowed');
      need(c.ui_vietocr_ocr && c.ui_vietocr_ocr.ok, `OCR through the UI failed: ${JSON.stringify(c.ui_vietocr_ocr)}`);
      const e = c.ocr_export || {};
      need(e.both_saved && e.txt_equals_json_text && e.json_method === 'vietocr_ocr' && e.decoder_limit_hits === 0
        && e.model === 'phase4_exp_b_width1024', `OCR export: ${JSON.stringify(e)}`);
      // Copy button: an error shown by the UI fails the run. What the main process reads back from the clipboard
      // is evidence only: on Windows that read-back proved unreliable (empty or stale while another process saw the
      // copied text), so a mismatch is a warning; verify the clipboard from outside (clipboard_watch) instead.
      const copy = c.ocr_copy || {};
      need(c.ocr_copy && !copy.ui_error, `copy button: ${JSON.stringify(copy)} (the UI reported a copy error or never ran the check)`);
      if (!(copy.copied && (copy.equals_full_text || copy.equals_page_text))) {
        warnings.push(`copy button: clipboard read-back not confirmed in-process (evidence only): ${JSON.stringify(copy)}`);
      }
    } else {
      need(c.ui_ocr_run_button_disabled === true, 'the OCR button is enabled although models are missing');
      need(c.api_vietocr_ocr && c.api_vietocr_ocr.status === 503 && /chặn OCR/.test(c.api_vietocr_ocr.detail || ''),
        `OCR request without models: ${JSON.stringify(c.api_vietocr_ocr)} (503 "chặn OCR" expected)`);
    }
    if (!(c.ui_preview && c.ui_preview.rendered)) warnings.push('PDF preview pixels not confirmed (evidence only)');
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
    console.error('usage: node scripts/check-smoke-report.js <smoke_report.json> --expect=no-models|ocr [--with-pdf]');
    return 2;
  }
  let report;
  try {
    report = JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch (error) {
    console.error(`SMOKE FAILED: no readable report at ${file} (${error.message})`);
    return 1;
  }
  const result = checkReport(report, { expect, withPdf: argv.includes('--with-pdf') });
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
