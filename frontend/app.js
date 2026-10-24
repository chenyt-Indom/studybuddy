/* StudyBuddy 前端 —— 无构建单页应用。
   为什么不用 Vue + Vite：PC 端先行验证，零 npm、零 CDN，双击能跑；
   等三条主线跑通再迁 Vue 也不迟（后端接口不用改）。 */

const SUBJECTS = [
  ['math', '数学'], ['physics', '物理'], ['chemistry', '化学'],
  ['biology', '生物'], ['chinese', '语文'], ['english', '英语']
];
const SUBJ_NAME = Object.fromEntries(SUBJECTS);
const GRADE_OPTIONS = {
  primary: [['primary_1', '一年级'], ['primary_2', '二年级'], ['primary_3', '三年级'],
            ['primary_4', '四年级'], ['primary_5', '五年级'], ['primary_6', '六年级']],
  junior: [['junior_1', '初一'], ['junior_2', '初二'], ['junior_3', '初三']],
  senior: [['senior_1', '高一'], ['senior_2', '高二'], ['senior_3', '高三']],
  college: [['college_1', '大一'], ['college_2', '大二'], ['college_3', '大三'], ['college_4', '大四']]
};
const ERROR_TYPES = {
  concept: '概念不清', calculation: '计算失误', careless: '粗心',
  method: '方法不当', transfer: '迁移失败', timeout: '时间不够'
};
const NAV = [
  ['chat', '学科对话', '💬'],
  ['dashboard', '学情看板', '📊'],
  ['review', '复习中心', '🔁'],
  ['mistakes', '错题本', '📕'],
  ['insight', '洞察', '💡'],
  ['memory', '记忆库', '🧠'],
  ['profile', '学习档案', '👤'],
  ['settings', '设置', '⚙️']
];

const state = {
  token: localStorage.getItem('sb_token') || '',
  user: JSON.parse(localStorage.getItem('sb_user') || 'null'),
  view: 'chat',
  subject: 'math',
  sysConfig: null,
  chatMeta: null,
  useWeb: localStorage.getItem('sb_useweb') || 'auto',
  reviewSel: null
};

/* ---------------- 基础工具 ---------------- */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const h = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));

let toastTimer = null;
function toast(msg, isErr = false) {
  const t = $('#toast');
  t.textContent = msg;
  t.className = 'on' + (isErr ? ' err' : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.className = ''; }, 2800);
}

/* ---------------- API ---------------- */
async function req(path, opt = {}) {
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opt.headers || {});
  if (state.token) headers.Authorization = 'Bearer ' + state.token;
  const res = await fetch(path, Object.assign({}, opt, { headers }));
  let body = null;
  const txt = await res.text();
  try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = { raw: txt }; }
  if (!res.ok) {
    const msg = (body && (body.detail || body.message)) || `HTTP ${res.status}`;
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
  }
  return body;
}
const api = {
  get: (p) => req(p),
  post: (p, d) => req(p, { method: 'POST', body: d ? JSON.stringify(d) : undefined }),
  put: (p, d) => req(p, { method: 'PUT', body: JSON.stringify(d || {}) }),
  del: (p) => req(p, { method: 'DELETE' })
};

/* ---------------- 极简 Markdown 渲染 ---------------- */
function md(src) {
  if (!src) return '';
  let s = h(src);
  const blocks = [];
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<pre><code>${code.replace(/\n$/, '')}</code></pre>`);
    return `\u0000B${blocks.length - 1}\u0000`;
  });
  s = s.replace(/^### (.*)$/gm, '<h3>$1</h3>')
       .replace(/^## (.*)$/gm, '<h2>$1</h2>')
       .replace(/^# (.*)$/gm, '<h1>$1</h1>')
       .replace(/^&gt; (.*)$/gm, '<blockquote>$1</blockquote>')
       .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
       .replace(/`([^`]+)`/g, '<code>$1</code>')
       .replace(/\n{2,}/g, '</p><p>')
       .replace(/\n/g, '<br>');
  s = s.replace(/(?:^|<br>)[-*] (.*?)(?=<br>|$)/g, '<br>• $1');
  s = '<p>' + s + '</p>';
  s = s.replace(/<p>\s*<\/p>/g, '');
  s = s.replace(/\u0000B(\d+)\u0000/g, (_, i) => blocks[+i]);
  return s;
}

/* ---------------- 登录 ---------------- */
function renderAuth(mode = 'login') {
  document.getElementById('app').innerHTML = `
  <div class="auth-wrap"><div class="auth-card">
    <h1>StudyBuddy</h1>
    <p class="sub">智能学习助手 · 越用越懂你</p>
    <div class="tabs">
      <button class="${mode === 'login' ? 'on' : ''}" data-m="login">登录</button>
      <button class="${mode === 'register' ? 'on' : ''}" data-m="register">注册</button>
    </div>
    <div class="field"><label>用户名</label><input id="u" type="text" placeholder="2~32 个字符" /></div>
    <div class="field"><label>密码</label><input id="p" type="password" placeholder="至少 6 位" /></div>
    ${mode === 'register' ? '<div class="field"><label>昵称（可选）</label><input id="n" type="text" /></div>' : ''}
    <div style="height:8px"></div>
    <button class="btn primary" id="go" style="width:100%;padding:11px">
      ${mode === 'login' ? '登录' : '注册并登录'}
    </button>
    <p class="hint" style="margin-top:16px;text-align:center">
      本地单机运行，数据只存在你自己的电脑上
    </p>
  </div></div>`;

  $$('.auth-card .tabs button').forEach(b => b.onclick = () => renderAuth(b.dataset.m));
  const doAuth = async () => {
    const username = $('#u').value.trim(), password = $('#p').value;
    if (!username || !password) return toast('用户名和密码都要填', true);
    try {
      const path = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
      const nickname = mode === 'register' ? ($('#n') ? $('#n').value.trim() : '') : '';
      const res = await api.post(path, { username, password, nickname });
      state.token = res.token; state.user = res.user;
      localStorage.setItem('sb_token', res.token);
      localStorage.setItem('sb_user', JSON.stringify(res.user));
      renderApp();
    } catch (e) { toast(e.message, true); }
  };
  $('#go').onclick = doAuth;
  $('#p').onkeydown = (e) => { if (e.key === 'Enter') doAuth(); };
}

/* ---------------- 外壳 ---------------- */
function renderApp() {
  document.getElementById('app').innerHTML = `
  <div class="app">
    <aside class="side">
      <div class="logo">StudyBuddy <small>v0.1</small></div>
      <nav>${NAV.map(([k, n, ico]) =>
        `<a data-v="${k}" class="${state.view === k ? 'on' : ''}"><span class="ico">${ico}</span>${n}</a>`
      ).join('')}</nav>
      <div class="foot">
        <div id="modeLine">检测中…</div>
        <div style="margin-top:6px">${h(state.user ? state.user.nickname : '')}</div>
      </div>
    </aside>
    <main class="main" id="main"></main>
  </div>`;

  $$('.side nav a').forEach(a => a.onclick = () => {
    state.view = a.dataset.v;
    $$('.side nav a').forEach(x => x.classList.toggle('on', x.dataset.v === state.view));
    route();
  });
  refreshMode();
  route();
}

async function refreshMode() {
  try {
    state.sysConfig = await api.get('/api/system/config');
    const live = state.sysConfig.mode === 'teleai';
    const line = $('#modeLine');
    if (line) line.innerHTML = `<span class="mode-dot ${live ? 'mode-live' : 'mode-mock'}"></span>`
      + (live ? '星辰模型已接入' : '离线演示模式');
  } catch (e) { /* ignore */ }
}

function route() {
  const m = $('#main');
  m.innerHTML = '';
  ({ chat: viewChat, dashboard: viewDashboard, review: viewReview, mistakes: viewMistakes,
     insight: viewInsight, memory: viewMemory, profile: viewProfile,
     settings: viewSettings }[state.view] || viewChat)(m);
}

/* ---------------- 视图：对话 ---------------- */
async function viewChat(root) {
  root.innerHTML = `
  <div class="page-h">
    <div><h2>学科对话</h2>
      <div class="desc">每个科目一条独立对话，永久保留 · 右侧是本次回答实际用到的画像与记忆</div></div>
    <div class="row" style="gap:8px">
      <select id="webMode" style="width:auto" title="联网搜索（DeepSeek 官方 Search，5 元/1000 次）">
        <option value="auto">联网：自动判断</option>
        <option value="on">联网：强制开启</option>
        <option value="off">联网：关闭</option>
      </select>
      <button class="btn" id="refreshStyle">重算我的认知风格</button>
    </div>
  </div>
  <div class="chat-layout">
    <div class="chat-main">
      <div class="subjects">
        ${SUBJECTS.map(([k, n]) => `<button data-s="${k}" class="${state.subject === k ? 'on' : ''}">${n}</button>`).join('')}
      </div>
      <div class="msgs" id="msgs"><div class="empty">选择一个科目，开始提问</div></div>
      <div class="composer">
        <textarea id="inp" placeholder="例如：二次函数的顶点怎么求？我上次配方法错了…（Enter 发送，Shift+Enter 换行）"></textarea>
        <button class="btn primary" id="send">发送</button>
      </div>
    </div>
    <aside class="ctx" id="ctx">
      <h4>本次回答的上下文</h4>
      <p class="hint">发一条消息后，这里会显示系统实际注入了哪些信息。</p>
    </aside>
  </div>`;

  $$('.subjects button').forEach(b => b.onclick = () => {
    state.subject = b.dataset.s;
    $$('.subjects button').forEach(x => x.classList.toggle('on', x.dataset.s === state.subject));
    const mb = $('#msgs');
    if (mb) delete mb.dataset.live;  // 切科目要重新渲染历史
    loadHistory();
  });
  $('#refreshStyle').onclick = async () => {
    try {
      const r = await api.post('/api/profile/refresh-style');
      toast(`认知风格：${r.style.primary || '样本不足'}（置信度 ${(r.style.confidence * 100).toFixed(0)}%）`);
    } catch (e) { toast(e.message, true); }
  };
  const wm = $('#webMode');
  wm.value = state.useWeb;
  wm.onchange = () => { state.useWeb = wm.value; localStorage.setItem('sb_useweb', wm.value); };
  const inp = $('#inp');
  inp.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };
  $('#send').onclick = sendMessage;
  // 历史没加载完之前禁用输入：否则用户手快先发，历史回来会把新消息覆盖掉
  inp.disabled = true;
  $('#send').disabled = true;
  await loadHistory();
  if ($('#inp')) {
    $('#inp').disabled = false;
    $('#send').disabled = false;
    $('#inp').focus();
  }
}

