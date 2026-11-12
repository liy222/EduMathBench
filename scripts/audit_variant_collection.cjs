// Explicitly a formula-engine and synthetic-control audit, not a browser run.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const root=path.resolve(__dirname,'..');
const pagePath=path.join(root,'可视化/变式题库浏览.html');
const html=fs.readFileSync(pagePath,'utf8');
const pairs=JSON.parse(html.match(/<script id="pairs-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));
const errors=[];let formulas=0,imageRefs=0;
for(const pair of pairs)for(const [role,q] of [['parent',pair.parent],['variant',pair.variant]]){
  for(const [field,text] of [['question',q.question],...Object.entries(q.options),['solution',q.solution||'']]){
    for(const m of text.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g)){
      formulas++;
      try{katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,strict:'ignore'});}catch(e){errors.push({id:q.id,role,field,message:e.message});}
    }
    if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text))errors.push({id:q.id,field,message:'control character'});
    if((text.match(/(?<!\\)\$/g)||[]).length%2)errors.push({id:q.id,field,message:'unbalanced math delimiters'});
    if(/\\[A-Za-z]+/.test(text.replace(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g,'')))errors.push({id:q.id,field,message:'macro outside math'});
  }
  const assets=q.image_data||[];imageRefs+=assets.length;
  for(const image of assets)if(!/^data:image\/(png|jpeg|svg\+xml);base64,/.test(image.data_url))errors.push({id:q.id,message:'image not embedded'});
}
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].filter(m=>!m[0].startsWith('<script id="pairs-data"'));
scripts.forEach((m,i)=>new vm.Script(m[1],{filename:'collection-script-'+i}));
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.textContent='';this.value='';}
  append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes;this.textContent=''}setAttribute(k,v){this[k]=v}
  addEventListener(k,v){this.events[k]=v}fire(event){this.events[event]()}
}
const ids={};for(const id of ['grade','difficulty','prev','next','position','parent','variant','change','metadata','pairs-data'])ids[id]=new Element('div');
ids['pairs-data'].textContent=JSON.stringify(pairs);
const document={getElementById:id=>{if(!ids[id])throw new Error('missing id '+id);return ids[id]},createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
const context=vm.createContext({document,renderMathInElement:()=>{},console});
vm.runInContext(fs.readFileSync(path.join(root,'data/visualization/question_content.js'),'utf8'),context);
vm.runInContext(scripts.at(-1)[1],context);
let controlChecks=0;
function assert(test,msg){if(!test)throw new Error(msg);controlChecks++}
assert(ids.position.textContent===`1 / ${pairs.length}`,'initial count');
for(let i=0;i<pairs.length;i++){
  assert(ids.parent.children[0].textContent===pairs[i].parent.id,'parent id on pair '+i);
  assert(ids.variant.children[0].textContent===pairs[i].variant.id,'variant id on pair '+i);
  assert(ids.parent.children.filter(n=>n.tag==='img').length===(pairs[i].parent.image_data||[]).length,'parent images on pair '+i);
  if(i<pairs.length-1)ids.next.fire('click');
}
assert(ids.next.disabled,'last boundary');
for(const grade of ['','7','8','9'])for(const difficulty of ['','基础','中等','困难']){
  ids.grade.value=grade;ids.difficulty.value=difficulty;ids.grade.fire('change');
  const n=pairs.filter(p=>(!grade||String(p.variant.grade)===grade)&&(!difficulty||p.variant.difficulty===difficulty)).length;
  assert(ids.position.textContent===(n?`1 / ${n}`:'没有匹配题对'),'filter '+grade+'/'+difficulty);
  assert(ids.prev.disabled,'reset to first');
}
ids.grade.value='';ids.difficulty.value='';ids.grade.fire('change');ids.next.fire('click');ids.prev.fire('click');
assert(ids.position.textContent===`1 / ${pairs.length}`,'previous navigation');
assert(!/<(?:script|link)[^>]+(?:src|href)\s*=/.test(html),'no external script/style asset');
assert(!/url\(fonts\//.test(html),'fonts embedded');
const report={pairs:pairs.length,formulas_checked:formulas,formula_errors:errors,script_syntax_passed:true,synthetic_control_checks:controlChecks,embedded_parent_images:imageRefs,embedded_font_faces:(html.match(/src:url\(data:font/g)||[]).length,page_sha256:crypto.createHash('sha256').update(html).digest('hex'),browser_execution_verified:false,scope:'All formulas parsed by KaTeX; synthetic DOM checks across all pairs, filters, navigation and image associations. No actual browser execution, pixel/layout or font-loading assurance.'};
fs.writeFileSync(path.join(root,'data/reports/variant_collection_presentation_check.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));if(errors.length)process.exitCode=1;
