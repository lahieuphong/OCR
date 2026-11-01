'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { EMPTY_TEXT_PLACEHOLDER, matchesTextView } = require('../electron/lib/smoke-text');

test('an empty native page matches the placeholder actually displayed by the UI', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../../demo/local_pdf_ocr/frontend/src/App.jsx'), 'utf8');
  const match = source.match(/shownText \|\| ("(?:[^"\\]|\\.)*")/u);
  assert.ok(match, 'the actual empty-result rendering contract must be checked');
  const rendered = JSON.parse(match[1]);
  assert.equal(rendered, EMPTY_TEXT_PLACEHOLDER);
  assert.equal(matchesTextView(rendered, ''), true);
});

test('nonempty page text requires exact Unicode, leading zeros and line breaks', () => {
  const text = 'Số: 00103/TEST-CN\nV/v kiểm thử tiếng Việt';
  assert.equal(matchesTextView(text, text), true);
  assert.equal(matchesTextView(text.replace('00103', '103'), text), false);
  assert.equal(matchesTextView(text.replace('thử', 'thứ'), text), false);
  assert.equal(matchesTextView(text.replace('\n', ' '), text), false);
});

test('a placeholder cannot hide missing nonempty text', () => {
  assert.equal(matchesTextView(EMPTY_TEXT_PLACEHOLDER, 'Văn bản có chữ'), false);
});

test('a missing element or invalid API value cannot pass as an empty page', () => {
  for (const [rendered, expected] of [[null, ''], [undefined, ''], [EMPTY_TEXT_PLACEHOLDER, null],
    [EMPTY_TEXT_PLACEHOLDER, undefined], ['', '']]) {
    assert.equal(matchesTextView(rendered, expected), false);
  }
});

test('unrelated empty-state messages do not pass', () => {
  for (const rendered of ['Đang bóc tách', 'Không có dữ liệu', EMPTY_TEXT_PLACEHOLDER + '\n']) {
    assert.equal(matchesTextView(rendered, ''), false);
  }
});
