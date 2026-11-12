import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(import.meta.url),katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));
const file=process.argv[2]||path.join(root,'data/benchmark_web_v0.2/candidates/questions.jsonl');
const rows=(await fs.readFile(file,'utf8')).trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);
const issues=[];let formulas=0;
for(const q of rows){
 for(const [field,value] of Object.entries({question:q.question,...Object.fromEntries(Object.entries(q.options).map(([k,v])=>['option_'+k.toLowerCase(),v]))})){
  let outside='',cursor=0;
  const pattern=/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$|\\\(([\s\S]*?)\\\)|\\\[([\s\S]*?)\\\]/g;
  for(const m of value.matchAll(pattern)){
   outside+=value.slice(cursor,m.index);cursor=m.index+m[0].length;const expression=m[1]??m[2]??m[3]??m[4];formulas++;
   try{katex.renderToString(expression,{throwOnError:true,strict:'ignore'});}catch(error){issues.push({id:q.id,field,kind:'katex_parse_error',formula:expression,error:String(error)});}
  }
  outside+=value.slice(cursor);
  if(/\\(?:frac|sqrt|cdot|begin|left|right|overline|underline|theta|alpha|beta)\b|[a-zA-Z0-9}]\^\{/.test(outside))issues.push({id:q.id,field,kind:'unwrapped_math_command',fragment:outside.slice(0,180)});
  if(/[\ufffd\u0000-\u0008]|blob\.png/.test(value))issues.push({id:q.id,field,kind:'encoding_or_filename_residue'});
  if((outside.match(/(?<!\\)\$/g)||[]).length)issues.push({id:q.id,field,kind:'unclosed_math_delimiter'});
 }
}
const out=path.join(root,'data/benchmark_web_v0.2/reports/formula_audit.json');
await fs.writeFile(out,JSON.stringify({checked_at:new Date().toISOString(),records:rows.length,formulas,issues},null,2));
console.log(JSON.stringify({records:rows.length,formulas,issues:issues.length,issue_examples:issues.slice(0,4)}));