async function loadHistory() {
  const box = $('#msgs');
  if (!box) return;
  box.innerHTML = '<div class="empty">加载中…</div>';
  try {
    const convs = await api.get('/api/chat/conversations');
    // 加载期间用户已经发过消息 → 放弃这次渲染，别把新消息覆盖掉
    if (box.dataset.live === '1' || !$('#msgs')) return;
    const conv = convs.find(c => c.subject === state.subject);
    if (!conv) {
      box.innerHTML = `<div class="empty">「${SUBJ_NAME[state.subject]}」还没有对话<br>直接在下面提问就会自动建立</div>`;
      return;
    }
    const msgs = await api.get('/api/chat/messages?conversation_id=' + conv.id);
    if (!msgs.length) {
      box.innerHTML = `<div class="empty">「${SUBJ_NAME[state.subject]}」还没有对话<br>直接在下面提问就会自动建立</div>`;
      return;
    }
    box.innerHTML = msgs.map(historyBubble).join('');
    // 思维链原文用 textContent 注入，避免转义/HTML 注入
    const bots = $$('.msg.bot', box);
    const datas = msgs.filter(m => m.role !== 'user');
    bots.forEach((n, i) => {
      const pre = $('.think-body', n);
      if (pre && datas[i] && datas[i].reasoning) pre.textContent = datas[i].reasoning;
    });
    hydrateThink(box);
    box.scrollTop = box.scrollHeight;
  } catch (e) {
    box.innerHTML = `<div class="empty">读取失败：${h(e.message)}</div>`;
  }
}

function bubble(role, content) {
  const isUser = role === 'user';
  return `<div class="msg ${isUser ? 'user' : 'bot'}">
    <div class="av">${isUser ? '我' : 'SB'}</div>
    <div class="bubble">${isUser ? h(content).replace(/\n/g, '<br>') : md(content)}</div>
  </div>`;
}

/* 历史消息：带思维链折叠 + 来源列表 */
function historyBubble(m) {
  if (m.role === 'user') return bubble('user', m.content);
  const src = (m.sources && m.sources.length)
    ? `<div class="sources"><div class="src-title">参考来源</div>${m.sources.map((s, i) =>
        `<a class="src" href="${h(s.url)}" target="_blank" rel="noopener">
           <span class="idx">${i + 1}</span>
           <span class="st">${h(s.title || s.url)}</span>
           <span class="sm">${h(s.site || '')}${s.date ? ' · ' + h(s.date) : ''}</span>
         </a>`).join('')}</div>`
    : '';
  return `<div class="msg bot">
    <div class="av">SB</div>
    <div class="bubble">
      ${m.reasoning ? `<div class="think">
        <button class="think-head" type="button">
          <span class="ico">🧠</span> 深度思考过程 · <span class="len">${m.reasoning.length} 字</span>
          <span class="chev">展开</span>
        </button>
        <pre class="think-body" hidden></pre>
      </div>` : ''}
      <div class="ans">${md(m.content)}</div>
      ${src}
    </div>
  </div>`;
}

/* 历史里的思维链需要 post-DOM 注入文本，避免 HTML 转义踩坑 */
function hydrateThink(root) {
  $$('.think', root).forEach(t => {
    const body = $('.think-body', t);
    const head = $('.think-head', t);
    const chev = $('.chev', t);
    if (!body || !head) return;
    // 思维链原文存在 data 里会有转义问题，改用从 ans 之外的结构推断：
    // 这里只绑交互，文本由调用方通过 setThinkText 注入
    head.onclick = () => {
      const open = body.hidden;
      body.hidden = !open;
      chev.textContent = open ? '收起' : '展开';
    };
  });
}

/* 创建一个流式机器人气泡，返回各区域句柄 */
function createBotBubble(box) {
  const id = 'b' + Date.now() + Math.floor(Math.random() * 1000);
  box.insertAdjacentHTML('beforeend', `
    <div class="msg bot" id="${id}">
      <div class="av">SB</div>
      <div class="bubble">
        <div class="srcline" hidden></div>
        <div class="think" hidden>
          <button class="think-head" type="button">
            <span class="ico">🧠</span> 深度思考过程 · <span class="len">0 字</span>
            <span class="chev">展开</span>
          </button>
          <pre class="think-body" hidden></pre>
        </div>
        <div class="ans"><span class="typing"><i></i><i></i><i></i></span></div>
        <div class="sources" hidden></div>
      </div>
    </div>`);
  const root = document.getElementById(id);
  const think = $('.think', root), body = $('.think-body', root);
  const chev = $('.chev', root);
  const handle = {
    root,
    ans: $('.ans', root),
    think, body, chev,
    len: $('.len', root),
    srcline: $('.srcline', root),
    sources: $('.sources', root),
    reasoning: '',
    answer: '',
    sourcesData: []
  };
  $('.think-head', root).onclick = () => {
    const open = body.hidden;
    body.hidden = !open;
    chev.textContent = open ? '收起' : '展开';
    if (open) body.scrollTop = body.scrollHeight;
  };
  return handle;
}

