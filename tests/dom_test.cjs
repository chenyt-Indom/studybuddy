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
  check('侧边栏导航', navs.length === 9, navs.join(' / '));

  // 逐个视图渲染
  for (const [key, mustHave] of [
    ['dashboard', '学情看板'], ['review', '复习中心'], ['mistakes', '错题本'],
    ['insight', '洞察'], ['memory', '自动整理'], ['textbook', '教材'], ['profile', '学习档案'],
    ['settings', '选择供应商']
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
  // 等历史加载完（发送按钮从 disabled 变可用），否则会撞上渲染覆盖
  await waitFor(() => {
    const s = doc.querySelector('#send');
    return s && s.disabled === false;
  }, 15000);
  check('历史加载完成后输入框可用', doc.querySelector('#send').disabled === false);

  const inp = doc.querySelector('#inp');
  inp.value = '二次函数的顶点怎么求？我想看图理解';
  doc.querySelector('#send').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

  const gotReply = await waitFor(() => {
    const bots = doc.querySelectorAll('.msg.bot .bubble');
    const last = bots[bots.length - 1];
    return last && !last.querySelector('.typing') && last.querySelector('.ans') &&
      last.querySelector('.ans').textContent.length > 40;
  }, 60000);
  const bots = doc.querySelectorAll('.msg.bot');
  const lastBot = bots[bots.length - 1];
  const lastText = lastBot ? lastBot.querySelector('.ans').textContent : '';
  check('SSE 流式消息到达', gotReply, `${lastText.length} 字`);

  // 思维链折叠块
  const think = lastBot && lastBot.querySelector('.think');
  const thinkBody = lastBot && lastBot.querySelector('.think-body');
  check('存在思维链折叠块', !!(think && !think.hidden && thinkBody), 
        thinkBody ? `正文 ${thinkBody.textContent.length} 字` : '');
  if (think && thinkBody) {
    const wasHidden = thinkBody.hidden;
    think.querySelector('.think-head').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
    const toggled = thinkBody.hidden !== wasHidden;
    check('思维链可展开/收起', toggled,
          `点击前 hidden=${wasHidden}，点击后 hidden=${thinkBody.hidden}`);
    think.querySelector('.think-head').dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  }

  const ctxHtml = doc.querySelector('#ctx').textContent;
  check('右侧上下文面板更新', ctxHtml.includes('认知风格'), ctxHtml.slice(0, 40).replace(/\s+/g, ' '));

  // 图表 SVG 是否真的产出
  const dashLink = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'dashboard');
  dashLink.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const hasSvg = await waitFor(() => doc.querySelectorAll('#main svg').length >= 1, 9000);
  check('图表渲染为 SVG', hasSvg, `${doc.querySelectorAll('#main svg').length} 个`);

  // 记忆库页：开关 + 管理按钮 + 档案区
  const memLink = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'memory');
  memLink.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const memOk = await waitFor(() => doc.querySelector('#swExtract') && doc.querySelector('#mRun'), 9000);
  check('记忆库有对话记忆开关', memOk && !!doc.querySelector('#swExtract'));
  check('记忆库有自动整理开关', !!doc.querySelector('#swConsolidate'));
  check('记忆库有管理按钮(整理/编辑/导入/重置)',
        !!doc.querySelector('#mRun') && !!doc.querySelector('#mEdit') &&
        !!doc.querySelector('#mImport') && !!doc.querySelector('#mReset'));
  check('记忆库有档案区', !!doc.querySelector('#docs'));

  // 教材页：版本选择 + 最新核查
  const tbLink = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'textbook');
  tbLink.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  const tbOk = await waitFor(() => doc.querySelector('#tbEditions'), 12000);
  check('教材页有版本区', tbOk);
  const edLoaded = await waitFor(() =>
    doc.querySelector('#tbEditions').textContent.includes('人教A版'), 12000);
  const edHtml = doc.querySelector('#tbEditions').textContent;
  check('版本列表已渲染', edLoaded, edHtml.slice(0, 46).replace(/\s+/g, ' '));
  check('有当前教材与最新核查区',
        !!doc.querySelector('#tbCur') && !!doc.querySelector('#tbLatest'));
  await waitFor(() => doc.querySelector('#tbCheck'), 12000);
  check('有「检查是否最新」按钮', !!doc.querySelector('#tbCheck'));

  // 回到对话页再检查联网开关
  const backChat = Array.from(doc.querySelectorAll('.side nav a')).find(a => a.dataset.v === 'chat');
  backChat.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
  await waitFor(() => doc.querySelector('#webMode'), 9000);
  check('联网开关存在', !!doc.querySelector('#webMode'),
        doc.querySelector('#webMode') ? doc.querySelector('#webMode').value : '');

  const errs = window.__errs || [];
  check('无未捕获 JS 错误', errs.length === 0, errs.slice(0, 3).join(' | '));

  console.log('='.repeat(64));
  console.log(`通过 ${pass} 项，失败 ${fails.length} 项`);
  if (fails.length) { console.log('失败项:', fails); process.exit(1); }
  dom.window.close();
  process.exit(0);
})().catch(e => { console.error('测试崩溃:', e); process.exit(1); });
