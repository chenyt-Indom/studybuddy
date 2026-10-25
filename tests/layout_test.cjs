/* 布局回归测试：用真浏览器（Edge/Chrome 无头）量尺寸。
   jsdom 没有排版引擎，CSS 写崩了它照样"全绿"，所以这一层必须真跑浏览器。

   查的是这次踩过的坑：
   1. 整页被内容顶成上万像素高（对话区 height:auto + .msgs flex:1）
   2. 输入框被挤成一条 / 文字被裁掉（textarea width:100% 撑住最小宽度）
   3. 发送按钮掉到视口外（窄屏标题换行后高度算不准）
   4. 消息区出现横向滚动条（气泡 min-width:auto 被长内容顶宽）

   跑法：先起服务（start.bat），再
     NODE_PATH=<jsdom 的 node_modules 可省> node tests/layout_test.cjs
   找不到 Edge/Chrome 就跳过（不当作失败）。
*/
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const BASE = 'http://127.0.0.1:8787';
const PORT = 9361;
const CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
];
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let pass = 0;
const fails = [];
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  [PASS] ${name} ${extra}`); }
  else { fails.push(`${name} ${extra}`); console.log(`  [FAIL] ${name} ${extra}`); }
}

function findBrowser() {
  for (const p of CANDIDATES) { try { if (fs.existsSync(p)) return p; } catch (e) { } }
  return null;
}

(async () => {
  console.log('='.repeat(64));
  console.log('布局回归测试（真浏览器）');

  const browser = findBrowser();
  if (!browser) {
    console.log('  未找到 Edge / Chrome，跳过布局测试');
    process.exit(0);
  }

  // 先确认服务在跑
  try {
    const h = await fetch(BASE + '/api/health');
    if (!h.ok) throw new Error('health ' + h.status);
  } catch (e) {
    console.log(`  服务没起来（${BASE}），先运行 start.bat 再测`);
    process.exit(1);
  }

  // 用一个独立账号，别动 demo 的数据
  const uname = 'layout_' + (Date.now() % 1000000);
  const reg = await fetch(BASE + '/api/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: uname, password: '123456', nickname: '布局' })
  });
  const tok = (await reg.json()).token;

  const prof = path.join(os.tmpdir(), 'layout_' + Date.now());
  const child = spawn(browser, ['--headless=new', '--disable-gpu', '--no-first-run',
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, 'about:blank'],
    { stdio: 'ignore' });

  let target = null;
  for (let i = 0; i < 80; i++) {
    try {
      const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = l.find(x => x.type === 'page');
      if (target) break;
    } catch (e) { }
    await sleep(250);
  }
  if (!target) { console.log('  浏览器 CDP 没起来'); process.exit(1); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  let id = 0;
  const pend = new Map();
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) {
      const p = pend.get(m.id); pend.delete(m.id);
      m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
    }
  });
  await new Promise(r => ws.addEventListener('open', r));
  const send = (method, params = {}) => new Promise((res, rej) => {
    const mid = ++id;
    pend.set(mid, { resolve: res, reject: rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  const ev = async (e) => (await send('Runtime.evaluate',
    { expression: e, returnByValue: true, awaitPromise: true })).result.value;

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });  // 否则改完 CSS 还测旧样式

  await send('Emulation.setDeviceMetricsOverride',
    { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: BASE + '/' });
  await sleep(1200);
  await ev(`localStorage.setItem('sb_token', ${JSON.stringify(tok)});
    localStorage.setItem('sb_user', JSON.stringify({id:1,username:'layout',nickname:'布局'})); 1`);

  for (const [w, h] of [[1440, 900], [1280, 800], [1200, 674], [1100, 800], [1024, 768], [820, 760], [520, 820]]) {
    await send('Emulation.setDeviceMetricsOverride',
      { width: w, height: h, deviceScaleFactor: 1, mobile: w < 600 });
    await send('Page.navigate', { url: BASE + '/' });
    for (let i = 0; i < 60; i++) {
      if (await ev(`!!document.querySelector('#inp')`).catch(() => false)) break;
      await sleep(200);
    }
    await sleep(600);

    const m = await ev(`(() => {
      const de = document.documentElement;
      const ta = document.querySelector('#inp');
      const sendBtn = document.querySelector('#send');
      const msgs = document.querySelector('#msgs');
      const tb = ta ? ta.getBoundingClientRect() : null;
      const sb = sendBtn ? sendBtn.getBoundingClientRect() : null;
      const row = document.querySelector('.composer-row');
      const pick = document.querySelector('#pickImg');
      const pb = pick ? pick.getBoundingClientRect() : null;
      return {
        rowDisplay: row ? getComputedStyle(row).display : null,
        // 图片按钮 / 发送按钮 与输入框是否在同一行（用户看到的"变形"就是它们竖着叠起来了）
        sameRowPick: !!(pb && tb) && Math.abs((pb.top + pb.bottom) / 2 - (tb.top + tb.bottom) / 2) < 40,
        sameRowSend: !!(sb && tb) && Math.abs((sb.top + sb.bottom) / 2 - (tb.top + tb.bottom) / 2) < 40,
        docH: de.scrollHeight, viewH: innerHeight, docW: de.scrollWidth, viewW: de.clientWidth,
        taW: tb ? Math.round(tb.width) : 0,
        taClipped: ta ? ta.scrollHeight > ta.clientHeight + 1 : null,
        sendBottom: sb ? Math.round(sb.bottom) : null,
        msgsOverX: msgs ? msgs.scrollWidth - msgs.clientWidth : null,
      };
    })()`);

    const tag = `${w}x${h}`;
    check(`${tag} 页面不被内容顶高`, m.docH <= m.viewH + 2, `docH=${m.docH} viewH=${m.viewH}`);
    check(`${tag} 页面没有横向溢出`, m.docW <= m.viewW + 1, `docW=${m.docW} viewW=${m.viewW}`);
    check(`${tag} 发送按钮在视口内`, m.sendBottom !== null && m.sendBottom <= m.viewH + 1,
      `bottom=${m.sendBottom}`);
    check(`${tag} 输入框有可用宽度`, m.taW >= 200, `width=${m.taW}px`);
    check(`${tag} 输入框文字没被裁`, m.taClipped === false);
    check(`${tag} 消息区没有横向滚动`, Math.abs(m.msgsOverX || 0) <= 1, `over=${m.msgsOverX}`);
    check(`${tag} 输入区是横向一行`, m.rowDisplay === 'flex', `display=${m.rowDisplay}`);
    check(`${tag} 图片按钮与输入框同行`, m.sameRowPick === true);
    check(`${tag} 发送按钮与输入框同行`, m.sameRowSend === true);
  }

  try { child.kill(); } catch (e) { }
  console.log('='.repeat(64));
  console.log(`通过 ${pass} 项，失败 ${fails.length} 项`);
  if (fails.length) { console.log('失败项:', fails); process.exit(1); }
  console.log('全部通过');
  process.exit(0);
})().catch(e => { console.error('测试崩溃:', e); process.exit(1); });
