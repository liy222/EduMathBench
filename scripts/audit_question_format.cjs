// Parse every input formula with the same offline KaTeX engine as the local page.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const root = path.resolve(__dirname, '..');
const katex = require(path.join(root, 'data/reports/visualization_assets/katex.min.js'));
const canonical = process.argv.includes('--canonical');
const inputPath = canonical ? 'data/normalized/questions.jsonl' : 'data/public_draft/questions.jsonl';
const inputData=fs.readFileSync(path.join(root,inputPath));
const questions = inputData.toString('utf8').trim().split(/\r?\n/).map(JSON.parse);
const delimiters = [ ['$$','$$',true], ['$','$',false], ['\\(','\\)',false], ['\\[','\\]',true] ];
function findEnd(right, text, start) {
  let depth=0;
  for(let i=start; i<text.length; i++) {
    if(depth<=0 && text.startsWith(right,i)) return i;
    if(text[i]==='\\') i++;
    else if(text[i]==='{') depth++;
    else if(text[i]==='}') depth--;
  }
  return -1;
}
function splitMath(text) {
  const result=[];
  let offset=0;
  while(offset<text.length) {
    let match=null;
    for(const d of delimiters) {
      const index=text.indexOf(d[0],offset);
      if(index>=0 && (!match || index<match.index)) match={d,index};
    }
    if(!match) {result.push({type:'text',data:text.slice(offset)});break;}
    if(match.index>offset) result.push({type:'text',data:text.slice(offset,match.index)});
    const end=findEnd(match.d[1],text,match.index+match.d[0].length);
    if(end<0) {result.push({type:'text',data:text.slice(match.index),unclosed:true});break;}
    result.push({type:'math',data:text.slice(match.index+match.d[0].length,end),display:match.d[2]});
    offset=end+match.d[1].length;
  }
  return result;
}
let formulas=0, fields=0;
const issues=[];
const warnings=[];
const seen=new Set();
function issue(q,field,kind,details) {
  const row={id:q.id,field,kind,...details,source_ref:q.source_ref,batch_id:q.batch_id};
  const key=JSON.stringify(row);
  if(!seen.has(key)){seen.add(key);issues.push(row);}
}
for(const q of questions) {
  for(const field of ['question','option_a','option_b','option_c','option_d']) {
    fields++;
    const value=q[field];
    if(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\ufffd]/.test(value)) issue(q,field,'control_or_replacement_character',{text:value});
    if(/<\/?(?:p|span|div|br|img|table|sup|sub|math)\b|&(?:nbsp|lt|gt|amp|#\d+|#x[a-f\d]+);/i.test(value)) issue(q,field,'literal_html_markup',{text:value});
    const pieces=splitMath(value);
    for(const p of pieces) {
      if(p.type==='math') {
        formulas++;
        const oldWarn=console.warn;
        console.warn=(message)=>warnings.push({id:q.id,field,formula:p.data,message:String(message)});
        try {katex.renderToString(p.data,{throwOnError:true,strict:'ignore',displayMode:p.display});}
        catch(e) {issue(q,field,'formula_parse_error',{formula:p.data,error:e.message});}
        finally {console.warn=oldWarn;}
      } else {
        if(p.unclosed) issue(q,field,'unclosed_math_delimiter',{text:p.data});
        if(/\\[A-Za-z]+|\^\{|_\{/.test(p.data)) issue(q,field,'math_markup_outside_delimiter',{text:p.data});
      }
    }
  }
}
const counts={};for(const e of issues)counts[e.kind]=(counts[e.kind]||0)+1;
const report={generated_at:new Date().toISOString(),input_path:inputPath,input_sha256:crypto.createHash('sha256').update(inputData).digest('hex'),scope:'全库1500题题干及四选项，使用本地页面同版本KaTeX逐公式解析；非浏览器视觉检查、非数学正确性验算。',question_count:questions.length,fields_checked:fields,formulas_checked:formulas,issue_count:issues.length,affected_questions:new Set(issues.map(e=>e.id)).size,issue_counts:counts,font_warning_count:warnings.length,font_warnings:warnings,issues};
fs.writeFileSync(path.join(root,'data/reports/'+(canonical?'canonical_question_format_audit.json':'question_format_audit.json')),JSON.stringify(report,null,2)+'\n','utf8');
console.log(JSON.stringify({...report,issues:issues.slice(0,12)},null,2));
