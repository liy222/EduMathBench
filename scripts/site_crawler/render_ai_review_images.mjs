// Question-only evidence images for multimodal reviewers; never include answers.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),out=path.join(root,'AI复核/AI复核数据_1800题_20261023');
const jobs=JSON.parse(await fs.readFile(path.join(out,'_build_metadata/render_jobs.json'),'utf8'));
const sha=b=>createHash('sha256').update(b).digest('hex');
if(sha(await fs.readFile(jobs.member_html))!==jobs.member_html_sha256)throw Error('Member input version changed');
const browser=await chromium.launch({channel:'msedge',headless:true}),images=[],issues=[],network=[];
try{
 const page=await browser.newPage({viewport:{width:1080,height:1000},deviceScaleFactor:2});
 await page.route('**/*',r=>{if(/^https?:/.test(r.request().url())){network.push(r.request().url());return r.abort();}return r.continue();});
 await page.goto(pathToFileURL(jobs.member_html).href,{waitUntil:'load'});await page.evaluate(()=>document.fonts.ready);
 await page.addStyleTag({content:'#card details{display:none!important}#card{border:0;border-radius:0;padding:20px;font-size:18px;background:white}#questionId{font-size:23px!important}'});
 for(const job of jobs.jobs){
  const result=await page.evaluate(async job=>{
   const id=window.__EMB_AUDIT__.visit(job.review_no-1),card=document.querySelector('#card');
   await Promise.all([...card.querySelectorAll('img')].map(im=>im.decode().catch(()=>{})));
   // Remove disclosure nodes completely, so their answer text cannot be rasterized.
   for(const e of card.querySelectorAll('details'))e.remove();
   return {id,images:card.querySelectorAll('img').length,broken:[...card.querySelectorAll('img')].some(im=>!im.naturalWidth),formulaError:!!card.querySelector('.katex-error'),text:card.innerText};
  },job);
  if(result.id!==job.question_id||!result.images||result.broken||result.formulaError||/查看来源答案|候选答案|生成者验算依据|自查推导/.test(result.text))throw Error('Question-only render failed: '+job.review_no);
  const file=path.resolve(out,job.path);if(!file.startsWith(path.resolve(out)+path.sep))throw Error('Output outside packet');
  await fs.mkdir(path.dirname(file),{recursive:true});await page.locator('#card').screenshot({path:file});
  images.push({review_no:job.review_no,question_id:job.question_id,input_sha256:job.input_sha256,path:job.path,sha256:sha(await fs.readFile(file)),original_image_occurrences:result.images,contains_answer_or_solution:false});
  if(images.length%100===0)console.log(JSON.stringify({rendered:images.length,total:jobs.jobs.length}));
 }
 const report={dataset_id:jobs.dataset_id,member_html_sha256:jobs.member_html_sha256,source_questions_sha256:jobs.source_questions_sha256,images,issues,external_requests:network,passed:images.length===619&&!issues.length&&!network.length,scope:'Question-only rendered evidence for image-dependent records; not OCR or mathematical validation.'};
 await fs.writeFile(path.join(out,'image_render_report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,rendered:images.length}));
}finally{await browser.close();}
