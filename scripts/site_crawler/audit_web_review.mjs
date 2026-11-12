import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..'),out=path.join(root,'data/benchmark_web_v0.2');
const browser=await chromium.launch({channel:'msedge',headless:true}),issues=[],requests=[];let checked=0;
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>issues.push({kind:'page_error',error:String(e)}));
 await page.route('**/*',route=>{if(/^https?:/.test(route.request().url())){requests.push(route.request().url());return route.abort();}return route.continue();});
 await page.goto(pathToFileURL(path.join(out,'人工复核对照.html')).href,{waitUntil:'load'});
 const groups=await page.locator('#group option').evaluateAll(els=>els.map(x=>x.value));
 for(const group of groups){
  await page.selectOption('#group',group);const ids=await page.locator('#item option').evaluateAll(els=>els.map(x=>x.value));
  for(const id of ids){
   await page.selectOption('#item',id);
   if(group.startsWith('OCR')){if(await page.locator('#ocr img[alt="来源答案原图"]').count()!==1)issues.push({id,kind:'OCR_evidence_missing'});}
   else {
    const frame=page.frameLocator('#normalized');await frame.locator('#card').waitFor();
    for(let i=0;i<10;i++){if(await frame.locator('#card').getAttribute('data-question-id')===id)break;await page.waitForTimeout(30);}
    if(await frame.locator('#card').getAttribute('data-question-id')!==id)issues.push({id,kind:'question_jump_failed'});
   }
   if(!(await page.locator('#raw').getAttribute('srcdoc')))issues.push({id,kind:'raw_source_empty'});
   await page.frameLocator('#raw').locator('body').waitFor();
   if((await page.frameLocator('#raw').locator('body').innerText()).trim().length<40)issues.push({id,kind:'raw_source_visibly_empty'});checked++;
  }
 }
 await page.selectOption('#group',groups[0]);await page.locator('#item').selectOption({index:3});await page.waitForTimeout(200);
 await page.screenshot({path:path.join(out,'reports/review_page.png'),fullPage:true});
 const report={checked_at:new Date().toISOString(),data_sha256:createHash('sha256').update(await fs.readFile(path.join(out,'questions.jsonl'))).digest('hex'),review_html_sha256:createHash('sha256').update(await fs.readFile(path.join(out,'人工复核对照.html'))).digest('hex'),checked_tasks:checked,groups:groups.length,issues,external_requests:requests,passed:checked===100&&!issues.length&&!requests.length,human_review_completed:false};
 await fs.writeFile(path.join(out,'reports/review_page_check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await browser.close();}
