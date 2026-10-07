import {test} from 'node:test';
import assert from 'node:assert/strict';
import {findingsText,issueText} from '../../src/fashion_scout/static/maintenance-findings.js';
test('ordinary findings group counts and known product titles without diagnostic IDs',()=>{
  const text=findingsText([{category:'missing',code:'IMAGE_NOT_ARCHIVED',count:4,product_count:2,product_names:['米杏色 · 垂感连衣裙','暖砂色 · 简约长款风衣'],object_id:'version:fixture-version-3:1'}]);
  assert.match(text,/缺失.*4 项，涉及 2 款/);assert.match(text,/米杏色 · 垂感连衣裙/);
  assert.doesNotMatch(text,/fixture|version:|IMAGE_NOT_ARCHIVED|object_id/);
});
test('unknown product and diagnostic code stay generic without invented names',()=>{
  assert.equal(findingsText([{category:'unknown',code:'UNRECOGNIZED_INTERNAL_CODE',count:1,product_count:0,product_names:[]}]),'待确认：此项目需要进一步核对 · 1 项');
  assert.equal(findingsText(), '');assert.equal(issueText('SECRET_CODE'),'此项目需要进一步核对');
});
