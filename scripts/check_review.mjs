import assert from 'node:assert/strict';
import {findPassages} from '../web/src/documentEvidence.js';
import {mergeBackup} from '../web/src/backup.js';
for(const newline of ['\n\n','\r\n\r\n']){const text='First paragraph.'+newline+'The method reduces measurement error.';const hits=findPassages(text,'measurement error');assert.equal(hits[0].index,2);assert.equal(hits[0].text,'The method reduces measurement error.');}
assert.deepEqual(findPassages('No relevant evidence.','quantum'),[]);
const result=mergeBackup({version:1,papers:[{paper_id:'a',title:'Paper'}],notes:{a:{review_methods:'Reviewed against paragraph 2'}}},[],{});assert.equal(result.notes.a.review_methods,'Reviewed against paragraph 2');
const preserved=mergeBackup({version:1,papers:[{paper_id:'a',title:'Paper'}],notes:{a:{review_methods:'Imported'}}},[],{a:{review_methods:'Existing'}});assert.equal(preserved.notes.a.review_methods,'Existing');
console.log('PASS paragraph references, no-match evidence, review-note backup and merge');
