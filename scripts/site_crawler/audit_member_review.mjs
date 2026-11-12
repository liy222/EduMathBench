// Offline checks for the portable member-review copy; no authentication needed.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=path.join(root,'成员复核/题库复核_1800题_20261023'),shots=path.join(root,'data/reports/member_review_20261023');
await fs.mkdir(shots,{recursive:true});
const records=(await fs.readFile(path.join(out,'题目集合.jsonl'),'utf8')).trim().split(/\r?\n/).map(JSON.parse);
const browser=await chromium.launch({channel:'msedge',headless:true});
const issues=[],errors=[],network=[],features=[];let visits=0,images=0,formulas=0;
try{
 const page=await browser.newPage({viewport:{width:1280,height:960}});
 page.on('pageerror',e=>errors.push(String(e)));
 await page.route('**/*',route=>{if(/^https?:/.test(route.request().url())){network.push(route.request().url());return route.abort();}return route.continue();});
 await page.goto(pathToFileURL(path.join(out,'题库复核.html')).href,{waitUntil:'load'});
 await page.waitForFunction(()=>window.__EMB_AUDIT__?.count===1800);await page.evaluate(()=>document.fonts.ready);
 for(const width of [1280,390]){
  await page.setViewportSize({width,height:960});
  for(let i=0;i<1800;i++){
   const result=await page.evaluate(async i=>{
    const id=window.__EMB_AUDIT__.visit(i),card=document.querySelector('#card');await Promise.all([...card.querySelectorAll('img')].map(im=>im.decode().catch(()=>{})));
    const failures=[],text=[...card.children].filter(e=>!e.matches('details')).map(e=>e.innerText).join('\n');
    if(document.querySelector('#questionId').textContent!==`第 ${i+1} 题`)failures.push('number_mismatch');
    if(card.querySelector('.katex-error'))failures.push('formula_error');
    if(/\[图片:[^\]]+\]|<ImageHere>|\ufffd|blob\.png/.test(text))failures.push('placeholder_or_encoding_residue');
    if([...card.querySelectorAll('img')].some(im=>!im.naturalWidth||!im.naturalHeight))failures.push('image_decode_failed');
    if(document.documentElement.scrollWidth>innerWidth+2||card.scrollWidth>card.clientWidth+2)failures.push('overflow');
    if(card.querySelector('details')?.open)failures.push('answer_not_collapsed_by_default');
    return {id,failures,images:card.querySelectorAll('img').length,formulas:card.querySelectorAll('.katex').length};
   },i);
   if(result.id!==records[i].id)result.failures.push('canonical_id_mismatch');
   if(result.failures.length)issues.push({review_number:i+1,width,...result});visits++;images+=result.images;formulas+=result.formulas;
  }
  console.log(JSON.stringify({width,visits,issues:issues.length}));
 }
 const expect=async(name,condition)=>features.push({name,passed:await condition});
 for(const n of [1,600,601,1200,1201,1800]){
  await page.fill('#reviewJump',String(n));await page.click('#jumpReview');await expect('jump_'+n,(await page.locator('#questionId').innerText())===`第 ${n} 题`);
 }
 await page.fill('#rangeStart','601');await page.fill('#rangeEnd','1200');await page.click('#applyRange');await expect('grade8_range',(await page.locator('#counter').innerText())==='1 / 600'&&(await page.locator('#questionId').innerText())==='第 601 题');
 await page.click('#next');await expect('range_stable_number',(await page.locator('#questionId').innerText())==='第 602 题');
 await page.selectOption('#kind','variant');await expect('grade8_variants',(await page.locator('#counter').innerText()).endsWith('/ 100'));
 await page.click('#reset');await expect('reset_all',(await page.locator('#counter').innerText())==='1 / 1800');
 const v=records.find(q=>q.source_type==='variant');await page.fill('#reviewJump',String(v.review_number));await page.click('#jumpReview');
 await page.locator('details').nth(1).evaluate(el=>el.open=true);await page.getByRole('button',{name:'跳到母题',exact:true}).click();await expect('parent_jump',(await page.locator('#questionId').innerText())===`第 ${v.parent_review_number} 题`);
 await page.fill('#rangeStart',String(v.review_number));await page.fill('#rangeEnd',String(v.review_number));await page.click('#applyRange');await page.click('#family');await expect('family_can_include_adjacent_parent',Number((await page.locator('#counter').innerText()).split('/').at(-1).trim())>=2);
 await page.fill('#rangeStart','10');await page.fill('#rangeEnd','5');await page.click('#applyRange');await expect('invalid_range_rejected',(await page.locator('#rangeMessage').innerText()).includes('范围须满足'));
 await page.click('#reset');await page.goto(pathToFileURL(path.join(out,'题库复核.html')).href+'#no=1201');await expect('hash_number_link',(await page.locator('#questionId').innerText())==='第 1201 题');
 await page.setViewportSize({width:1280,height:960});await page.screenshot({path:path.join(shots,'numbered_review.png'),fullPage:true});
 const imageIndex=records.findIndex(q=>q.image_assets.length>2);await page.evaluate(i=>window.__EMB_AUDIT__.visit(i),imageIndex);await page.screenshot({path:path.join(shots,'numbered_image_review.png'),fullPage:true});
 const report={checked_at:new Date().toISOString(),html_sha256:createHash('sha256').update(await fs.readFile(path.join(out,'题库复核.html'))).digest('hex'),jsonl_sha256:createHash('sha256').update(await fs.readFile(path.join(out,'题目集合.jsonl'))).digest('hex'),records:1800,render_visits:visits,viewports:[1280,390],images,formulas,issues,page_errors:errors,external_requests:network,features,human_review_completed:false,passed:!issues.length&&!errors.length&&!network.length&&features.every(f=>f.passed),scope:'review numbering, navigation, portable rendering and controls; not mathematical correctness or member approval'};
 await fs.writeFile(path.join(out,'页面检查报告.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,features,issues:issues.slice(0,5),errors}));
 if(!report.passed)process.exitCode=1;
}finally{await browser.close();}
