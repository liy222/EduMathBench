const assert=require('assert');
const fs=require('fs');
const path=require('path');
const root=path.resolve(__dirname,'..');
const {embSplitTableRow,embTableBlocks}=require('../data/visualization/question_content.js');
assert.deepStrictEqual(embSplitTableRow('| $\\|-5\\|$ | 6 |  | $2^3$ |'), ['$\\|-5\\|$','6','','$2^3$']);
assert.deepStrictEqual(embSplitTableRow('| $|x-2|$ | 3 |'), ['$|x-2|$','3']);
assert.throws(()=>embTableBlocks('| a | b |\n| --- | --- |\n| 1 |'),/列数不一致/);
let tables=0,cells=0;
for(const q of fs.readFileSync(path.join(root,'data/normalized/questions.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse)) {
  for(const key of ['question','option_a','option_b','option_c','option_d']) {
    for(const block of embTableBlocks(q[key])) if(block.type==='table'){tables++;cells+=block.rows.reduce((n,row)=>n+row.length,0);}
  }
}
assert.strictEqual(tables,9);
console.log(JSON.stringify({tables_checked:tables,cells_checked:cells,escaped_and_math_absolute_bars_preserved:true,blank_cells_preserved:true}));
