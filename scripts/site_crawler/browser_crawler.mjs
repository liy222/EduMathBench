/** Headed Playwright acquisition. Uses normal pages and a private login profile.
 * No password, cookie, token export or private endpoint discovery is performed.
 * Python performs normalization/validation using the same four parsers as HTTP.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline/promises';
import { spawnSync } from 'node:child_process';
import { chromium } from 'playwright';

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const option = (name, fallback) => argv.includes(name) ? argv[argv.indexOf(name) + 1] : fallback;
if (argv.includes('--help')) {
  console.log('node browser_crawler.mjs --config tasks.json --site all --limit 3 --pages 1 --out RUN_DIR [--login] [--cdp http://127.0.0.1:9222] [--python PYTHON_PATH]');
  process.exit(0);
}
const maxItems = Number(option('--limit', '3'));
const maxPages = Number(option('--pages', '1'));
if (!Number.isSafeInteger(maxItems) || maxItems < 1 || maxItems > 50 || !Number.isSafeInteger(maxPages) || maxPages < 1 || maxPages > 10) throw new Error('每站limit须为1–50，pages须为1–10。');
const configPath = path.resolve(option('--config', path.join(here, 'tasks.json')));
const cfg = JSON.parse(await fs.readFile(configPath, 'utf8'));
const selected = option('--site', 'all');
const tasks = cfg.tasks.filter(t => selected === 'all' || t.site === selected);
if (!tasks.length) throw new Error('未找到所选站点');
const runDir = path.resolve(option('--out', path.join(here, '../../data/site_crawl_runs', new Date().toISOString().replace(/[:.]/g, '-'))));
await fs.mkdir(runDir, {recursive: true});
const manifestPath = path.join(runDir, 'manifest.json');
try { await fs.access(manifestPath); throw new Error('输出目录已有manifest，请使用新的运行目录，避免覆盖。'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
await fs.mkdir(path.join(runDir, 'raw'), {recursive: true});
await fs.mkdir(path.join(runDir, 'screenshots'), {recursive: true});
const manifest = {format: 'edumath-browser-acquisition-v1', started_at: new Date().toISOString(), items: [], events: []};
const flush = () => fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2));
const consoleInput = createInterface({input: process.stdin, output: process.stdout});
let context, attachedBrowser;
if (option('--cdp', null)) {
  attachedBrowser = await chromium.connectOverCDP(option('--cdp'));
  context = attachedBrowser.contexts()[0];
  if (!context) throw new Error('调试连接没有浏览器上下文');
} else {
  // The user's ordinary Edge profile is deliberately never copied or unlocked.
  const profile = path.resolve(option('--profile-dir', path.join(here, '.local_browser_profile')));
  context = await chromium.launchPersistentContext(profile, {channel: 'msedge', headless: false, viewport: null});
}
const ownedPages = [];
const gate = /抱歉.{0,12}(?:未登录|尚未登录)|游客模式.{0,50}(?:登录|注册)|请完成验证|访问过于频繁|安全验证|(?:今日|免费).{0,20}(?:次数已用完|额度不足)/;
const log = (site, status, extra = {}) => {
  const event = {at: new Date().toISOString(), site, status, ...extra};
  manifest.events.push(event);
  console.log(`[${site}] ${status}`);
};
const rootSelector = site => site === 'tiku' ? '.q-detail' : site === 'jyeoo' ? 'li.QUES_LI, fieldset.quesborder' : 'li.QuestionView';
const visibleHtml = async locator => locator.evaluate(el => {
  const clone = el.cloneNode(true);
  const liveNodes = [...el.querySelectorAll('*')];
  const cloneNodes = [...clone.querySelectorAll('*')];
  // Remove hidden branches and executable markup from the evidence copy.
  for (let i = liveNodes.length - 1; i >= 0; --i) {
    const live = liveNodes[i], target = cloneNodes[i];
    const style = getComputedStyle(live);
    if (['SCRIPT', 'STYLE', 'INPUT', 'TEMPLATE'].includes(live.tagName) || style.display === 'none' || style.visibility === 'hidden') target.remove();
  }
  return clone.outerHTML;
});
async function settle(page, selector) {
  await page.waitForLoadState('domcontentloaded');
  await page.locator(selector).first().waitFor({state: 'visible', timeout: 20000});
  // Site filters arrive asynchronously after the initial server-rendered list.
  await page.waitForTimeout(1200);
}
async function loginIfNecessary(page, task, detail = false, returnUrl = task.url) {
  const text = await page.locator('body').innerText();
  const blocked = gate.test(text) || /passport|loginform|\/login(?:\?|$)/.test(page.url());
  if (!blocked) return true;
  log(task.site, 'login_or_verification_required', {url: page.url(), stage: detail ? 'detail' : 'list'});
  if (!argv.includes('--login')) return false;
  console.log(`${task.site}：请在刚打开的浏览器中自行登录/完成验证。程序不会输入账号密码。`);
  await consoleInput.question('完成后按回车继续，或Ctrl+C结束：');
  const again = await page.locator('body').innerText();
  if (gate.test(again) || /passport|loginform|\/login(?:\?|$)/.test(page.url())) return false;
  if (page.url() !== returnUrl) await page.goto(returnUrl, {waitUntil: 'domcontentloaded', timeout: 30000});
  return true;
}
async function saveItem(task, page, root, url, listing, index) {
  const markup = await visibleHtml(root);
  const nativeId = task.site === 'tiku'
    ? await root.locator('[id^="p"]').first().getAttribute('id')
    : url.split('/').pop().split('?')[0];
  const slug = nativeId.replace(/[^\w-]/g, '_').slice(0, 90);
  const rawPath = path.join(runDir, 'raw', `${task.site}_${index}_${slug}.html`);
  await fs.writeFile(rawPath, markup);
  const screenshotPath = path.join(runDir, 'screenshots', `${task.site}_${index}_${slug}.png`);
  await root.screenshot({path: screenshotPath});
  manifest.items.push({site: task.site, url, raw_path: rawPath, filters: task.filters, listing, collection_method: 'playwright_browser_crawler', screenshot_path: screenshotPath, sha256: createHash('sha256').update(markup).digest('hex')});
  log(task.site, 'question_saved', {native_id: nativeId, raw_path: rawPath});
  await flush();
}

try {
  for (const task of tasks) {
    const page = await context.newPage(); ownedPages.push(page);
    let count = 0;
    try {
      await page.goto(task.url, {waitUntil: 'domcontentloaded', timeout: 30000});
      if (!await loginIfNecessary(page, task)) { await flush(); continue; }
      await settle(page, rootSelector(task.site));
      const visited = new Set();
      for (let p = 0; p < maxPages && count < maxItems; p++) {
        const firstCardSignature = await page.locator(rootSelector(task.site)).first().innerText();
        const pageSignature = createHash('sha256').update(firstCardSignature).digest('hex');
        if (visited.has(pageSignature)) { log(task.site, 'pagination_cycle'); break; }
        visited.add(pageSignature);
        // Preserve the URL and selected UI controls so requested filters are auditable.
        const evidence = await page.evaluate(() => Array.from(document.querySelectorAll('a.active[data-param]')).map(el => ({text: el.textContent.trim(), parameter: el.getAttribute('data-param')})));
        log(task.site, 'list_opened', {url: page.url(), requested_filters: task.filters, selected_controls: evidence});
        const listHtml = await visibleHtml(page.locator(task.site === 'tiku' ? '#qlist-container' : task.site === 'jyeoo' ? '.ques-list' : '.question-list, #J_question_list').first()).catch(() => null);
        if (listHtml) await fs.writeFile(path.join(runDir, 'raw', `${task.site}_list_${p + 1}.html`), listHtml);
        if (task.site === 'tiku') {
          const cards = await page.locator('.q-detail').all();
          for (const card of cards) {
            if (count >= maxItems) break;
            if (await card.locator('img').count()) { log(task.site, 'input_image_deferred'); continue; }
            // Text answers are already visible; solution controls are not needed.
            await saveItem(task, page, card, page.url(), {url: page.url()}, ++count);
            await page.waitForTimeout(1500);
          }
        } else {
          const detailName = task.site === 'jyeoo' ? '解析' : task.site === '21cnjy' ? '详情' : '查看解析';
          const links = await page.getByRole('link', {name: detailName, exact: true}).all();
          const candidates = [];
          for (const link of links) {
            const item = await link.evaluate(el => {
              const card = el.closest('li');
              const origin = card?.querySelector('.ques-origin,.ques-source');
              return {href: el.href, text: card?.innerText ?? '', origin: origin?.textContent?.trim() ?? ''};
            });
            if (cfg.prefer_text && /如图|图中|图1|图2/.test(item.text)) continue;
            candidates.push(item);
          }
          for (const item of candidates) {
            if (count >= maxItems) break;
            if (new URL(item.href).origin !== new URL(task.url).origin) { log(task.site, 'external_detail_ignored'); continue; }
            const detail = await context.newPage(); ownedPages.push(detail);
            try {
              await detail.goto(item.href, {waitUntil: 'domcontentloaded', timeout: 30000});
              if (!await loginIfNecessary(detail, task, true, item.href)) break;
              await settle(detail, rootSelector(task.site));
              await saveItem(task, detail, detail.locator(rootSelector(task.site)).first(), item.href, {...item, url: page.url()}, ++count);
            } catch (error) { log(task.site, 'detail_failed', {url: item.href, error: String(error)}); }
            await detail.close();
            await page.waitForTimeout(1500);
          }
        }
        if (count >= maxItems || p + 1 >= maxPages) break;
        const next = page.getByRole('link', {name: task.site === 'tiku' ? '>' : '下一页', exact: true});
        if (!await next.count() || !await next.first().isVisible()) break;
        await next.first().click();
        await settle(page, rootSelector(task.site));
      }
      log(task.site, 'task_finished', {saved: count});
    } catch (error) { log(task.site, 'task_failed', {error: String(error), saved: count}); }
    await flush();
  }
} finally {
  manifest.finished_at = new Date().toISOString();
  await flush();
  consoleInput.close();
  for (const page of ownedPages) if (!page.isClosed()) await page.close().catch(() => {});
  if (!attachedBrowser) await context.close();
}
const python = option('--python', process.env.EDUMATH_PYTHON ?? 'python');
const result = spawnSync(python, [path.join(here, 'edumath_crawler.py'), 'import', manifestPath, '--out', path.join(runDir, 'normalized'), '--download-assets', '--automatic-only'], {stdio: 'inherit'});
if (result.error) { console.error(`原始采集已保存。规范化程序未运行：${result.error.message}`); process.exitCode = 1; }
else process.exitCode = result.status ?? 1;
