// Standalone logged-in acquisition, driven only by normal visible pages.
import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createInterface} from 'node:readline/promises';
import {createHash} from 'node:crypto';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const out=path.join(root,'data/benchmark_web_v0.2/browser_capture');
await fs.mkdir(path.join(out,'raw'),{recursive:true});
const configIndex=process.argv.indexOf('--config');
const configFile=configIndex>=0?path.resolve(process.argv[configIndex+1]):path.join(here,'tasks.json');
const tasks=JSON.parse(await fs.readFile(configFile,'utf8')).tasks.filter(t=>t.site!=='tiku');
const context=await chromium.launchPersistentContext(path.join(here,'.local_browser_profile'),{channel:'msedge',headless:false,viewport:null});
const pages=[];
let manifest={format:'edumath-browser-acquisition-v1',started_at:new Date().toISOString(),items:[],events:[]};
try{manifest=JSON.parse(await fs.readFile(path.join(out,'manifest.json'),'utf8'));}catch(error){if(error.code!=='ENOENT')throw error;}
const flush=()=>fs.writeFile(path.join(out,'manifest.json'),JSON.stringify(manifest,null,2));
const log=(site,status,extra={})=>{manifest.events.push({site,status,at:new Date().toISOString(),...extra});console.log(JSON.stringify({site,status,...extra}));};
for(const task of tasks){
 const page=await context.newPage();pages.push({page,task});
 try{await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:30000});log(task.site,'login_window_opened',{url:task.url});}
 catch(error){log(task.site,'navigation_warning',{error:String(error)});}
}
await flush();
const input=createInterface({input:process.stdin,output:process.stdout});
if(!process.argv.includes('--no-prompt'))await input.question('请在三个专用Edge页面正常登录。完成后在终端按回车，或在聊天回复已登录：');
for(const {page,task} of pages){
 let saved=0;let paused=false;const seen=new Set();
 try{
  await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:30000});
  for(let n=0;n<2;n++){
   await page.waitForTimeout(1800);
   const links=await page.locator('a[href]').evaluateAll(els=>els.map(a=>({url:a.href,text:a.textContent.trim()})).filter(a=>/\/question\/detail[\/-]|\/math\/ques\/detail\//.test(a.url)));
   log(task.site,'list_scanned',{url:page.url(),detail_links:links.length});
   for(const item of links){
    const identity=new URL(item.url).pathname;
    if(saved>=20||seen.has(identity))continue;seen.add(identity);
    if(new URL(item.url).origin!==new URL(task.url).origin)continue;
    const detail=await context.newPage();
    try{
     await detail.goto(item.url,{waitUntil:'domcontentloaded',timeout:30000});await detail.waitForTimeout(1000);
     const visibleText=await detail.locator('body').innerText();
     if(/今日查看试题解析数量已达上限/.test(visibleText)){log(task.site,'paused_daily_access_quota',{url:item.url});paused=true;break;}
     const markup=await detail.locator('body').evaluate(body=>{
      const clone=body.cloneNode(true),a=[...body.querySelectorAll('*')],b=[...clone.querySelectorAll('*')];
      for(let i=a.length-1;i>=0;i--){const s=getComputedStyle(a[i]);if(['SCRIPT','STYLE','INPUT','TEMPLATE'].includes(a[i].tagName)||s.display==='none'||s.visibility==='hidden')b[i].remove();}
      return clone.outerHTML;
     });
     const key=createHash('sha256').update(item.url).digest('hex').slice(0,20);
     const raw=path.join('raw',`${task.site}_${key}.html`);
     await fs.writeFile(path.join(out,raw),markup);
     manifest.items.push({site:task.site,url:item.url,raw_path:raw,filters:{module:'数与式',...task.filters},listing:{url:page.url()},collection_method:'playwright_browser_crawler',sha256:createHash('sha256').update(markup).digest('hex')});
     log(task.site,'visible_detail_saved',{url:item.url});saved++;await flush();
    }catch(error){log(task.site,'detail_failed',{url:item.url,error:String(error)});}
    finally{await detail.close();}
    await page.waitForTimeout(1800);
   }
   if(paused)break;
   if(saved>=20)break;
   const next=page.getByRole('link',{name:'下一页',exact:true});
   if(!await next.count())break;
   const nextHref=await next.first().getAttribute('href');
   if(nextHref&&!nextHref.startsWith('javascript:'))await page.goto(new URL(nextHref,page.url()).href,{waitUntil:'domcontentloaded',timeout:30000});
   else await next.first().click();
  }
 }catch(error){log(task.site,'site_failed',{error:String(error)});}
 log(task.site,'capture_finished',{saved});await flush();
}
manifest.finished_at=new Date().toISOString();await flush();input.close();
console.log('原始页面保存完成；账号资料留在专用目录，不导出凭据。');
await context.close();
