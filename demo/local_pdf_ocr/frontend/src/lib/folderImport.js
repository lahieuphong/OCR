// Adding many documents at once: files, a picked folder (with subfolders) or a dropped folder.
// Files are only referenced here; nothing is read before the user starts processing.
export const MAX_UPLOAD_BYTES = 15 * 1024 * 1024;
export const MAX_BATCH_DOCUMENTS = 1000;
export const MAX_LISTED_SKIPS = 5;
const SUPPORTED = /\.(?:pdf|png|jpe?g)$/iu;
// Hidden files and the files Windows/macOS/Office leave in folders are never documents.
const SYSTEM_FILE = /^(?:\.|~\$)|^(?:thumbs\.db|desktop\.ini|ehthumbs\.db)$/iu;
const collator = new Intl.Collator("vi", {numeric: true, sensitivity: "base"});

export const SKIP_REASONS = {
  unsupported: "Vui lòng chọn tệp PDF, PNG hoặc JPG.",
  tooLarge: "Giới hạn kích thước tệp là 15 MB.",
  empty: "Tệp rỗng.",
  duplicate: "Đã có trong danh sách.",
  limit: `Danh sách tối đa ${MAX_BATCH_DOCUMENTS} tài liệu.`,
};

// Path inside the chosen folder ("Hồ sơ/2026/a.pdf"), else the file name.
export function documentPath(file) {
  return file.vietdocPath || file.webkitRelativePath || file.name;
}

function readEntries(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

async function walk(entry, prefix, files) {
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    try {Object.defineProperty(file, "vietdocPath", {value: prefix + entry.name});} catch {/* keep the name */}
    files.push(file);
    return;
  }
  if (!entry.isDirectory) return;
  const reader = entry.createReader();
  // readEntries returns the folder in chunks until an empty chunk.
  for (let chunk = await readEntries(reader); chunk.length; chunk = await readEntries(reader)) {
    for (const child of chunk) await walk(child, prefix + entry.name + "/", files);
  }
}

function dropEntries(dataTransfer) {
  return Array.from(dataTransfer?.items || [])
    .map(item => item.kind === "file" && typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null)
    .filter(Boolean);
}

export function dropHasFolder(dataTransfer) {
  return dropEntries(dataTransfer).some(entry => entry.isDirectory);
}

// Must be called synchronously from the drop event: the entries are taken before the first await.
export async function filesFromDrop(dataTransfer) {
  const plain = Array.from(dataTransfer?.files || []);
  const entries = dropEntries(dataTransfer);
  if (!entries.some(entry => entry.isDirectory)) return {files: plain, fromFolder: false};
  const files = [];
  for (const entry of entries) await walk(entry, "", files);
  return {files, fromFolder: true};
}

function sameSource(a, b) {
  return documentPath(a) === documentPath(b) && a.size === b.size && a.lastModified === b.lastModified;
}

// Splits candidate files into accepted documents (ordered like the folder: "2.pdf" before "10.pdf")
// and skipped ones with a reason. Folder imports also skip files already in the list.
export function planImport(files, {existing = [], fromFolder = false} = {}) {
  const candidates = Array.from(files || []).filter(file => !SYSTEM_FILE.test(file.name));
  if (fromFolder) candidates.sort((a, b) => collator.compare(documentPath(a), documentPath(b)));
  const accepted = [], skipped = [];
  for (const file of candidates) {
    const path = documentPath(file);
    let reason = "";
    if (!SUPPORTED.test(file.name)) reason = "unsupported";
    else if (file.size > MAX_UPLOAD_BYTES) reason = "tooLarge";
    else if (file.size < 1) reason = "empty";
    else if (fromFolder && [...existing, ...accepted].some(other => sameSource(other, file))) reason = "duplicate";
    else if (existing.length + accepted.length >= MAX_BATCH_DOCUMENTS) reason = "limit";
    if (reason) skipped.push({path, reason});
    else accepted.push(file);
  }
  return {accepted, skipped};
}

const SKIP_COUNTS = {
  unsupported: "không phải PDF/PNG/JPG", tooLarge: "lớn hơn 15 MB", empty: "tệp rỗng",
  duplicate: "đã có trong danh sách", limit: `vượt giới hạn ${MAX_BATCH_DOCUMENTS} tài liệu`,
};

export function describeImport({accepted, skipped}, {fromFolder = false} = {}) {
  if (!skipped.length) return "";
  const listed = skipped.slice(0, MAX_LISTED_SKIPS).map(item => `${item.path}: ${SKIP_REASONS[item.reason]}`);
  const counts = Object.entries(skipped.reduce((all, item) => ({...all, [item.reason]: (all[item.reason] || 0) + 1}), {}))
    .map(([reason, count]) => `${count} ${SKIP_COUNTS[reason]}`);
  const head = fromFolder || skipped.length > MAX_LISTED_SKIPS
    ? [`Đã thêm ${accepted.length} tài liệu, bỏ qua ${skipped.length} tệp: ${counts.join(", ")}.`] : [];
  const more = skipped.length > MAX_LISTED_SKIPS ? [`… và ${skipped.length - MAX_LISTED_SKIPS} tệp khác.`] : [];
  return [...head, ...listed, ...more].join("\n");
}
