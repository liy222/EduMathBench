// Formula-engine and synthetic-control verification; no browser execution.
const fs=require('fs'),path=require('path'),vm=require('vm'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),page=path.join(root,'可视化/完整题库浏览.html'),html=fs.readFileSync(page,'utf8');
const rows=JSON.parse(html.match(/<script id="questions-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));
const errors=[];let formulas=0,imageRefs=0,sourceFragments=0;
for(const q of rows){
  const display=q.solution_display||{text:q.solution||'',status:'formatted'};
  if(display.status==='raw_source_fragment')sourceFragments++;
  for(const [field,s] of [['question',q.question],...Object.entries(q.options),['solution',display.status==='raw_source_fragment'?'':display.text],['change_description',q.change_description||''],['difficulty_reason',q.difficulty_annotation?.reason||'']]){
    for(const m of s.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g)){
      formulas++;try{katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,strict:'ignore'});}catch(e){errors.push({id:q.id,field,message:e.message})}
    }
    if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(s))errors.push({id:q.id,field,message:'control character'});
    if((s.match(/(?<!\\)\$/g)||[]).length%2)errors.push({id:q.id,field,message:'unbalanced math delimiters'});
    if(/\\[A-Za-z]+/.test(s.replace(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g,'')))errors.push({id:q.id,field,message:'macro outside math'});
  }
  imageRefs+=(q.image_data||[]).length;
  for(const image of q.image_data||[]){
    if(!/^data:image\/(png|jpeg);base64,/.test(image.data_url))errors.push({id:q.id,message:'image not embedded'});
    if(!['question','option_a','option_b','option_c','option_d'].includes(image.field))errors.push({id:q.id,message:'unhandled image field '+image.field});
  }
}
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].filter(m=>!m[0].startsWith('<script id="questions-data"'));
scripts.forEach((m,i)=>new vm.Script(m[1],{filename:'benchmark-script-'+i}));
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.textContent='';this.value=''}
  append(...nodes){this.children.push(...nodes)}replaceChildren(...nodes){this.children=nodes;this.textContent=''}setAttribute(k,v){this[k]=v}
  addEventListener(k,v){this.events[k]=v}fire(k){this.events[k]()}
}
const ids={};for(const id of ['split','sourceType','grade','module','difficulty','solutionStatus','solutionStats','search','reset','prev','position','next','family','familyTag','metadata','card','questions-data'])ids[id]=new Element('div');
ids['questions-data'].textContent=JSON.stringify(rows);
const document={getElementById:id=>{if(!ids[id])throw Error('missing id '+id);return ids[id]},createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
const ctx=vm.createContext({document,renderMathInElement:()=>{},console});
vm.runInContext(fs.readFileSync(path.join(root,'data/visualization/question_content.js'),'utf8'),ctx);vm.runInContext(scripts.at(-1)[1],ctx);
let controls=0;function assert(test,msg){if(!test)throw Error(msg);controls++}
function countImages(el){return (el.tag==='img'?1:0)+(el.children||[]).reduce((n,e)=>n+countImages(e),0)}
for(let i=0;i<rows.length;i++){
  assert(ids.card.children[0].textContent===rows[i].id,'row '+i);
  const solutionExists=Boolean(rows[i].solution?.trim()),fragment=rows[i].solution_display?.status==='raw_source_fragment';
  const label=!solutionExists?'无解析文本（仅有答案）':fragment?'有解析文本 · 源解析片段异常':'有解析文本';
  assert(ids.card.children[1].id==='solutionStatusTag'&&ids.card.children[1].textContent===label,'solution badge '+i);
  if(!solutionExists){const detail=ids.card.children.find(e=>e.tag==='details');assert(detail.children[0].textContent==='查看答案（无解析文本）','missing solution summary '+i);assert(detail.children.some(e=>e.textContent==='当前记录未保存解析文本。'),'missing solution explanation '+i)}
  assert(countImages(ids.card)===(rows[i].image_data||[]).length,'images '+i);
  if(i<rows.length-1)ids.next.fire('click');
}
assert(ids.next.disabled,'last boundary');
for(const split of ['','dev','test','debug100'])for(const sourceType of ['','public','variant'])for(const grade of ['','7','8','9'])for(const difficulty of ['','基础','中等','困难'])for(const solution of ['','has','missing','fragment']){
  ids.reset.fire('click');ids.split.value=split;ids.sourceType.value=sourceType;ids.grade.value=grade;ids.difficulty.value=difficulty;ids.solutionStatus.value=solution;ids.solutionStatus.fire('change');
  const chosen=rows.filter(q=>(!split||(split==='debug100'?q.debug_subset:q.split===split))&&(!sourceType||q.source_type===sourceType)&&(!grade||String(q.grade)===grade)&&(!difficulty||q.difficulty===difficulty)&&(!solution||(solution==='has'?Boolean(q.solution?.trim()):solution==='missing'?!q.solution?.trim():q.solution_display?.status==='raw_source_fragment'))),n=chosen.length;
  assert(ids.position.textContent===(n?`1 / ${n}`:'没有匹配题目'),'combined filter '+[split,sourceType,grade,difficulty,solution]);assert(ids.prev.disabled,'filter reset');
  const withSolution=chosen.filter(q=>q.solution?.trim()).length,fragments=chosen.filter(q=>q.solution_display?.status==='raw_source_fragment').length;
  assert(ids.solutionStats.textContent===`当前筛选 ${n} 题 · 有解析文本 ${withSolution} 题 · 无解析文本 ${n-withSolution} 题 · 其中源解析片段异常 ${fragments} 题`,'solution counts for combined filters');
}
for(const module of ['数与式','方程与不等式','函数','几何','统计与概率']){
  ids.reset.fire('click');ids.module.value=module;ids.module.fire('change');assert(ids.position.textContent===`1 / ${rows.filter(q=>q.module===module).length}`,'module '+module);
}
// Exact ID search, associated-family navigation and restoring the full set.
for(const q of rows.filter(q=>q.source_type==='variant')){
  ids.reset.fire('click');ids.search.value=q.id;ids.search.fire('input');assert(ids.position.textContent==='1 / 1','id search '+q.id);ids.family.fire('click');
  assert(ids.position.textContent===`1 / ${rows.filter(r=>r.family_id===q.family_id).length}`,'family '+q.id);
}
ids.reset.fire('click');ids.search.value='no-such-question-xyz';ids.search.fire('input');assert(ids.position.textContent==='没有匹配题目','empty search');assert(ids.family.disabled,'empty family');
ids.reset.fire('click');ids.next.fire('click');ids.prev.fire('click');assert(ids.position.textContent===`1 / ${rows.length}`,'reset/navigation');
assert(ids.solutionStatus.value==='','reset solution filter');
assert(!/<(?:script|link)[^>]+(?:src|href)\s*=/.test(html),'no external script/style');assert(!/url\(fonts\//.test(html),'fonts embedded');
const report={questions:rows.length,formulas_checked:formulas,formula_errors:errors,source_solution_fragments_displayed_literally:sourceFragments,solution_text_counts:{has:rows.filter(q=>q.solution?.trim()).length,missing:rows.filter(q=>!q.solution?.trim()).length,fragment:sourceFragments},script_syntax_passed:true,synthetic_control_checks:controls,embedded_image_refs:imageRefs,embedded_font_faces:(html.match(/src:url\(data:font/g)||[]).length,page_sha256:crypto.createHash('sha256').update(html).digest('hex'),browser_execution_verified:false,scope:'Formula parser and synthetic controls only; malformed source solution excerpts are clearly labelled and shown literally, not repaired. No browser layout, pixel or font/image-loading verification.'};
fs.writeFileSync(path.join(root,'data/reports/benchmark_draft_presentation_check.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({...report,formula_errors:errors.slice(0,12)}));if(errors.length)process.exitCode=1;
