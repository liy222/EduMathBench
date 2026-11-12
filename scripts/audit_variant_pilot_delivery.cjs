// Formula engine and presentation-control checks; never a browser execution claim.
const fs=require('fs'),path=require('path'),vm=require('vm');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'可视化/变式试做题对.html'),'utf8');
const data=JSON.parse(html.match(/<script id="pairs-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);
const katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));
const errors=[];let formulas=0;
for(const {parent,variant} of data){
  for(const [role,q] of [['parent',parent],['variant',variant]]){
    for(const [field,text] of [['question',q.question],...Object.entries(q.options),['solution',q.solution||'']]){
      for(const m of text.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g)){
        formulas++;
        try{katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,strict:'ignore'});}catch(e){errors.push({id:q.id,role,field,message:e.message});}
      }
      if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text))errors.push({id:q.id,field,message:'control character'});
      const rest=text.replace(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g,'');
      if(/\\[A-Za-z]+/.test(rest))errors.push({id:q.id,field,message:'macro outside math'});
    }
  }
}
const scripts=[...html.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/g)].filter(m=>!m[0].startsWith('<script id="pairs-data"'));
scripts.forEach((m,i)=>new vm.Script(m[1],{filename:'pilot-script-'+i}));
class Element{
  constructor(tag){this.tag=tag;this.children=[];this.events={};this.textContent='';this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;this.textContent='';}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,v){this.events[k]=v;}
  fire(event){this.events[event]();}
}
const ids={};for(const id of ['grade','difficulty','prev','next','position','parent','variant','change','metadata','pairs-data'])ids[id]=new Element('div');
ids['pairs-data'].textContent=JSON.stringify(data);
const document={getElementById:id=>{if(!ids[id])throw new Error('missing id '+id);return ids[id]},createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
const context=vm.createContext({document,renderMathInElement:()=>{},console});
vm.runInContext(fs.readFileSync(path.join(root,'data/visualization/question_content.js'),'utf8'),context);
vm.runInContext(scripts.at(-1)[1],context);
function assert(test,msg){if(!test)throw new Error(msg)}
assert(ids.position.textContent==='1 / 30','initial position');
ids.next.fire('click');assert(ids.position.textContent==='2 / 30','next navigation');
ids.prev.fire('click');assert(ids.position.textContent==='1 / 30','previous navigation');
ids.grade.value='8';ids.grade.fire('change');assert(ids.position.textContent==='1 / 10','grade filter');
ids.difficulty.value='困难';ids.difficulty.fire('change');assert(ids.position.textContent==='1 / 2','combined filter');
ids.next.fire('click');assert(ids.position.textContent==='2 / 2'&&ids.next.disabled,'last boundary');
ids.grade.value='';ids.grade.fire('change');assert(ids.position.textContent==='1 / 6','all hard');
ids.difficulty.value='';ids.difficulty.fire('change');assert(ids.position.textContent==='1 / 30','restore all');
ids.grade.value='9';ids.grade.fire('change');for(let i=0;i<4;i++)ids.next.fire('click');
assert(ids.parent.children.some(n=>n.tag==='img'&&n.src.startsWith('data:image/')),'separately linked parent image is shown');
assert(!/<(?:script|link)[^>]+(?:src|href)\s*=/.test(html),'external script/style asset');
assert(!/url\(fonts\//.test(html),'nonembedded font');
const report={pairs:data.length,formulas_checked:formulas,formula_errors:errors,script_syntax_passed:true,synthetic_control_checks:9,embedded_parent_images:data.reduce((n,p)=>n+(p.parent.image_data||[]).length,0),embedded_font_faces:(html.match(/src:url\(data:font/g)||[]).length,browser_execution_verified:false,scope:'KaTeX parsing and synthetic DOM control checks; no browser pixels, font loading, layout or actual browser runtime proof.'};
fs.writeFileSync(path.join(root,'data/reports/variant_pilot_presentation_check.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));if(errors.length)process.exitCode=1;
