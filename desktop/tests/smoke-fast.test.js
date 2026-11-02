'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {validateFastScope} = require('../electron/lib/smoke-fast');

function result(usedOcr = true) {
  return {method:'metadata_fast', partial_result:true, source_page_count:6, inspected_pages:[1],
    processed_pages:usedOcr ? [1] : [], used_ocr:usedOcr, page_count:1,
    pages:[{page:1, text:'Header tiếng Việt'}], text:'Header tiếng Việt', line_count:1};
}

test('real fast result can contain one header page while retaining six source pages', () => {
  assert.equal(validateFastScope(result()).source_page_count, 6);
  assert.deepEqual(validateFastScope(result(false)).processed_pages, []);
});

test('full-document, appendix or misleading partial scopes cannot pass the fast gate', () => {
  const invalid = [
    {partial_result:false}, {source_page_count:0}, {source_page_count:7}, {source_page_count:'6'},
    {processed_pages:[1,4,5,6]}, {processed_pages:[1,1]}, {inspected_pages:[1,2]},
    {processed_pages:[]}, {pages:[{page:2,text:'Header tiếng Việt'}]}, {text:'changed raw'},
    {method:'hybrid_h1'}, {page_count:6},
  ];
  for (const change of invalid) assert.throws(() => validateFastScope({...result(), ...change}), JSON.stringify(change));
});
