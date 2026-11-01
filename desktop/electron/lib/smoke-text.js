'use strict';
// Smoke assertions compare displayed text; raw exports and clipboard text are checked separately.
const EMPTY_TEXT_PLACEHOLDER = 'Không phát hiện được dòng văn bản. Hãy kiểm tra ảnh/PDF gốc.';

function matchesTextView(rendered, expected) {
  return typeof rendered === 'string' && typeof expected === 'string'
    && rendered === (expected === '' ? EMPTY_TEXT_PLACEHOLDER : expected);
}

module.exports = { EMPTY_TEXT_PLACEHOLDER, matchesTextView };
