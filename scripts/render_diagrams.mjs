// Optional documentation tooling: Mermaid + Playwright, separate from runtime dependencies.
// node scripts/render_diagrams.mjs --modules /path/to/node_modules --browser /path/to/chromium
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';

const args = process.argv.slice(2);
const option = name => args.includes(name) ? args[args.indexOf(name) + 1] : undefined;
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const modules = option('--modules');
const require = createRequire(modules ? path.join(path.resolve(modules), '..', 'package.json') : import.meta.url);
const {chromium} = require('playwright');
const dist = path.dirname(require.resolve('mermaid'));
const directory = path.join(root, 'docs', 'diagrams');
const server = http.createServer(async (req, res) => {
  try {
    if (req.url === '/') {
      res.setHeader('Content-Type', 'text/html');
      res.end('<html><body style="margin:0;background:white"><div id="diagram"></div><script type="module">import mermaid from "/dist/mermaid.esm.min.mjs"; window.mermaid=mermaid;</script></body></html>');
      return;
    }
    if (!req.url.startsWith('/dist/')) { res.writeHead(404).end(); return; }
    const target = path.resolve(dist, decodeURIComponent(req.url.slice(6)));
    if (!target.startsWith(dist + path.sep)) { res.writeHead(403).end(); return; }
    res.setHeader('Content-Type', target.endsWith('.mjs') ? 'text/javascript' : 'application/octet-stream');
    res.end(await fs.readFile(target));
  } catch { res.writeHead(404).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
let browser;
try {
  browser = await chromium.launch({headless:true, executablePath:option('--browser')});
  const page = await browser.newPage({viewport:{width:1800,height:1200},deviceScaleFactor:2});
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await page.waitForFunction(() => window.mermaid);
  for (const name of ['architecture','query_flow','catalogue_flow','scaling']) {
    const source = await fs.readFile(path.join(directory, name+'.mmd'), 'utf8');
    const svg = await page.evaluate(async ({source,name}) => {
      window.mermaid.initialize({startOnLoad:false, theme:'base', securityLevel:'strict',
        themeVariables:{fontFamily:'Arial, sans-serif',fontSize:'17px',primaryColor:'#eff6ff',primaryTextColor:'#0f172a',lineColor:'#64748b'},
        flowchart:{htmlLabels:false,curve:'linear',useMaxWidth:false,nodeSpacing:35,rankSpacing:45},
        sequence:{useMaxWidth:false,wrap:true,width:160,messageMargin:28,actorMargin:35}});
      const {svg} = await window.mermaid.render('render_'+name, source.replace(/^\uFEFF/,''));
      document.getElementById('diagram').innerHTML=svg;
      return svg;
    },{source,name});
    await fs.writeFile(path.join(directory,name+'.svg'),svg);
    const bounds=await page.locator('#diagram svg').boundingBox();
    await page.setViewportSize({width:Math.ceil(bounds.width)+16,height:Math.ceil(bounds.height)+16});
    await page.locator('#diagram svg').screenshot({path:path.join(directory,name+'.png')});
    console.log(`${name}: ${Math.ceil(bounds.width)} x ${Math.ceil(bounds.height)} CSS pixels`);
  }
} finally {
  if (browser) await browser.close();
  await new Promise(resolve=>server.close(resolve));
}