function renderSources(el, list) {
  if (!list || !list.length) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<div class="src-title">参考来源（${list.length}）</div>` +
    list.map((s, i) => `<a class="src" href="${h(s.url)}" target="_blank" rel="noopener">
      <span class="idx">${i + 1}</span>
      <span class="st">${h(s.title || s.url)}</span>
      <span class="sm">${h(s.site || '')}${s.date ? ' · ' + h(s.date) : ''}</span>
    </a>`).join('');
}

async function sendMessage() {
  const inp = $('#inp'), box = $('#msgs'), btn = $('#send');
  const text = inp.value.trim();
  if (!text) return;
  inp.value = ''; btn.disabled = true;

  if (box.querySelector('.empty')) box.innerHTML = '';
  box.dataset.live = '1';   // 标记：这里已经有实时消息，别再被历史渲染覆盖
  box.insertAdjacentHTML('beforeend', bubble('user', text));
  const hd = createBotBubble(box);
  box.scrollTop = box.scrollHeight;

  const useWeb = state.useWeb === 'auto' ? null : (state.useWeb === 'on');
  const keepBottom = () => { box.scrollTop = box.scrollHeight; };

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + state.token },
      body: JSON.stringify({ subject: state.subject, message: text, use_web: useWeb })
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);

    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        let evt;
        try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }

        if (evt.type === 'meta') {
          state.chatMeta = evt;
          renderCtx(evt);

        } else if (evt.type === 'status') {
          hd.srcline.hidden = false;
          hd.srcline.innerHTML = `<span class="spin"></span> ${h(evt.text)}`;
          keepBottom();

        } else if (evt.type === 'search') {
          hd.srcline.hidden = false;
          hd.sourcesData = evt.results || [];
          if (evt.used) {
            hd.srcline.innerHTML = `<span class="pill ok">🌐 ${h(evt.message)}</span>
              <span class="hint">查询：${h(evt.query)}</span>`;
            renderSources(hd.sources, hd.sourcesData);
          } else {
            hd.srcline.innerHTML = `<span class="pill warn">未联网</span>
              <span class="hint">${h(evt.message || '')}</span>`;
          }
          keepBottom();

        } else if (evt.type === 'reasoning') {
          hd.think.hidden = false;
          hd.reasoning += evt.text || '';
          hd.len.textContent = `${hd.reasoning.length} 字`;
          hd.body.textContent = hd.reasoning;
          if (!hd.body.hidden) hd.body.scrollTop = hd.body.scrollHeight;
          if (!hd.answer) {
            hd.ans.innerHTML = `<span class="hint">深度思考中…（点上方「展开」可看推理过程）</span>`;
          }
          keepBottom();

        } else if (evt.type === 'delta') {
          hd.answer += evt.text;
          hd.ans.innerHTML = md(hd.answer);
          keepBottom();

        } else if (evt.type === 'error') {
          hd.ans.innerHTML = `<span style="color:#b91c1c">${h(evt.message)}</span>`;

        } else if (evt.type === 'done') {
          if (!hd.answer) hd.ans.innerHTML = '<span class="hint">（没有内容返回）</span>';
          if (evt.truncated) {
            hd.ans.insertAdjacentHTML('beforeend',
              `<div class="hint" style="color:#b45309;margin-top:8px">
                ⚠️ 本次回复异常短，可能被截断。可以在设置里换更省事的问法，或分多次提问。</div>`);
          }
        }
      }
    }
  } catch (e) {
    hd.ans.innerHTML = `<span style="color:#b91c1c">请求失败：${h(e.message)}</span>`;
  } finally {
    btn.disabled = false;
    inp.focus();
  }
}

function renderCtx(meta) {
  const box = $('#ctx');
  if (!box) return;
  const styleCn = { visual: '视觉型', verbal: '语言型', kinesthetic: '动手型', logical: '逻辑型' };
  const sec = (title, inner) => `<div class="sec"><h5>${title}</h5>${inner}</div>`;

  let html = `<h4>本次回答的上下文</h4>
    <p class="hint">同样的问题，不同学生会得到完全不同的 Prompt —— 这就是专精化。</p>`;

  html += sec('认知风格', `<div class="item"><b>${styleCn[meta.style] || '样本不足'}</b>
    ${meta.style ? '（按此风格调整讲解方式）' : '（再多聊几轮就能推断出来）'}</div>`);

  if (meta.weak_points && meta.weak_points.length) {
    html += sec('薄弱知识点', meta.weak_points.map(w =>
      `<div class="item"><b>${h(w.name)}</b> 掌握度 ${(w.mastery * 100).toFixed(0)}%</div>`).join(''));
  } else {
    html += sec('薄弱知识点', '<div class="item" style="color:#8d97a8">暂无记录</div>');
  }

  if (meta.cross_subject) {
    const c = meta.cross_subject;
    html += sec('跨科关联', `<div class="item">与 <b>${h(c.related_subject_cn)}</b> 的
      「<b>${h(c.related_kp)}</b>」相关<br>
      <span class="hint">该处掌握度 ${(c.related_mastery * 100).toFixed(0)}% ·
      ${h(c.relation_cn)}</span></div>`);
  }

  const memList = meta.memories || [];
  html += sec('召回的长期记忆',
    meta.memories_used > 0
      ? `<div class="item">全局 <b>${meta.memories_global || 0}</b> 条 · 本科目 <b>${meta.memories_subject || 0}</b> 条</div>`
        + memList.map(m => `<div class="item">· <span class="pill" style="font-size:10.5px">${
            m.scope === 'global' ? '全局' : '科目'}</span> ${h(m.content)}</div>`).join('')
      : '<div class="item" style="color:#8d97a8">本次没有命中相关记忆</div>');

  html += sec('激活的模式洞察',
    meta.patterns_used > 0
      ? `<div class="item">本次带入 <b>${meta.patterns_used}</b> 条洞察</div>`
      : '<div class="item" style="color:#8d97a8">数据还不够，先去录成绩/错题</div>');

  box.innerHTML = html;
}

/* ---------------- 视图：看板 ---------------- */
async function viewDashboard(root) {
  root.innerHTML = `<div class="page-h"><div><h2>学情看板</h2>
    <div class="desc">数据全部来自你自己的录入 · 不联网、不上传</div></div>
    <button class="btn primary" id="runMine">重新分析</button></div>
    <div class="grid g4" id="stats"></div>
    <div style="height:16px"></div>
    <div class="grid g2">
      <div class="card"><h3>成绩趋势 <span class="tag">统一换算百分制</span></h3><div id="trend"></div></div>
      <div class="card"><h3>各科掌握度 <span class="tag">雷达</span></h3><div id="radar"></div></div>
    </div>
    <div style="height:16px"></div>
    <div class="card"><h3>最新洞察</h3><div id="insights"></div></div>`;

  $('#runMine').onclick = async () => {
    try {
      const r = await api.post('/api/insight/run');
      toast(`分析完成，命中 ${r.found} 条洞察`);
      viewDashboard(root);
    } catch (e) { toast(e.message, true); }
  };

  try {
    const [rs, trend, radar, ins] = await Promise.all([
      api.get('/api/review/stats'), api.get('/api/grades/trend'),
      api.get('/api/cross/radar'), api.get('/api/insight')
    ]);
    $('#stats').innerHTML = [
      ['待复习', rs.due, '个知识点今天该复习'],
      ['已跟踪知识点', rs.tracked, '进入 SM-2 调度'],
      ['平均记忆强度', (rs.avg_strength * 100).toFixed(0) + '%', '越低越紧迫'],
      ['洞察', ins.insights.length, '条已识别模式']
    ].map(([t, v, s]) => `<div class="card">
        <div class="hint">${t}</div>
        <div class="stat" style="margin:6px 0 2px">${v}<small>${s}</small></div>
      </div>`).join('');

    $('#trend').innerHTML = Charts.lineChart(trend.series,
      { yMin: 0, yMax: 100, emptyText: '还没有成绩记录 —— 去「错题本」旁边的接口录一条' });
    $('#radar').innerHTML = Charts.radarChart(radar.radar);

    $('#insights').innerHTML = ins.insights.length
      ? ins.insights.slice(0, 4).map(insightCard).join('')
      : '<div class="empty">还没有洞察。录入一次带逐题记录的考试成绩，或攒够 10 道错题，系统就会自动分析。</div>';
  } catch (e) {
    toast(e.message, true);
  }
}

function insightCard(i) {
  return `<div class="insight ${h(i.severity)}">
    <div class="t">${h(i.title)} ${i.subject ? `<span class="pill">${h(SUBJ_NAME[i.subject] || i.subject)}</span>` : ''}</div>
    <div class="d">${md(i.detail)}</div>
    ${i.action ? `<div class="a">👉 ${md(i.action)}</div>` : ''}
  </div>`;
}

/* ---------------- 视图：复习 ---------------- */
async function viewReview(root) {
  root.innerHTML = `<div class="page-h"><div><h2>复习中心</h2>
    <div class="desc">SM-2 动态间隔 · 按「快忘了 × 重要 × 本来就弱」排序</div></div></div>
    <div class="grid g2">
      <div class="card"><h3>今日队列 <span class="tag" id="qCount"></span></h3>
        <div id="queue"></div></div>
      <div class="card"><h3>遗忘曲线 <span class="tag" id="curveTitle">选一个知识点</span></h3>
        <div id="curve"><div class="empty">点左边队列里的知识点查看</div></div>
        <div id="cards"></div>
      </div>
    </div>`;

  try {
    const r = await api.get('/api/review/queue');
    if (!$('#queue')) return;
    const items = r.items || [];
    $('#qCount').textContent = `${items.length} 个`;
    if (!items.length) {
      $('#queue').innerHTML = `<div class="empty">今天没有到期的复习<br>
        去对话里问几个问题，或在错题本录几道错题，系统会自动排程</div>`;
      return;
    }
    $('#queue').innerHTML = items.map((it, idx) => `
      <div class="q-item" data-kp="${h(it.kp_code)}">
        <div style="flex:1;min-width:0">
          <div class="name">${h(it.kp_name)}
            <span class="pill">${h(SUBJ_NAME[it.subject] || it.subject)}</span></div>
          <div class="meta">记忆强度 ${(it.strength * 100).toFixed(0)}% ·
            优先级 ${it.priority} · 已过 ${it.overdue_days} 天 ·
            EF ${it.ef} · 间隔 ${it.interval} 天</div>
          <div class="bar" style="margin-top:6px;max-width:240px">
            <i style="width:${Math.max(3, it.strength * 100)}%;
              background:${it.strength < 0.4 ? '#dc2626' : it.strength < 0.7 ? '#f59e0b' : '#16a34a'}"></i>
          </div>
        </div>
        <div class="quality">
          ${[0, 1, 2, 3, 4, 5].map(q => `<button data-q="${q}" title="${q}分">${q}</button>`).join('')}
        </div>
      </div>`).join('');

    $$('#queue .q-item').forEach(row => {
      const kp = row.dataset.kp;
      row.querySelector('.name').style.cursor = 'pointer';
      row.querySelector('.name').onclick = () => showCurve(kp);
      row.querySelectorAll('.quality button').forEach(b => b.onclick = async (ev) => {
        ev.stopPropagation();
        try {
          const res = await api.post(`/api/review/${encodeURIComponent(kp)}/grade`,
            { quality: Number(b.dataset.q) });
          toast(`已记录：${b.dataset.q} 分 → 下次 ${res.interval_days} 天后复习（EF ${res.after.ef}）`);
          viewReview(root);
        } catch (e) { toast(e.message, true); }
      });
    });
    if (items[0]) showCurve(items[0].kp_code);
  } catch (e) { toast(e.message, true); }
}

async function showCurve(kp) {
  try {
    const [c, st] = await Promise.all([
      api.get('/api/review/curve?kp_code=' + encodeURIComponent(kp)),
      api.get('/api/review/state?kp_code=' + encodeURIComponent(kp))
    ]);
    if (!$('#curve') || !$('#curveTitle')) return;
    $('#curveTitle').textContent = (c.kp_name || '') + ` · EF ${c.ef || '-'}`;
    $('#curve').innerHTML = Charts.curveChart(c.points);
    $('#cards').innerHTML = `
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
        <button class="btn sm" id="genCards">生成复习卡片（3 张）</button>
        <span class="hint">用星辰模型针对你的薄弱点出题</span>
      </div>
      <div id="cardBox"></div>`;
    $('#genCards').onclick = async () => {
      $('#cardBox').innerHTML = '<div class="empty">生成中…</div>';
      try {
        const r = await api.get('/api/review/cards?kp_code=' + encodeURIComponent(kp));
        $('#cardBox').innerHTML = (r.cards || []).map((c, i) => `
          <div class="insight" style="margin-top:10px">
            <div class="t">卡片 ${i + 1}：${h(c.q)}</div>
            <div class="d">答：${h(c.a)}</div>
            <div class="a">提示：${h(c.hint)}</div>
          </div>`).join('');
      } catch (e) { $('#cardBox').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
    };
  } catch (e) { toast(e.message, true); }
}

/* ---------------- 视图：错题本 ---------------- */
async function viewMistakes(root) {
  root.innerHTML = `<div class="page-h"><div><h2>错题本</h2>
    <div class="desc">错因六分类是 P3 洞察的原料 · 录入时自动归因知识点</div></div></div>
    <div class="grid g2">
      <div class="card">
        <h3>录入一道错题</h3>
        <div class="field"><label>科目</label>
          <select id="mSubj">${SUBJECTS.map(([k, n]) => `<option value="${k}" ${k === state.subject ? 'selected' : ''}>${n}</option>`).join('')}</select>
        </div>
        <div style="height:10px"></div>
        <div class="field"><label>题目 / 你的错误描述</label>
          <textarea id="mContent" placeholder="把题干贴进来，或写「二次函数顶点那题，我用配方法算错了」"></textarea>
        </div>
        <div style="height:10px"></div>
        <div class="grid g2">
          <div class="field"><label>错因（六选一）</label>
            <select id="mErr"><option value="">先不填</option>
              ${Object.entries(ERROR_TYPES).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
            </select></div>
          <div class="field"><label>难度层级</label>
            <select id="mTier"><option value="">先不填</option>
              <option value="basic">基础题</option><option value="medium">中档题</option>
              <option value="hard">压轴题</option></select></div>
        </div>
        <div style="height:14px"></div>
        <div class="row">
          <button class="btn primary" id="addM">保存（自动归因知识点）</button>
          <button class="btn" id="previewCand">看候选知识点</button>
        </div>
        <div id="candBox"></div>
      </div>
      <div class="card"><h3>错因画像</h3><div id="errChart"></div>
        <div id="errInsight"></div></div>
    </div>
    <div style="height:16px"></div>
    <div class="card"><h3>错题列表</h3><div id="mList"></div></div>`;

  const load = async () => {
    const subj = $('#mSubj').value;
    try {
      const [list, stats] = await Promise.all([
        api.get('/api/mistakes?subject=' + subj),
        api.get('/api/mistakes/stats?subject=' + subj)
      ]);
      const a = stats.analysis || {};
      if (a.distribution_cn && Object.keys(a.distribution_cn).length) {
        $('#errChart').innerHTML = Charts.barChart(
          Object.entries(a.distribution_cn).map(([k, v]) => ({ label: k, value: v, color: '#8b5cf6' })), {});
      } else {
        $('#errChart').innerHTML = `<div class="empty">${h(a.message || '还没有足够错题做归因分析')}</div>`;
      }
      $('#errInsight').innerHTML = a.insight ? insightCard(a.insight) : '';

      $('#mList').innerHTML = list.length ? `<table class="tbl">
        <thead><tr><th>科目</th><th>内容</th><th>知识点</th><th>错因</th><th>时间</th></tr></thead>
        <tbody>${list.map(m => `<tr>
          <td>${h(SUBJ_NAME[m.subject] || m.subject)}</td>
          <td>${h(m.content).slice(0, 90)}</td>
          <td>${h(m.kp_name || '—')}</td>
          <td>${m.error_type_cn ? `<span class="pill warn">${h(m.error_type_cn)}</span>` : '—'}</td>
          <td class="hint">${h((m.created_at || '').slice(0, 10))}</td>
        </tr>`).join('')}</tbody></table>`
        : '<div class="empty">还没有错题</div>';
    } catch (e) { toast(e.message, true); }
  };

  $('#mSubj').onchange = load;
  $('#previewCand').onclick = async () => {
    try {
      const r = await api.get(`/api/mistakes/candidates?subject=${$('#mSubj').value}&text=${encodeURIComponent($('#mContent').value)}`);
      $('#candBox').innerHTML = `<div style="margin-top:12px"><h5 class="hint">候选知识点（模型只能从这里选，防止编造）</h5>
        <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:6px">
        ${(r.candidates || []).map(c => `<span class="pill">${h(c.name)}</span>`).join('')}</div></div>`;
    } catch (e) { toast(e.message, true); }
  };
  $('#addM').onclick = async () => {
    const content = $('#mContent').value.trim();
    if (!content) return toast('先写点内容', true);
    try {
      const r = await api.post('/api/mistakes', {
        subject: $('#mSubj').value, content,
        error_type: $('#mErr').value || null, tier: $('#mTier').value || null
      });
      toast(`已保存，归因到「${r.kp_name || '未匹配'}」（${r.attributed_by === 'auto' ? '自动' : '手动'}）`);
      $('#mContent').value = '';
      load();
    } catch (e) { toast(e.message, true); }
  };
  await load();
}

/* ---------------- 视图：洞察 ---------------- */
async function viewInsight(root) {
  root.innerHTML = `<div class="page-h"><div><h2>洞察</h2>
    <div class="desc">L3 模式洞察：从数据里推断出你自己都没意识到的问题</div></div>
    <button class="btn primary" id="run">立即分析</button></div>
    <div class="grid g2">
      <div class="card"><h3>题型分层</h3><div id="tier"></div></div>
      <div class="card"><h3>知识断层</h3><div id="gaps"></div></div>
    </div>
    <div style="height:16px"></div>
    <div class="card"><h3>全部洞察</h3><div id="list"></div></div>`;

  const load = async () => {
    try {
      const [ins, detail] = await Promise.all([
        api.get('/api/insight'), api.get('/api/insight/detail?subject=' + state.subject)
      ]);
      $('#list').innerHTML = ins.insights.length
        ? ins.insights.map(insightCard).join('')
        : '<div class="empty">还没有洞察。先录一次带逐题对错的成绩。</div>';

      const t = (detail.tiers || {});
      if (t.insufficient) {
        $('#tier').innerHTML = `<div class="empty">${h(t.message)}</div>`;
      } else if (t.tiers) {
        const items = Object.entries(t.tiers).map(([k, v]) => ({
          label: k, value: v.accuracy, text: `${(v.accuracy * 100).toFixed(0)}% (${v.count}题)`,
          color: v.accuracy < 0.5 ? '#dc2626' : v.accuracy < 0.75 ? '#f59e0b' : '#16a34a'
        }));
        $('#tier').innerHTML = Charts.barChart(items, { max: 1 });
      } else {
        $('#tier').innerHTML = '<div class="empty">暂无数据</div>';
      }

      const gaps = detail.gaps || [];
      $('#gaps').innerHTML = gaps.length ? gaps.map(g => insightCard(g.insight)).join('')
        : '<div class="empty">没有发现「前置也没掌握」的断层</div>';
    } catch (e) { toast(e.message, true); }
  };

  $('#run').onclick = async () => {
    try {
      const r = await api.post('/api/insight/run');
      toast(`分析完成，命中 ${r.found} 条`);
      load();
    } catch (e) { toast(e.message, true); }
  };
  await load();
}

/* ---------------- 视图：档案 ---------------- */
async function viewProfile(root) {
  root.innerHTML = `<div class="page-h"><div><h2>学习档案</h2>
    <div class="desc">四维画像：学业基础 / 认知风格 / 学习习惯 / 心理状态</div></div>
    <button class="btn" id="showPrompt">看我的 Prompt 长什么样</button></div>
    <div class="grid g2">
      <div class="card"><h3>基础信息</h3>
        <div class="grid g2">
          <div class="field"><label>学段</label><select id="pStage">
            <option value="primary">小学</option><option value="junior">初中</option>
            <option value="senior">高中</option><option value="college">大学</option>
          </select></div>
          <div class="field"><label>年级</label><select id="pGrade"></select></div>
          <div class="field"><label>目标专业/方向</label><input id="pMajor" type="text" placeholder="如：人工智能技术应用" /></div>
          <div class="field"><label>目标分</label><input id="pScore" type="number" placeholder="如：600" /></div>
        </div>
        <div style="height:14px"></div>
        <button class="btn primary" id="saveP">保存</button>
      </div>
      <div class="card"><h3>认知风格 <span class="tag">从对话行为推断，不是自己填的</span></h3>
        <div id="styleChart"></div>
        <div class="hint" id="styleTip" style="margin-top:8px"></div>
      </div>
    </div>
    <div style="height:16px"></div>
    <div class="grid g2">
      <div class="card"><h3>心理状态</h3><div id="psy"></div></div>
      <div class="card"><h3>薄弱知识点</h3><div id="weak"></div></div>
    </div>
    <div style="height:16px"></div>
    <div class="card"><h3>长期记忆库 <span class="tag">写记忆是异步的，不会拖慢对话</span></h3>
      <div id="mem"></div></div>
    <div id="promptBox"></div>`;

  // 事件先绑，避免 await 期间用户切换视图后元素已不存在
  $('#showPrompt').onclick = async () => {
    try {
      const r = await api.get('/api/profile/prompt-preview?subject=' + state.subject);
      const box = $('#promptBox');
      if (!box) return;
      box.innerHTML = `<div class="card" style="margin-top:16px">
        <h3>你的辅导 Prompt（${h(SUBJ_NAME[r.subject] || r.subject)}）</h3>
        <p class="hint">这是实际发给星辰大模型的 system prompt。不同学生拿到的完全不同。</p>
        <pre class="mono" style="white-space:pre-wrap;background:#0f1730;color:#dbe3f5;
          padding:16px;border-radius:10px;line-height:1.75;max-height:420px;overflow:auto">${h(r.system_prompt)}</pre>
      </div>`;
      box.scrollIntoView({ behavior: 'smooth' });
    } catch (e) { toast(e.message, true); }
  };

  try {
    const r = await api.get('/api/profile/overview');
    if (!$('#pStage')) return;  // 视图已被切走
    const p = r.profile;

    $('#pStage').value = p.stage || 'senior';
    const fillGrades = () => {
      const list = GRADE_OPTIONS[$('#pStage').value] || [];
      $('#pGrade').innerHTML = list.map(([k, n]) =>
        `<option value="${k}" ${k === p.grade ? 'selected' : ''}>${n}</option>`).join('');
    };
    fillGrades();
    $('#pStage').onchange = () => { fillGrades(); };
    $('#pMajor').value = p.target_major || '';
    $('#pScore').value = p.target_score || '';

    $('#saveP').onclick = async () => {
      try {
        await api.put('/api/profile', {
          stage: $('#pStage').value, grade: $('#pGrade').value,
          target_major: $('#pMajor').value.trim() || null,
          target_score: $('#pScore').value ? Number($('#pScore').value) : null
        });
        toast('已保存');
      } catch (e) { toast(e.message, true); }
    };

    const styles = p.style_scores || {};
    const styleCn = { visual: '视觉型', verbal: '语言型', kinesthetic: '动手型', logical: '逻辑型' };
    if (Object.keys(styles).length && Object.values(styles).some(v => v > 0)) {
      $('#styleChart').innerHTML = Charts.barChart(
        Object.entries(styles).map(([k, v]) => ({ label: styleCn[k] || k, value: v, color: '#3b5bfd' })), {});
      const n = r.style_samples || 0;
      $('#styleTip').innerHTML = `主风格：<b>${styleCn[p.primary_style] || '—'}</b>，`
        + `置信度 ${(p.style_confidence * 100).toFixed(0)}%`
        + `<br>基于 ${n} 轮你的提问推断${n < 8 ? '（样本还少，多聊几轮会更准）' : ''}`;
    } else {
      $('#styleChart').innerHTML = `<div class="empty">还没有足够的对话样本<br>去「学科对话」多聊几轮</div>`;
    }

    const psyItem = (label, v, color) => `
      <div style="margin-bottom:12px">
        <div class="row" style="justify-content:space-between">
          <span class="hint">${label}</span><span class="hint">${(v * 100).toFixed(0)}%</span></div>
        <div class="bar" style="margin-top:5px"><i style="width:${v * 100}%;background:${color}"></i></div>
      </div>`;
    $('#psy').innerHTML = psyItem('信心水平', p.confidence_level, '#16a34a')
      + psyItem('焦虑水平', p.anxiety_level, '#dc2626')
      + psyItem('动机强度', p.motivation, '#3b5bfd')
      + `<div class="hint">从最近对话的情绪词推断。信心低于 40% 时，AI 会自动切换成鼓励式语气。</div>`;

    $('#weak').innerHTML = r.weak_points.length
      ? r.weak_points.map(w => `<div class="item" style="display:flex;justify-content:space-between;
          padding:7px 0;border-bottom:1px dashed #e6eaf2;font-size:13px">
          <span>${h(w.name)} <span class="pill">${h(SUBJ_NAME[w.subject] || w.subject)}</span></span>
          <b>${(w.mastery * 100).toFixed(0)}%</b></div>`).join('')
      : '<div class="empty">还没有掌握度数据</div>';

    // 记忆概览：详细管理移到「记忆库」页
    const ms = await api.get('/api/memory/stats');
    const rate = ms.accuracy_rate === null ? '尚未判定'
      : `${(ms.accuracy_rate * 100).toFixed(0)}%（对 ${ms.correct} / 错 ${ms.wrong}）`;
    $('#mem').innerHTML = `<div class="grid g3" style="margin-bottom:14px">
        <div><div class="hint">记忆总数</div>
          <div class="stat" style="font-size:20px">${ms.total}</div></div>
        <div><div class="hint">全局 / 科目</div>
          <div class="stat" style="font-size:20px">${ms.global}<small> / ${ms.subject}</small></div></div>
        <div><div class="hint">你的判定准确率</div>
          <div class="stat" style="font-size:20px">${rate}</div></div>
      </div>
      <div class="row">
        <button class="btn primary" id="goMemory">去记忆库查看 / 核查每一条</button>
        <span class="hint">能看到依据原话，也能判「准确 / 不准确」</span>
      </div>`;
    const gm = $('#goMemory');
    if (gm) gm.onclick = () => {
      state.view = 'memory';
      $$('.side nav a').forEach(x => x.classList.toggle('on', x.dataset.v === 'memory'));
      route();
    };

  } catch (e) { toast(e.message, true); }
}

/* ---------------- 视图：记忆库 ---------------- */
const MEM_STATE = { scope: 'all', subject: '', accuracy: '', q: '', editing: false };

async function viewMemory(root) {
  root.innerHTML = `
  <div class="page-h">
    <div><h2>记忆库</h2>
      <div class="desc">两层：档案综述（给人看）+ 原子记忆（用于召回和核查）· 数据只存在你的设备上</div></div>
    <div class="row" style="gap:8px">
      <button class="btn" id="mPreview">预览会注入什么</button>
    </div>
  </div>

  <div class="card" style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
    <div style="flex:1">
      <div style="font-weight:600;font-size:14px">对话记忆</div>
      <div class="hint" style="margin-top:4px">记住对话中的重要信息，让后续回答更贴合你。</div>
    </div>
    <label class="switch"><input type="checkbox" id="swExtract"><i></i></label>
  </div>

  <div class="card" style="display:flex;align-items:center;gap:16px;margin-bottom:16px">
    <div style="flex:1">
      <div style="font-weight:600;font-size:14px">自动整理</div>
      <div class="hint" style="margin-top:4px">每晚自动合并重复、更新过时记忆，并重写分节档案。数据仅保存在你的设备上。</div>
    </div>
    <label class="switch"><input type="checkbox" id="swConsolidate"><i></i></label>
  </div>

  <div class="card" style="margin-bottom:16px">
    <div class="row" style="margin-bottom:10px">
      <h3 style="margin:0">管理记忆</h3>
      <div class="spacer"></div>
      <button class="btn" id="mRun">立即整理</button>
      <button class="btn" id="mEdit">编辑</button>
      <button class="btn" id="mImport">导入</button>
      <button class="btn" id="mReset" style="color:#b91c1c;border-color:#f3c6c6">重置</button>
    </div>
    <div class="hint" id="lastInfo">每晚自动整理更新，可随时查看和编辑。</div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h3>记忆档案 <span class="tag">按主题合成，模型用它把握整体</span></h3>
    <div id="docs"></div>
    <div class="row" style="margin-top:10px">
      <button class="btn sm" id="addDoc">+ 新增分节</button>
      <span class="hint" id="docHint"></span>
    </div>
  </div>

  <div class="card">
    <h3>原子记忆 <span class="tag">用于召回与逐条核查</span></h3>
    <div class="grid g4" id="mStats" style="margin-bottom:14px"></div>
    <div class="row" style="flex-wrap:wrap;gap:8px;margin-bottom:14px">
      <div class="row" style="gap:4px" id="mScopeTabs">
        <button class="btn sm" data-s="all">全部</button>
        <button class="btn sm" data-s="global">全局</button>
        <button class="btn sm" data-s="subject">分科目</button>
      </div>
      <select id="mSubject" style="width:auto">
        <option value="">所有科目</option>
        ${SUBJECTS.map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}
      </select>
      <select id="mAccuracy" style="width:auto">
        <option value="">所有判定</option>
        <option value="unverified">未判定</option>
        <option value="correct">我判定：准确</option>
        <option value="wrong">我判定：不准确</option>
      </select>
      <input id="mQ" type="text" placeholder="搜索内容…" style="width:160px" />
      <div class="spacer"></div>
      <button class="btn sm ghost" id="mClean" style="color:#b91c1c">清理所有「不准确」</button>
    </div>
    <div id="mList"></div>
  </div>

  <div id="mDialog"></div>`;

  // ============ 开关 ============
  const loadMeta = async () => {
    try {
      const m = await api.get('/api/memory/meta');
      if (!$('#swExtract')) return;
      $('#swExtract').checked = m.auto_extract;
      $('#swConsolidate').checked = m.auto_consolidate;
      $('#lastInfo').innerHTML = m.last_consolidated_at
        ? `上次整理：${h(m.last_consolidated_at.replace('T', ' ').slice(0, 16))}`
          + ` · 累计整理 ${m.consolidate_count} 次`
          + (m.last_summary ? `<br><span style="color:#8d97a8">${h(m.last_summary)}</span>` : '')
          + '<br>每晚自动整理更新，可随时查看和编辑。'
        : '还没整理过。点「立即整理」现在跑一次，或等今晚自动整理。';
    } catch (e) { toast(e.message, true); }
  };

  $('#swExtract').onchange = async () => {
    try {
      await api.post('/api/memory/meta', { auto_extract: $('#swExtract').checked });
      toast($('#swExtract').checked ? '已开启对话记忆' : '已关闭对话记忆');
    } catch (e) { toast(e.message, true); }
  };
  $('#swConsolidate').onchange = async () => {
    try {
      await api.post('/api/memory/meta', { auto_consolidate: $('#swConsolidate').checked });
      toast($('#swConsolidate').checked ? '已开启自动整理' : '已关闭自动整理');
    } catch (e) { toast(e.message, true); }
  };

  // ============ 统计 ============
  const renderStats = (s) => {
    let rate, note;
    if (s.accuracy_rate === null) {
      rate = '<span class="hint" style="font-size:15px">尚未判定</span>';
      note = '点下面「准确/不准确」开始核查';
    } else if (s.judged < 3) {
      rate = `<span>${(s.accuracy_rate * 100).toFixed(0)}%</span>`;
      note = `样本 ${s.judged} 条，参考价值有限`;
    } else {
      const c = s.accuracy_rate >= 0.8 ? '#16a34a' : s.accuracy_rate >= 0.6 ? '#f59e0b' : '#dc2626';
      rate = `<span style="color:${c}">${(s.accuracy_rate * 100).toFixed(0)}%</span>`;
      note = `对 ${s.correct} / 错 ${s.wrong}`;
    }
    $('#mStats').innerHTML = `
      <div><div class="hint">有效记忆</div>
        <div class="stat" style="font-size:20px">${s.total}<small>全局 ${s.global} · 科目 ${s.subject}</small></div></div>
      <div><div class="hint">你判定过</div>
        <div class="stat" style="font-size:20px">${s.judged}<small>未判定 ${s.unverified}</small></div></div>
      <div><div class="hint">准确率</div>
        <div class="stat" style="font-size:20px">${rate}<small>${note}</small></div></div>
      <div><div class="hint">已归档</div>
        <div class="stat" style="font-size:20px">${s.superseded || 0}<small>被新事实取代</small></div></div>`;
  };

  // ============ 档案（综述） ============
  const renderDocs = (docs) => {
    if (!docs.length) {
      $('#docs').innerHTML = `<div class="empty">还没有档案。聊几轮后点「立即整理」，系统会把记忆合成一份分节档案。<br>
        也可以点下面「+ 新增分节」自己写。</div>`;
      return;
    }
    $('#docs').innerHTML = docs.map(d => `
      <div class="doc" data-id="${d.id}" data-section="${h(d.section)}">
        <div class="doc-head">
          <span class="doc-title">${h(d.section)}</span>
          <span class="pill" style="font-size:10.5px">v${d.version}</span>
          ${d.user_edited ? '<span class="pill ok" style="font-size:10.5px">你手改过</span>' : ''}
          <div class="spacer"></div>
          <button class="btn sm ghost" data-act="ed">编辑</button>
          <button class="btn sm ghost" data-act="del" style="color:#b91c1c">删</button>
        </div>
        <div class="doc-body">${h(d.content).replace(/\n/g, '<br>')}</div>
      </div>`).join('');

    $$('#docs .doc').forEach(el => {
      const id = el.dataset.id;
      const sec = el.dataset.section;
      el.querySelector('[data-act="ed"]').onclick = () => {
        if (el.querySelector('textarea')) return;
        const body = el.querySelector('.doc-body');
        const raw = body.innerHTML.replace(/<br>/g, '\n').replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&quot;/g, '"');
        body.innerHTML = `<textarea style="min-height:140px">${h(raw)}</textarea>
          <div class="row" style="margin-top:8px">
            <button class="btn sm primary" data-a="save">保存</button>
            <button class="btn sm ghost" data-a="cancel">取消</button>
            <span class="hint">手改后，自动整理不会再覆盖这一节</span>
          </div>`;
        body.querySelector('[data-a="save"]').onclick = async () => {
          try {
            await api.put(`/api/memory/docs/${id}`, { content: body.querySelector('textarea').value });
            toast('已保存');
            loadDocs();
          } catch (e) { toast(e.message, true); }
        };
        body.querySelector('[data-a="cancel"]').onclick = () => loadDocs();
      };
      el.querySelector('[data-act="del"]').onclick = async () => {
        if (!confirm(`删除分节「${sec}」？`)) return;
        try { await api.del(`/api/memory/docs/${id}`); loadDocs(); }
        catch (e) { toast(e.message, true); }
      };
    });
  };

  const loadDocs = async () => {
    try {
      const r = await api.get('/api/memory/docs');
      if (!$('#docs')) return;
      renderDocs(r.docs || []);
      $('#docHint').textContent = r.docs && r.docs.length
        ? `共 ${r.docs.length} 节 · 只有标了「你手改过」的不会被自动覆盖`
        : '';
    } catch (e) { toast(e.message, true); }
  };

  // ============ 原子记忆 ============
  const loadList = async () => {
    const p = new URLSearchParams();
    if (MEM_STATE.scope !== 'all') p.set('scope', MEM_STATE.scope);
    if (MEM_STATE.subject) p.set('subject', MEM_STATE.subject);
    if (MEM_STATE.accuracy) p.set('accuracy', MEM_STATE.accuracy);
    if (MEM_STATE.q) p.set('q', MEM_STATE.q);
    try {
      const [st, r] = await Promise.all([
        api.get('/api/memory/stats'),
        api.get('/api/memory?' + p.toString())
      ]);
      if (!$('#mList')) return;
      renderStats(st);
      renderList(r.items || []);
    } catch (e) { toast(e.message, true); }
  };

  const renderList = (items) => {
    if (!items.length) {
      $('#mList').innerHTML = `<div class="empty">这里还没有原子记忆<br>
        去「学科对话」聊几轮会自动提取，或点上面的「+ 新增分节」手写档案</div>`;
      return;
    }
    $('#mList').innerHTML = items.map(m => `
      <div class="mem ${h(m.accuracy)}" data-id="${m.id}" data-pinned="${m.pinned ? 1 : 0}">
        <div class="mem-head">
          <span class="pill ${m.scope === 'global' ? 'brand' : ''}">${m.scope === 'global' ? '全局' : h(m.subject_cn || '科目')}</span>
          <span class="pill">${h(m.type_cn)}</span>
          ${m.pinned ? '<span class="pill warn">置顶</span>' : ''}
          ${m.accuracy === 'correct' ? '<span class="pill ok">你判定：准确</span>' : ''}
          ${m.accuracy === 'wrong' ? '<span class="pill bad">你判定：不准确</span>' : ''}
          <span class="mem-meta">置信 ${(m.confidence * 100).toFixed(0)}% · 权重 ${m.weight} · 命中 ${m.hits}</span>
          <div class="spacer"></div>
          <button class="btn sm" data-act="ok">准确</button>
          <button class="btn sm" data-act="no">不准确</button>
          <button class="btn sm ghost" data-act="pin">${m.pinned ? '取消置顶' : '置顶'}</button>
          <button class="btn sm ghost" data-act="del" style="color:#b91c1c">删</button>
        </div>
        <div class="mem-body">${h(m.content)}</div>
        ${m.evidence ? `<div class="mem-ev">依据原话：「${h(m.evidence)}」</div>`
          : '<div class="mem-ev" style="color:#b45309">⚠️ 这条没有依据片段，建议核实</div>'}
      </div>`).join('');

    $$('#mList .mem').forEach(el => {
      const id = el.dataset.id;
      el.querySelector('[data-act="ok"]').onclick = () => verify(id, 'correct');
      el.querySelector('[data-act="no"]').onclick = () => verify(id, 'wrong');
      el.querySelector('[data-act="pin"]').onclick = () => patch(id, { pinned: el.dataset.pinned !== '1' });
      el.querySelector('[data-act="del"]').onclick = async () => {
        if (!confirm('删除这条记忆？')) return;
        try { await api.del(`/api/memory/${id}`); toast('已删除'); loadList(); }
        catch (e) { toast(e.message, true); }
      };
    });
  };

  const verify = async (id, accuracy) => {
    try {
      await api.post(`/api/memory/${id}/verify`, { accuracy });
      toast(accuracy === 'correct' ? '已标为准确' : '已标为不准确（不再使用）');
      loadList();
    } catch (e) { toast(e.message, true); }
  };
  const patch = async (id, body) => {
    try { await api.put(`/api/memory/${id}`, body); loadList(); }
    catch (e) { toast(e.message, true); }
  };

  // ============ 管理按钮 ============
  $('#mRun').onclick = async () => {
    const btn = $('#mRun');
    btn.disabled = true; btn.textContent = '整理中…';
    try {
      const r = await api.post('/api/memory/consolidate');
      toast(r.message || '整理完成');
      if (r.skipped_user_edited && r.skipped_user_edited.length) {
        toast(`保留了 ${r.skipped_user_edited.length} 节你手改过的内容`);
      }
      await Promise.all([loadMeta(), loadDocs(), loadList()]);
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = '立即整理'; }
  };

  $('#mReset').onclick = async () => {
    if (!confirm('重置会清空所有原子记忆和档案，且无法恢复。确定？')) return;
    if (!confirm('再确认一次：真的要全部清空吗？')) return;
    try {
      const r = await api.post('/api/memory/reset?scope=all');
      toast(`已清空：原子记忆 ${r.deleted_memories} 条、档案 ${r.deleted_docs} 节`);
      await Promise.all([loadMeta(), loadDocs(), loadList()]);
    } catch (e) { toast(e.message, true); }
  };

  $('#mEdit').onclick = () => {
    const first = $('#docs .doc [data-act="ed"]');
    if (!first) return toast('先有档案才能编辑', true);
    $$('#docs .doc [data-act="ed"]').forEach(b => {
      if (!b.closest('.doc').querySelector('textarea')) b.click();
    });
    toast('已进入编辑模式，改完点各节的「保存」');
  };

  $('#mImport').onclick = () => {
    $('#mDialog').innerHTML = `<div class="card" style="margin-top:16px">
      <h3>导入档案</h3>
      <p class="hint">把现成的一段自我介绍 / 学习情况贴进来。导入的内容不会被自动整理改写。</p>
      <div class="field"><label>分节名称</label>
        <input id="impSec" type="text" value="导入的档案" /></div>
      <div style="height:10px"></div>
      <div class="field"><label>内容</label>
        <textarea id="impText" style="min-height:180px" placeholder="粘贴你的学习背景、目标、习惯……"></textarea></div>
      <div style="height:14px"></div>
      <div class="row"><button class="btn primary" id="impGo">导入</button>
        <button class="btn ghost" id="impCancel">取消</button></div>
    </div>`;
    $('#impCancel').onclick = () => { $('#mDialog').innerHTML = ''; };
    $('#impGo').onclick = async () => {
      const text = $('#impText').value.trim();
      if (!text) return toast('内容为空', true);
      try {
        await api.post('/api/memory/import', { text, section: $('#impSec').value.trim() || '导入的档案' });
        $('#mDialog').innerHTML = '';
        toast('已导入');
        loadDocs();
      } catch (e) { toast(e.message, true); }
    };
  };

  $('#addDoc').onclick = () => {
    $('#mDialog').innerHTML = `<div class="card" style="margin-top:16px">
      <h3>新增分节</h3>
      <div class="field"><label>分节名称</label>
        <input id="ndSec" type="text" placeholder="例如：我的弱项、作息安排" /></div>
      <div style="height:10px"></div>
      <div class="field"><label>内容</label>
        <textarea id="ndText" style="min-height:120px"></textarea></div>
      <div style="height:14px"></div>
      <div class="row"><button class="btn primary" id="ndGo">添加</button>
        <button class="btn ghost" id="ndCancel">取消</button></div>
    </div>`;
    $('#ndCancel').onclick = () => { $('#mDialog').innerHTML = ''; };
    $('#ndGo').onclick = async () => {
      const sec = $('#ndSec').value.trim(), content = $('#ndText').value.trim();
      if (!sec || !content) return toast('名称和内容都要填', true);
      try {
        await api.post('/api/memory/docs', { section: sec, content });
        $('#mDialog').innerHTML = '';
        toast('已添加');
        loadDocs();
      } catch (e) { toast(e.message, true); }
    };
  };

  // ============ 预览 / 清理 / 筛选 ============
  $('#mPreview').onclick = async () => {
    const subj = $('#mSubject').value || state.subject;
    const q = $('#mQ').value.trim() || '二次函数怎么求';
    try {
      const r = await api.get(`/api/memory/preview?subject=${encodeURIComponent(subj)}&query=${encodeURIComponent(q)}`);
      const box = (list) => list.length
        ? list.map(m => `<div class="mem-ev" style="margin:4px 0">· [${h(m.type_cn)}] ${h(m.content)}</div>`).join('')
        : '<div class="hint">（无）</div>';
      $('#mDialog').innerHTML = `<div class="card" style="margin-top:16px">
        <h3>这次对话会注入 ${r.count} 条原子记忆</h3>
        <p class="hint">模拟问题：「${h(r.query)}」 · 科目：${h(SUBJ_NAME[r.subject] || r.subject)}　
          （另外还会注入档案综述与全局记忆）</p>
        <div style="height:10px"></div>
        <h5 class="hint">全局记忆（${r.global.length}）</h5>${box(r.global)}
        <div style="height:10px"></div>
        <h5 class="hint">科目记忆（${r.subject_items.length}）</h5>${box(r.subject_items)}
        <div class="a" style="margin-top:12px;color:#5a6577">${h(r.note)}</div>
      </div>`;
    } catch (e) { toast(e.message, true); }
  };

  $('#mClean').onclick = async () => {
    if (!confirm('将删除所有你判定为「不准确」的记忆，确定？')) return;
    try {
      const r = await api.post('/api/memory/cleanup');
      toast(`已清理 ${r.deleted} 条`);
      loadList();
    } catch (e) { toast(e.message, true); }
  };

  $$('#mScopeTabs .btn').forEach(b => {
    if (b.dataset.s === MEM_STATE.scope) b.classList.add('primary');
    b.onclick = () => {
      MEM_STATE.scope = b.dataset.s;
      $$('#mScopeTabs .btn').forEach(x => x.classList.toggle('primary', x.dataset.s === MEM_STATE.scope));
      loadList();
    };
  });
  $('#mSubject').value = MEM_STATE.subject;
  $('#mSubject').onchange = () => { MEM_STATE.subject = $('#mSubject').value; loadList(); };
  $('#mAccuracy').value = MEM_STATE.accuracy;
  $('#mAccuracy').onchange = () => { MEM_STATE.accuracy = $('#mAccuracy').value; loadList(); };
  $('#mQ').value = MEM_STATE.q;
  $('#mQ').oninput = () => {
    MEM_STATE.q = $('#mQ').value.trim();
    clearTimeout(state._memT);
    state._memT = setTimeout(loadList, 250);
  };

  await Promise.all([loadMeta(), loadDocs(), loadList()]);
}

/* ---------------- 视图：设置 ---------------- */
let secCfg = null;

const MODEL_HINTS = {
  deepseek: [
    ['deepseek-flash', 'V4.1 Flash · 推荐'],
    ['deepseek-v4-pro', 'V4 Pro · 更贵更强']
  ],
  teleai: []
};

async function viewSettings(root) {
  root.innerHTML = `
  <div class="page-h">
    <div><h2>设置</h2>
      <div class="desc">选供应商 → 填 Key → 测试连接。Key 加密存本机，只进不出。</div></div>
  </div>
  <div class="grid g2">
    <div class="card">
      <h3>① 选择供应商</h3>
      <div class="row" style="flex-wrap:wrap;gap:8px" id="provBox"></div>
      <div id="keyStatus" style="margin-top:14px"></div>

      <div style="height:16px"></div>
      <div class="field"><label>API Key</label>
        <div class="row">
          <input id="cKey" type="password" autocomplete="off" spellcheck="false"
                 placeholder="粘贴后点保存，输入框会立即清空" style="flex:1" />
          <button class="btn" id="toggleKey" type="button">显示</button>
        </div>
      </div>
      <p class="hint" style="margin:6px 0 0">只提交这一次。之后浏览器里再也没有明文。</p>

      <div style="height:14px"></div>
      <div class="field"><label>模型名</label>
        <input id="cModel" type="text" placeholder="deepseek-flash" /></div>
      <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px" id="modelChips"></div>

      <div style="height:14px"></div>
      <div class="field"><label>base_url</label>
        <input id="cBase" type="text" placeholder="https://api.deepseek.com/v1" /></div>
      <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px" id="presetBox"></div>

      <div style="height:18px"></div>
      <div class="row" style="flex-wrap:wrap">
        <button class="btn primary" id="saveC">保存</button>
        <button class="btn" id="testChat">测试连接</button>
        <button class="btn" id="probe">拉取模型列表</button>
        <button class="btn ghost" id="clearKey" style="color:#b91c1c">删除已保存的 Key</button>
      </div>
      <div id="modelList"></div>
      <div id="testOut"></div>
    </div>

    <div class="card">
      <h3>② 保密是怎么做到的</h3>
      <p class="hint" style="margin:0 0 12px">
        「前端输入」和「前端持有」是两件事。这里做的是前者，绝不做后者。
      </p>
      <ol class="hint" style="padding-left:18px;line-height:2;margin:0 0 14px">
        <li>Key 只提交 <b>一次</b>，走 <span class="mono">127.0.0.1</span> 回环，不出网卡</li>
        <li>后端用 <b>Windows DPAPI</b> 加密后存 <span class="mono">data/secrets.bin</span>，
            绑定<b>当前 Windows 用户 + 本机</b>，拷到别的机器解不开</li>
        <li>任何接口只返回<b>掩码</b>（<span class="mono">sk-a1b2****9f8e</span>），明文永不出后端</li>
        <li>前端<b>不写 localStorage、不写 cookie</b>，输入框提交后立即清空</li>
        <li>所有大模型调用都在<b>后端</b>完成 —— 浏览器不直连 DeepSeek，
            所以 F12 的 Network 里翻不到 Key</li>
        <li>报错信息统一过 <span class="mono">scrub()</span>，万一网关回显了 Key 也会被抹掉</li>
        <li><span class="mono">data/</span> 已在 .gitignore，不会随仓库推上 GitHub</li>
      </ol>
      <div id="secureNote"></div>
      <div style="height:14px"></div>
      <h3>③ 去哪拿 Key</h3>
      <div class="row" style="flex-wrap:wrap;gap:8px" id="linkBox"></div>
      <p class="hint" style="margin-top:12px">
        <b>DeepSeek 注意</b>：模型名用 <span class="mono">deepseek-flash</span>
        （即 V4.1 Flash）。旧名 <span class="mono">deepseek-v4-flash</span> 已下线，
        虽然还能调但会兼容路由到 V4.1 Flash；<span class="mono">deepseek-chat</span> /
        <span class="mono">deepseek-reasoner</span> 已在 2026-07-24 弃用。
      </p>
      <p class="hint">
        <b>思考模式</b>：DeepSeek 默认开启深度思考，此时 temperature 参数<b>不生效</b>。
        本项目已按场景区分 —— 讲课类开思考（质量优先），抽记忆 / 挖模式 / 出题关思考（要确定性）。
      </p>
    </div>
  </div>`;

  // ---------- 渲染 ----------
  const renderCfg = (c) => {
    secCfg = c;
    const cur = (c.providers || []).find(p => p.name === c.provider) || {};

    // 供应商
    $('#provBox').innerHTML = (c.providers || []).map(p => `
      <button class="btn ${p.name === c.provider ? 'primary' : ''}" data-p="${h(p.name)}">
        ${h(p.label)}${p.has_key ? ' ✓' : ''}
      </button>`).join('');
    $$('#provBox .btn').forEach(b => b.onclick = async () => {
      if (b.dataset.p === secCfg.provider) return;
      try {
        await api.post('/api/system/config', { provider: b.dataset.p });
        toast('已切换供应商');
        renderSettingsReload(root);
      } catch (e) { toast(e.message, true); }
    });

    // Key 状态
    if (cur.from_env) {
      $('#keyStatus').innerHTML = `<span class="pill ok">环境变量已配置</span>
        <span class="hint"> 从 ${h(cur.name === 'deepseek' ? 'DEEPSEEK_API_KEY' : 'TELEAI_APP_KEY')} 读取，
        优先级高于本机存储</span>`;
    } else if (cur.has_key) {
      $('#keyStatus').innerHTML = `<span class="pill ok">已保存并加密</span>
        <span class="mono" style="margin-left:6px">${h(cur.key_masked)}</span>
        <div class="hint" style="margin-top:6px">留空提交不会覆盖现有 Key；要换就填新的。</div>`;
    } else {
      $('#keyStatus').innerHTML = `<span class="pill warn">未配置 Key</span>
        <span class="hint"> 当前是离线演示模式，对话会用占位回复</span>`;
    }
    $('#cKey').value = '';
    $('#cKey').placeholder = cur.has_key
      ? `已保存 ${cur.key_masked}，留空则不修改`
      : '粘贴后点保存，输入框会立即清空';

    // 模型 / base_url
    $('#cModel').value = cur.model || '';
    $('#cBase').value = cur.base_url || '';
    $('#cModel').placeholder = (MODEL_HINTS[c.provider] || [])[0]?.[0] || '手动填写模型名';

    $('#modelChips').innerHTML = (MODEL_HINTS[c.provider] || []).map(([m, d]) =>
      `<span class="pill brand" style="cursor:pointer" data-m="${h(m)}">${h(m)}
        <span style="opacity:.7">· ${h(d)}</span></span>`).join('');
    $$('#modelChips .pill').forEach(el => el.onclick = () => {
      $('#cModel').value = el.dataset.m;
    });

    $('#presetBox').innerHTML = (cur.presets || []).map(p =>
      `<span class="pill" style="cursor:pointer" data-u="${h(p.value)}"
         title="${h(p.value)}">${h(p.label)}</span>`).join('');
    $$('#presetBox .pill').forEach(el => el.onclick = () => {
      $('#cBase').value = el.dataset.u;
    });

    // 安全说明
    $('#secureNote').innerHTML = `<div class="insight ${c.secure_storage ? '' : 'high'}">
      <div class="t">${c.secure_storage ? '✅ 加密存储已启用' : '⚠️ 加密存储不可用'}</div>
      <div class="d">${h(c.secure_note || '')}</div></div>`;

    // 平台链接
    $('#linkBox').innerHTML = `
      <a class="btn sm" href="${h(cur.console || '#')}" target="_blank" rel="noopener">申请 API Key ↗</a>
      <a class="btn sm ghost" href="${h(cur.doc || '#')}" target="_blank" rel="noopener">官方文档 ↗</a>`;
  };

  const renderSettingsReload = async () => {
    try {
      const c = await api.get('/api/system/config');
      if (!$('#provBox')) return;
      renderCfg(c);
    } catch (e) { toast(e.message, true); }
  };

  try {
    const c = await api.get('/api/system/config');
    if (!$('#provBox')) return;
    renderCfg(c);
  } catch (e) {
    toast(e.message, true);
    return;
  }

  // ---------- 交互 ----------
  $('#toggleKey').onclick = () => {
    const inp = $('#cKey');
    const show = inp.type === 'password';
    inp.type = show ? 'text' : 'password';
    $('#toggleKey').textContent = show ? '隐藏' : '显示';
  };

  $('#saveC').onclick = async () => {
    const k = $('#cKey').value.trim();
    const body = {
      provider: secCfg.provider,
      model: $('#cModel').value.trim(),
      base_url: $('#cBase').value.trim()
    };
    // 只有真的填了才带 api_key，留空表示「不修改」
    if (k) body.api_key = k;
    $('#cKey').value = '';           // 提交即清空，不在 DOM 里留明文
    $('#cKey').type = 'password';
    $('#toggleKey').textContent = '显示';
    try {
      const c = await api.post('/api/system/config', body);
      renderCfg(c);
      toast(c.configured ? '已保存，模型已接入' : '已保存（还差 Key 或模型名）');
      refreshMode();
    } catch (e) { toast(e.message, true); }
  };

  $('#clearKey').onclick = async () => {
    if (!confirm('确定删除已保存的 API Key？删除后需要重新填写。')) return;
    try {
      const r = await api.post('/api/system/key/clear', { provider: secCfg.provider });
      if (r.ok === false) return toast(r.message || '删除失败', true);
      renderCfg({ provider: r.provider, providers: r.providers,
                  configured: r.configured, secure_storage: r.secure_storage,
                  secure_note: r.secure_note });
      toast('已删除');
      refreshMode();
    } catch (e) { toast(e.message, true); }
  };

  $('#probe').onclick = async () => {
    $('#modelList').innerHTML = '<div class="empty">拉取中…</div>';
    try {
      const r = await api.get('/api/system/models?provider=' + encodeURIComponent(secCfg.provider));
      if (!r.ok) {
        $('#modelList').innerHTML = `<div class="insight medium" style="margin-top:12px">
          <div class="t">没拉到列表（不代表配置错了）</div>
          <div class="d">${h(r.message || '未知原因')}</div>
          ${r.hint ? `<div class="a">${h(r.hint)}</div>` : ''}</div>`;
        return;
      }
      $('#modelList').innerHTML = `<div style="margin-top:12px">
        <h5 class="hint">可用模型（${r.count} 个，点一下填入）</h5>
        <div class="row" style="flex-wrap:wrap;gap:6px;margin-top:8px">
        ${r.models.map(m => `<span class="pill brand" style="cursor:pointer"
            data-m="${h(m)}">${h(m)}</span>`).join('')}</div></div>`;
      $$('#modelList .pill').forEach(p => p.onclick = () => { $('#cModel').value = p.dataset.m; });
    } catch (e) { $('#modelList').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
  };

  $('#testChat').onclick = async () => {
    $('#testOut').innerHTML = '<div class="empty">测试中…（一次真实调用）</div>';
    try {
      const r = await api.post('/api/system/test-chat');
      $('#testOut').innerHTML = `<div class="insight ${r.ok ? '' : 'high'}" style="margin-top:12px">
        <div class="t">${r.ok ? '✅ 连通成功' : '❌ 连通失败'}</div>
        <div class="d">${r.ok
          ? `provider=${h(r.provider)} · model=${h(r.model)} · 回复：${h(r.reply || '')}`
          : h(r.message || '')}</div></div>`;
    } catch (e) { $('#testOut').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
  };
}

/* ---------------- 启动 ---------------- */
(async function boot() {
  if (!state.token) return renderAuth('login');
  try {
    const me = await api.get('/api/auth/me');
    state.user = me;
    renderApp();
  } catch (e) {
    localStorage.removeItem('sb_token');
    localStorage.removeItem('sb_user');
    state.token = '';
    renderAuth('login');
  }
})();
