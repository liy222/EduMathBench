const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),dir=path.join(root,'data/variants/batches/b003');
const katex=require(path.join(root,'data/reports/visualization_assets/katex.min.js'));
let checked=0,formulas=0;const errors=[];
for(const grade of [7,8,9]){
  const file=path.join(dir,`g${grade}.jsonl`);if(!fs.existsSync(file))continue;
  let qs;try{qs=fs.readFileSync(file,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse)}catch{continue}
  for(const q of qs){checked++;
    for(const [field,text] of [['question',q.question],...Object.entries(q.options),['solution',q.solution]]){
      for(const m of text.matchAll(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g)){
        formulas++;try{katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,strict:'ignore'})}catch(e){errors.push({id:q.id,field,message:e.message})}
      }
      if((text.match(/(?<!\\)\$/g)||[]).length%2)errors.push({id:q.id,field,message:'unbalanced delimiters'});
      if(/\\[A-Za-z]+/.test(text.replace(/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g,'')))errors.push({id:q.id,field,message:'macro outside math'});
    }
  }
}
const report={partial_records:checked,formulas_checked:formulas,errors,browser_execution_verified:false};
fs.writeFileSync(path.join(dir,'in_progress_formula_check.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
