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
  // The text only: the state's icon (status.html) is chosen by the class.
  $('message-text').textContent = status.message || '';
  $('message').className = 'message ' + (status.state || '');
  const facts = $('facts');
  facts.replaceChildren();
  const desk = status.desktop;
  const summary = $('summary');
  summary.replaceChildren();
  // The app has one method, the fast header extraction: a PDF's text layer needs no model, a scan or a photo needs OCR.
  row(summary, 'Máy chủ xử lý', desk ? 'Đang chạy' : status.state === 'error' ? 'Chưa sẵn sàng' : 'Đang khởi động…');
  row(summary, 'PDF có lớp chữ', desk?.native_text_allowed ? 'Sẵn sàng' : 'Chưa sẵn sàng');
  row(summary, 'Bản scan và ảnh (OCR)', desk ? (desk.ocr_allowed ? 'Sẵn sàng' : 'Thiếu model OCR hoặc model chưa hợp lệ') : 'Chưa sẵn sàng');
  // After an error the retry is the next step; otherwise restarting the server is a rare, secondary action.
  const retry = $('retry');
  retry.querySelector('span').textContent = status.state === 'error' ? 'Thử lại' : 'Khởi động lại máy chủ';
  retry.className = status.state === 'error' ? 'primary' : '';
  if (desk) {
    row(facts, 'Backend', `đang chạy · 127.0.0.1:${desk.port} · PID ${desk.pid}`);
    row(facts, 'OCR (VietOCR B1024)', desk.ocr_allowed ? 'sẵn sàng' : 'bị chặn');
    row(facts, 'Text layer PDF', desk.native_text_allowed ? 'sẵn sàng' : 'không');
    row(facts, 'Recognizer', `${desk.recognizer.ok ? 'khớp SHA-256' : 'không dùng được'} · ${desk.recognizer.dir}`);
    row(facts, 'Detector', `${desk.detector.ok ? 'khớp SHA-256' : 'không dùng được'} · ${desk.detector.dir}`);
    row(facts, 'Tải model', desk.model_downloads === 'disabled' ? 'tắt (offline)' : desk.model_downloads);
    row(facts, 'Giới hạn', `${Math.round(desk.limits.max_upload_bytes / 1048576)} MB mỗi tệp · PDF: đọc trang 1 · ảnh ${desk.limits.max_image_pixels / 1e6} MP`);
    row(facts, 'Phiên bản', Object.entries(desk.versions).map(([k, v]) => `${k} ${v ?? '—'}`).join(' · '));
  }
  const problems = $('problems');
  problems.replaceChildren();
  for (const p of desk ? [...desk.recognizer.problems, ...desk.detector.problems] : []) {
    const li = document.createElement('li');
    li.textContent = p;
    problems.append(li);
  }
  $('log').textContent = status.log ? `Nhật ký: ${status.log}` : '';
}

$('retry').addEventListener('click', () => window.vietdoc.retry());
$('logs').addEventListener('click', () => window.vietdoc.openLogs());
$('quit').addEventListener('click', () => window.vietdoc.quit());
window.vietdoc.onStatus(render);
window.vietdoc.getStatus().then(render);
