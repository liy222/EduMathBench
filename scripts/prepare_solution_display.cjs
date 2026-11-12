// Keep malformed source excerpts literal; never infer omitted derivation text.
const fs=require('fs'),path=require('path');const root=path.resolve(__dirname,'..');
const target=path.join(root,'data/benchmark_draft/solution_display.json');
const items=JSON.parse(fs.readFileSync(target,'utf8'));
const questions=new Map(fs.readFileSync(path.join(root,'data/benchmark_draft/questions.jsonl'),'utf8').trim().split('\n').map(s=>{const q=JSON.parse(s);return [q.id,q]}));
const katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));let fallback=0;
for(const [id,item] of Object.entries(items)){
  const s=item.text,issues=[];
  if((s.match(/(?<!\\)\$/g)||[]).length%2)issues.push('unbalanced_math_delimiters');
  if(/\\[A-Za-z]+/.test(s.replace(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g,'')))issues.push('macro_outside_math');
  if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(s))issues.push('control_character');
  for(const m of s.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g))try{katex.renderToString(m[1]??m[2],{throwOnError:true,strict:'ignore'})}catch(e){issues.push(e.message)}
  if(issues.length){
    if(item.source_type==='variant')throw Error('variant derivation issue '+id+': '+issues.join(';'));
    item.status='raw_source_fragment';item.text=questions.get(id).solution;item.rules=[];item.issues=issues;fallback++;
  }
}
fs.writeFileSync(target,JSON.stringify(items,null,2)+'\n');
console.log(JSON.stringify({source_fragment_fallbacks:fallback,scope:'Display only; source solution and source answer unchanged.'}));
