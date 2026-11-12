// Actual offline Edge render checks; no source-site or authentication access.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const out=process.argv[2]?path.resolve(process.argv[2]):path.join(root,'data/benchmark_web_v0.2');
if(!out.startsWith(path.join(root,'data')+path.sep))throw Error('Render audit output must stay in project data');
const browser=await chromium.launch({channel:'msedge',headless:true});
const issues=[],pageErrors=[],network=[];let checks=0,images=0,formulas=0;
try {
 const page=await browser.newPage({viewport:{width:1280,height:960}});
 page.on('pageerror',e=>pageErrors.push(String(e)));
 await page.route('**/*',route=>{const url=route.request().url();if(/^https?:/.test(url)){network.push(url);return route.abort();}return route.continue();});
 await page.goto(pathToFileURL(path.join(out,'完整题库浏览.html')).href,{waitUntil:'load'});
 await page.waitForFunction(()=>window.__EMB_AUDIT__?.count===1800);
 await page.evaluate(()=>document.fonts.ready);
 for(const width of [1280,390]) {
  await page.setViewportSize({width,height:960});
  for(let i=0;i<1800;i++) {
   const result=await page.evaluate(async i=>{
    const id=window.__EMB_AUDIT__.visit(i),card=document.querySelector('#card');
    await Promise.all([...card.querySelectorAll('img')].map(im=>im.decode().catch(()=>{})));
    const failures=[];const bodyFields=[...card.children].filter(e=>!e.matches('details'));
    const inputText=bodyFields.map(e=>e.innerText).join('\n');
    if(card.querySelector('.katex-error'))failures.push({kind:'formula_error',text:card.querySelector('.katex-error').textContent});
    if(/\[图片:[^\]]+\]|<ImageHere>/.test(inputText))failures.push({kind:'unresolved_image_placeholder',text:inputText.match(/\[图片:[^\]]+\]|<ImageHere>/)?.[0]});
    if(/\ufffd|blob\.png/.test(inputText))failures.push({kind:'encoding_residue'});
    for(const im of card.querySelectorAll('img'))if(!im.naturalWidth||!im.naturalHeight)failures.push({kind:'image_failed',hash:im.dataset.assetHash});
    if(document.documentElement.scrollWidth>innerWidth+2)failures.push({kind:'page_overflow',width:document.documentElement.scrollWidth});
    if(card.scrollWidth>card.clientWidth+2)failures.push({kind:'card_overflow',width:card.scrollWidth,client:card.clientWidth});
    return {id,failures,images:card.querySelectorAll('img').length,formulas:card.querySelectorAll('.katex').length};
   },i);
   checks++;images+=result.images;formulas+=result.formulas;
   for(const failure of result.failures)issues.push({id:result.id,viewport_width:width,...failure});
   if(i%200===0)console.log(JSON.stringify({width,visited:i+1,issues:issues.length}));
  }
 }
 const filters=[];
 await page.click('#reset');
 for(const [selector,value,expected] of [['#split','dev',150],['#split','test',1650],['#split','debug',100],['#kind','variant',300],['#origin','new_web_crawl',1137],['#solutionStatus','has',0],['#solutionStatus','missing',1800]]){
  await page.click('#reset');await page.selectOption(selector,value);const counter=await page.locator('#counter').innerText();const got=Number(counter.split('/').at(-1).trim());filters.push({selector,value,expected,got,passed:got===expected});
 }
 await page.click('#reset');await page.selectOption('#split','dev');await page.selectOption('#kind','variant');filters.push({selector:'dev_and_variant',expected:0,got:Number((await page.locator('#counter').innerText()).split('/').at(-1).trim()),passed:(await page.locator('#counter').innerText())==='0 / 0'});
 await page.click('#reset');await page.selectOption('#kind','variant');await page.click('#family');const familyCount=Number((await page.locator('#counter').innerText()).split('/').at(-1).trim());filters.push({selector:'variant_family',minimum:2,got:familyCount,passed:familyCount>=2});
 await page.click('#reset');await page.setViewportSize({width:1280,height:960});
 await page.evaluate(()=>window.__EMB_AUDIT__.visit(1500));await page.locator('details').first().evaluate(el=>el.open=true);
 await page.screenshot({path:path.join(out,'reports/render_variant.png'),fullPage:true});
 const records=(await fs.readFile(path.join(out,'questions.jsonl'),'utf8')).trim().split(/\r?\n/).map(JSON.parse);
 const imageIndex=records.findIndex(q=>q.image_assets.length>1);await page.evaluate(i=>window.__EMB_AUDIT__.visit(i),imageIndex);await page.waitForTimeout(100);
 await page.screenshot({path:path.join(out,'reports/render_image.png'),fullPage:true});
 const report={checked_at:new Date().toISOString(),data_sha256:createHash('sha256').update(await fs.readFile(path.join(out,'questions.jsonl'))).digest('hex'),engine:'installed Microsoft Edge via Playwright',file_protocol:true,records:1800,viewports:[1280,390],render_visits:checks,image_instances:images,formula_instances:formulas,issues,page_errors:pageErrors,external_requests:network,filters,passed:!issues.length&&!pageErrors.length&&!network.length&&filters.every(x=>x.passed),scope:'DOM, KaTeX, image decoding and overflow checks for each record at both widths; screenshots inspected separately. Not mathematical or full human visual approval.'};
 await fs.writeFile(path.join(out,'reports/browser_render_check.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({passed:report.passed,issues:issues.slice(0,15),pageErrors,filters}));
}finally{await browser.close();}
