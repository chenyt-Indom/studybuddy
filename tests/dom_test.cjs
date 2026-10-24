/* 前端 DOM 冒烟测试：在 jsdom 里真跑一遍前端，验证页面能渲染、导航能切、消息能流式到达。 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const BASE = 'http://127.0.0.1:8787';
const ROOT = path.resolve(__dirname, '..');
const nodeFetch = globalThis.fetch;

let pass = 0;
const fails = [];
function check(name, cond, extra = '') {
  if (cond) { pass++; console.log(`  [PASS] ${name} ${extra}`); }
  else { fails.push(name); console.log(`  [FAIL] ${name} ${extra}`); }
}
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function waitFor(fn, timeout = 8000, step = 120) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (fn()) return true; } catch (e) { /* keep waiting */ }
    await sleep(step);
  }
  return false;
}

(async () => {
  console.log('='.repeat(64));
  console.log('前端 DOM 测试');

  // 准备一个已存在的账号 token
  let tok;
  let r = await nodeFetch(BASE + '/api/auth/register', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'dom_user', password: '123456', nickname: 'DOM测试' })
  });
  if (r.status === 400) {
    r = await nodeFetch(BASE + '/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'dom_user', password: '123456' })
    });
  }
  tok = (await r.json()).token;

  // 给这个测试账号造点数据，否则看板全是空状态、图表无从渲染
  const auth = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok };
  const kpOf = { 1: 'math.function_basic', 2: 'math.set', 3: 'math.linear_function',
                 4: 'math.inequality', 5: 'math.factorization', 6: 'math.quadratic_function',
                 7: 'math.trigonometry', 8: 'math.sequence', 9: 'math.derivative' };
  for (const [name, score, date] of [['9月月考', 88, '2026-09-18'], ['10月月考', 95, '2026-10-20']]) {
    const qs = [];
    for (let q = 1; q <= 15; q++) {
      qs.push({ q_no: q, kp_code: kpOf[((q - 1) % 9) + 1], is_correct: q <= 7 || q === 9 });
    }
    await nodeFetch(BASE + '/api/grades', {
      method: 'POST', headers: auth,
      body: JSON.stringify({ subject: 'math', exam_name: name, score, full_score: 150, exam_date: date, questions: qs })
    });
  }
  await nodeFetch(BASE + '/api/mistakes', {
    method: 'POST', headers: auth,
    body: JSON.stringify({ subject: 'math', content: '二次函数顶点题，配方法算错',
                           kp_code: 'math.quadratic_function', error_type: 'calculation' })
  });

  const html = fs.readFileSync(path.join(ROOT, 'frontend/index.html'), 'utf8');
  const dom = new JSDOM(html, {
    url: BASE + '/',
    runScripts: 'dangerously',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = (input, init) => nodeFetch(new URL(input, BASE), init);
      window.TextDecoder = TextDecoder;
      window.TextEncoder = TextEncoder;
      window.Element.prototype.scrollIntoView = function () {};
      const errs = [];
      window.__errs = errs;
      window.addEventListener('error', (e) => errs.push(String(e.message)));
      window.localStorage.setItem('sb_token', tok);
      window.localStorage.setItem('sb_user', JSON.stringify({ id: 1, username: 'dom_user', nickname: 'DOM测试' }));
    }
  });

  const { window } = dom;
  const doc = window.document;

  // 手动注入脚本，保证顺序
  window.eval(fs.readFileSync(path.join(ROOT, 'frontend/charts.js'), 'utf8'));
  window.eval(fs.readFileSync(path.join(ROOT, 'frontend/app.js'), 'utf8'));

  check('charts 挂载', typeof window.Charts === 'object' && typeof window.Charts.lineChart === 'function');

  // 等 boot() 完成 → 应该渲染出侧边栏
  const booted = await waitFor(() => doc.querySelector('.side nav a'));
  check('进入主界面（boot 成功）', booted);

  const navs = Array.from(doc.querySelectorAll('.side nav a')).map(a => a.textContent.trim());
  check('侧边栏导航', navs.length === 7, navs.join(' / '));

  // 逐个视图渲染
  for (const [key, mustHave] of [
    ['dashboard', '学情看板'], ['review', '复习中心'], ['mistakes', '错题本'],
    ['insight', '洞察'], ['profile', '学习档案'], ['settings', '选择供应商']
  ]) {
    const link = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === key);
    link.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const ok = await waitFor(() => doc.querySelector('#main').textContent.includes(mustHave), 9000);
    check(`视图渲染 ${key}`, ok);
  }

  // 回到对话并发一条消息，验证 SSE 流式
  const chatLink = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'chat');
  chatLink.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await waitFor(() => doc.querySelector('#inp'));

  const inp = doc.querySelector('#inp');
  inp.value = '二次函数的顶点怎么求？我想看图理解';
  doc.querySelector('#send').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

  const gotReply = await waitFor(() => {
    const bots = doc.querySelectorAll('.msg.bot .bubble');
    const last = bots[bots.length - 1];
    return last && last.textContent.length > 40 && !last.querySelector('.typing');
  }, 20000);
  const bots = doc.querySelectorAll('.msg.bot .bubble');
  const lastText = bots.length ? bots[bots.length - 1].textContent : '';
  check('SSE 流式消息到达', gotReply, `${lastText.length} 字`);

  const ctxHtml = doc.querySelector('#ctx').textContent;
  check('右侧上下文面板更新', ctxHtml.includes('认知风格'), ctxHtml.slice(0, 40).replace(/\s+/g, ' '));

  // 图表 SVG 是否真的产出
  const dashLink = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'dashboard');
  dashLink.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const hasSvg = await waitFor(() => doc.querySelectorAll('#main svg').length >= 1, 9000);
  check('图表渲染为 SVG', hasSvg, `${doc.querySelectorAll('#main svg').length} 个`);

  const errs = window.__errs || [];
  check('无未捕获 JS 错误', errs.length === 0, errs.slice(0, 3).join(' | '));

  console.log('='.repeat(64));
  console.log(`通过 ${pass} 项，失败 ${fails.length} 项`);
  if (fails.length) { console.log('失败项:', fails); process.exit(1); }
  dom.window.close();
  process.exit(0);
})().catch(e => { console.error('测试崩溃:', e); process.exit(1); });
