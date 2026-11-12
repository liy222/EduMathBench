const fs=require('fs');
const path=require('path');
const sharp=require('C:/Users/liyh/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/sharp');
const read=p=>fs.readFileSync(p,'utf8').split(/\r?\n/).filter(Boolean).map(x=>JSON.parse(x));
const root=path.resolve(__dirname,'..'),base=path.join(root,'data/hard_collection/completion');
const pool=new Map(read(path.join(root,'data/hard_collection/images_round1/bulk_probe/cmm_image_candidates.jsonl')).map(q=>[q.candidate_id,q]));
const labels=['g7_labels','g8_labels','g9_labels'].flatMap(n=>read(path.join(base,n+'.jsonl'))).filter(a=>a.difficulty==='困难'&&a.decision==='eligible');
const output=[];
(async()=>{
 for(let start=0;start<labels.length;start+=12){
  const batch=labels.slice(start,start+12),composites=[];
  for(let i=0;i<batch.length;i++){
   const a=batch[i],q=pool.get(a.candidate_id),refs=q.image_refs.slice(0,q.question.split('<ImageHere>').length-1);
   const cols=Math.max(1,refs.length);
   for(let j=0;j<refs.length;j++){
    const image=await sharp(path.join(base,'images',refs[j])).resize({width:Math.floor(480/cols)-5,height:270,fit:'inside'}).flatten({background:'#fff'}).toBuffer();
    composites.push({input:image,left:(i%3)*480+j*Math.floor(480/cols)+4,top:Math.floor(i/3)*310+35});
   }
   const title=Buffer.from(`<svg width="480" height="30"><text x="8" y="23" font-size="17">${q.candidate_id} (${refs.join(',')})</text></svg>`);
   composites.push({input:title,left:(i%3)*480,top:Math.floor(i/3)*310});
   output.push({candidate_id:q.candidate_id,question:q.question,options:q.options,answer:q.answer,analysis:q.analysis,image_refs:q.image_refs,label:a});
  }
  await sharp({create:{width:1440,height:Math.ceil(batch.length/3)*310,channels:3,background:'#fff'}}).composite(composites).png().toFile(path.join(base,'root_hard_contact_'+Math.floor(start/12)+'.png'));
 }
 fs.writeFileSync(path.join(base,'root_review_input.jsonl'),output.map(x=>JSON.stringify(x)).join('\n')+'\n');
 process.stdout.write(JSON.stringify({questions:labels.length,sheets:Math.ceil(labels.length/12)}));
})();
