import {chromium} from 'playwright';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const tasks=JSON.parse(await fs.readFile(path.join(here,'tasks.json'),'utf8')).tasks.filter(t=>t.site!=='tiku');
const context=await chromium.launchPersistentContext(path.join(here,'.local_browser_profile'),{channel:'msedge',headless:false});
const results=[];
for(const task of tasks){
 const page=await context.newPage();
 try{
  await page.goto(task.url,{waitUntil:'domcontentloaded',timeout:30000});await page.waitForTimeout(6000);
  const controls=await page.evaluate(()=>[...document.querySelectorAll('#divTree2 a, .JV_tree a, .JV_tree span, .JV_tree input, .treeview a, .t-tree-node, [data-kid], [data-knowledge-id]')]
    .filter(el=>el.textContent?.trim().length<100).slice(0,2000).map(el=>({tag:el.tagName,id:el.id,class:el.className,text:el.textContent.trim(),
       attrs:Object.fromEntries([...el.attributes].filter(a=>/^(data-|href$|title$|pk$|value$)/.test(a.name)).map(a=>[a.name,a.value])),
       ancestors:['解一元一次方程','有理数的加法','平行线的判定'].includes(el.textContent.trim())?
         [el.parentElement,el.parentElement?.parentElement,el.parentElement?.parentElement?.parentElement].filter(Boolean).map(p=>({tag:p.tagName,attrs:Object.fromEntries([...p.attributes].map(a=>[a.name,a.value])),head:p.outerHTML.slice(0,650)})):[]})));
  results.push({site:task.site,url:page.url(),controls});
  console.log(task.site,JSON.stringify(controls.slice(0,14)));
 }catch(error){results.push({site:task.site,error:String(error)});}
 await page.close();
}
await fs.writeFile(path.join(root,'data/benchmark_web_v0.2/knowledge/browser_tree_controls.json'),JSON.stringify(results,null,2));
await context.close();
