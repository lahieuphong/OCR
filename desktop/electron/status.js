'use strict';
// Renders the backend and model state sent by the main process. Text only; no HTML from the status.
const $ = (id) => document.getElementById(id);

function row(list, label, value) {
  const dt = document.createElement('dt');
  dt.textContent = label;
  const dd = document.createElement('dd');
  dd.textContent = value;
  list.append(dt, dd);
}

function render(status) {
  if (!status) return;
  const message = $('message');
  message.textContent = status.message || '';
  message.className = 'message ' + (status.state || '');
  const facts = $('facts');
  facts.replaceChildren();
  const desk = status.desktop;
  if (desk) {
    row(facts, 'Backend', `đang chạy · 127.0.0.1:${desk.port} · PID ${desk.pid}`);
    row(facts, 'OCR (VietOCR B1024)', desk.ocr_allowed ? 'sẵn sàng' : 'bị chặn');
    row(facts, 'Text layer PDF', desk.native_text_allowed ? 'sẵn sàng' : 'không');
    row(facts, 'Recognizer', `${desk.recognizer.ok ? 'khớp SHA-256' : 'không dùng được'} · ${desk.recognizer.dir}`);
    row(facts, 'Detector', `${desk.detector.ok ? 'khớp SHA-256' : 'không dùng được'} · ${desk.detector.dir}`);
    row(facts, 'Tải model', desk.model_downloads === 'disabled' ? 'tắt (offline)' : desk.model_downloads);
    row(facts, 'Giới hạn', `${Math.round(desk.limits.max_upload_bytes / 1048576)} MB · ${desk.limits.max_pdf_pages} trang PDF · ${desk.limits.max_image_pixels / 1e6} MP`);
    row(facts, 'Phiên bản', Object.entries(desk.versions).map(([k, v]) => `${k} ${v ?? '—'}`).join(' · '));
  }
  const problems = $('problems');
  problems.replaceChildren();
  for (const p of desk ? [...desk.recognizer.problems, ...desk.detector.problems] : []) {
    const li = document.createElement('li');
    li.textContent = p;
    problems.append(li);
  }
  $('log').textContent = status.log ? `Log: ${status.log}` : '';
}

$('retry').addEventListener('click', () => window.vietdoc.retry());
$('logs').addEventListener('click', () => window.vietdoc.openLogs());
$('quit').addEventListener('click', () => window.vietdoc.quit());
window.vietdoc.onStatus(render);
window.vietdoc.getStatus().then(render);
