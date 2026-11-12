// Discover a new knowledge ID by ordinary tree controls and resulting pagination.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../..');
const cfg=JSON.parse(await fs.readFile(path.join(here,'tasks.json'),'utf8'));
const ctx=await chromium.launchPersistentContext(path.join(here,'.local_browser_profile'),{channel:'msedge',headless:false});
const output=[],events=[];
for(const task of cfg.tasks.filter(t=>t.site==='21cnjy'||t.site==='chujuan')){
 const page=await ctx.newPage();
 const observedIds=[];
 page.on('request',request=>{
  try{const u=new URL(request.url());if(u.origin===new URL(task.url).origin){const id=u.searchParams.get('knowledges')||u.searchParams.get('knowledges[]');if(id&&id!=='11568'&&!id.includes(','))observedIds.push(id);}}catch{}
 });
 try{
  try{await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:30000});}
  catch{await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:30000});}
  await page.waitForTimeout(3500);
  // Normal first-use help overlay, not a login or verification challenge.
  const understood=page.locator('.filter-guide .guide-btn').first();
  if(await understood.count()&&await understood.isVisible())await understood.click();
  const closeTour=page.locator('[data-eyzt-close="1"]').first();
  if(await closeTour.count()&&await closeTour.isVisible())await closeTour.click();
  await page.locator('.tab-tree-group[data-tab="知识点"]').click();await page.waitForTimeout(1000);
  const target=page.locator('.JV_tree_bd .t-name a').filter({hasText:/^解一元一次方程$/}).first();
  const ancestors=await target.locator('xpath=ancestor::li[contains(@class,"t-checkbox-node")]').all();
  for(const parent of ancestors){
   const list=parent.locator(':scope > ul').first();
   const button=parent.locator(':scope > .t-tit > .t-btn').first();
   if(await list.count()&&!await list.isVisible()&&await button.isVisible()){await button.click();await page.waitForTimeout(250);}
  }
  await target.waitFor({state:'visible',timeout:10000});
  await target.locator('xpath=ancestor::li[1]').locator(':scope > .t-tit > .t-checkbox').click();
  await page.waitForTimeout(4500);
  const hrefs=await page.locator('a[data-page],a').evaluateAll(els=>els.map(a=>a.href).filter(u=>u.includes('knowledges')));
  let observed=hrefs.map(u=>new URL(u)).find(u=>u.searchParams.get('knowledges')&&u.searchParams.get('knowledges')!=='11568');
  if(!observed&&observedIds.length){observed=new URL(task.url);observed.searchParams.set('knowledges',observedIds.at(-1));}
  if(!observed)throw new Error('没有找到反映新筛选条件的分页地址或正常浏览器请求');
  const ids=observed.searchParams.get('knowledges');
  if(ids.includes(',')||ids==='11568')throw new Error('筛选尚未切到单个目标知识点：'+ids);
  observed.searchParams.set('page','1');
  output.push({...task,url:observed.href,filters:{...task.filters,module:'方程与不等式',knowledge:'解一元一次方程',knowledge_path:['方程与不等式','一元一次方程','解一元一次方程']},knowledge_id:ids});
  events.push({site:task.site,status:'native_tree_selection_verified',knowledge:'解一元一次方程',knowledge_id:ids,url:observed.href});
 }catch(error){events.push({site:task.site,status:'tree_selection_failed',error:String(error)});await fs.writeFile(path.join(root,`data/benchmark_web_v0.2/knowledge/${task.site}_tree_debug.html`),await page.content());}
 await page.close();
}
const j=cfg.tasks.find(t=>t.site==='jyeoo');const url=new URL(j.url);url.searchParams.set('q','22286');
output.push({...j,url:url.href,filters:{...j.filters,module:'方程与不等式',knowledge:'解一元一次方程',knowledge_path:['方程与不等式','一元一次方程','解一元一次方程']},knowledge_id:'22286'});
await fs.writeFile(path.join(here,'second_module_tasks.json'),JSON.stringify({prefer_text:true,tasks:output},null,2));
await fs.writeFile(path.join(root,'data/benchmark_web_v0.2/knowledge/second_module_discovery.json'),JSON.stringify(events,null,2));
console.log(JSON.stringify(events));await ctx.close();
