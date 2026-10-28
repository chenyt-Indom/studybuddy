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
  senior: [['senior_1', '高一'], ['senior_2', '高二'], ['senior_3', '高三']]
};
const ERROR_TYPES = {
  concept: '概念不清', calculation: '计算失误', careless: '粗心',
  method: '方法不当', transfer: '迁移失败', timeout: '时间不够'
};
const NAV = [
  ['chat', '学科对话', '💬'],
  ['dashboard', '学情看板', '📊'],
  ['review', '复习中心', '🔁'],
  ['kp', '知识点', '📖'],
  ['mistakes', '错题本', '📕'],
  ['insight', '洞察', '💡'],
  ['memory', '记忆库', '🧠'],
  ['textbook', '教材', '📚'],
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
      <div class="logo">StudyBuddy <small>v0.1${_frontStamp()}</small></div>
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
  // 图片点开看大图（全局委托一次，避免每个气泡重复绑）
  document.addEventListener('click', (e) => {
    const img = e.target && e.target.closest && e.target.closest('.bubble-imgs img');
    if (img) openLightbox(img.getAttribute('src'));
  });
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
  // 给 <body> 打上当前视图标记：对话页要用它做「撑满剩余高度」的布局（见 style.css）
  document.body.dataset.view = state.view;
  ({ chat: viewChat, dashboard: viewDashboard, review: viewReview, mistakes: viewMistakes,
     insight: viewInsight, kp: viewKp, memory: viewMemory, textbook: viewTextbook,
     profile: viewProfile, settings: viewSettings }[state.view] || viewChat)(m);
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
        <div class="attach-bar" id="attachBar" hidden></div>
        <div class="composer-row">
          <button class="btn icon" id="pickImg" type="button"
                  title="上传题目图片（也可以直接粘贴或把图片拖进来）"
                  aria-label="上传题目图片"><svg width="17" height="17" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
                  stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2.5" />
                  <circle cx="8.6" cy="8.6" r="1.6" /><path d="M21 15.5l-4.6-4.6L5.6 21" /></svg></button>
          <textarea id="inp" placeholder="题目不会做？拍图上传，或直接问（Enter 发送 / Shift+Enter 换行）"></textarea>
          <button class="btn primary" id="send">发送</button>
        </div>
        <div class="hint" id="visionHint" hidden></div>
      </div>
      <input type="file" id="imgFile" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden />
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

  // ---------- 图片：按钮 / 粘贴 / 拖拽 ----------
  pendingImgs = [];
  renderAttachBar();
  $('#pickImg').onclick = () => $('#imgFile').click();
  $('#imgFile').onchange = async (e) => {
    await addImages(e.target.files);
    e.target.value = '';        // 清空，才能再选同一张
  };
  inp.onpaste = (e) => {
    const files = Array.from((e.clipboardData && e.clipboardData.files) || [])
      .filter(f => String(f.type).startsWith('image/'));
    if (files.length) { e.preventDefault(); addImages(files); }
  };
  const main = $('.chat-main');
  if (main) {
    main.addEventListener('dragover', (e) => { e.preventDefault(); main.classList.add('dragging'); });
    main.addEventListener('dragleave', () => main.classList.remove('dragging'));
    main.addEventListener('drop', (e) => {
      e.preventDefault();
      main.classList.remove('dragging');
      addImages(e.dataTransfer && e.dataTransfer.files);
    });
  }

  // 当前模型能不能看图：不能就把按钮标灰 + 说明原因，别让用户白传一张
  const checkVision = async () => {
    try {
      const v = await api.get('/api/system/vision');
      if (!$('#pickImg')) return;
      if (!v.supported) {
        const b = $('#pickImg'), hint = $('#visionHint');
        if (b) { b.disabled = true; b.title = v.note || '当前模型不支持图片'; }
        if (hint) {
          hint.hidden = false;
          hint.textContent = '⚠️ ' + (v.note || `当前模型 ${v.model} 不支持看图`);
        }
      }
    } catch (e) { /* 探测失败不挡路，真不支持时发出去会报错 */ }
  };
  checkVision();
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
    hydrateImgs(box);
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

function bubble(role, content, imgs) {
  const isUser = role === 'user';
  // 图片放文字上方：题目截图先看到，再看自己写的疑问
  // imgs: [{id, src?}] —— src 只在刚发出去时有（本地预览 URL）；
  // 历史消息只有 id，靠 hydrateImgs() 带鉴权拉取（<img> 标签不会带 Authorization 头）
  const pics = (imgs && imgs.length)
    ? `<div class="bubble-imgs">${imgs.map(im => {
        const src = im.src ? ` src="${h(im.src)}"` : '';
        const aid = im.id ? ` data-aid="${h(im.id)}"` : '';
        return `<img class="zoom"${src}${aid} alt="题目图片" loading="lazy" />`;
      }).join('')}</div>`
    : '';
  return `<div class="msg ${isUser ? 'user' : 'bot'}">
    <div class="av">${isUser ? '我' : 'SB'}</div>
    <div class="bubble">${pics}${isUser ? h(content).replace(/\n/g, '<br>') : md(content)}</div>
  </div>`;
}

/* 图片附件要用带鉴权的 fetch 取回来再变 blob URL。
   直接用 <img src="/api/chat/attachments/..."> 是不行的：图片标签不会带 Authorization 头，
   服务端只认 Bearer token → 结果就是"裂图"（踩过）。 */
const imgCache = new Map();   // aid -> objectURL

async function loadImgEl(img) {
  const aid = img.dataset.aid;
  if (!aid || img.getAttribute('src')) return;
  if (imgCache.has(aid)) { img.src = imgCache.get(aid); return; }
  try {
    const res = await fetch('/api/chat/attachments/' + encodeURIComponent(aid), {
      headers: { Authorization: 'Bearer ' + state.token }
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const url = URL.createObjectURL(await res.blob());
    imgCache.set(aid, url);
    img.src = url;
  } catch (e) {
    img.classList.add('broken');
    img.alt = '图片加载失败（可能已被清理）';
  }
}

function hydrateImgs(root) {
  if (!root) return;
  $$('img[data-aid]', root).forEach(img => { loadImgEl(img); });
}

/* ---------------- 聊天图片：选择 / 粘贴 / 拖拽 / 预览 ---------------- */
let pendingImgs = [];   // 待发送：{id, url, preview, name, size, uploading}

function renderAttachBar() {
  const bar = $('#attachBar');
  if (!bar) return;
  if (!pendingImgs.length) {
    bar.hidden = true;
    bar.innerHTML = '';
    return;
  }
  bar.hidden = false;
  bar.innerHTML = pendingImgs.map((im, i) => `
    <div class="att-chip${im.uploading ? ' up' : ''}">
      <img src="${h(im.preview || im.url)}" alt="" />
      <button class="x" type="button" data-del="${i}" title="移除这张">×</button>
      ${im.uploading ? '<span class="spin"></span>' : ''}
    </div>`).join('') +
    `<span class="hint">可继续粘贴/拖拽，最多 4 张 · 单张 8MB</span>`;
  $$('#attachBar [data-del]').forEach(b => {
    b.onclick = () => { pendingImgs.splice(+b.dataset.del, 1); renderAttachBar(); };
  });
}

async function addImages(files) {
  const list = Array.from(files || []).filter(f => f && String(f.type).startsWith('image/'));
  if (!list.length) return;
  if (pendingImgs.length + list.length > 4) {
    toast('一条消息最多 4 张图片', true);
    return;
  }
  for (const f of list) {
    let preview = '';
    try { preview = URL.createObjectURL(f); } catch (e) { preview = ''; }  // 老浏览器/测试环境没有就退化为不预览
    const item = { name: f.name, preview, uploading: true };
    pendingImgs.push(item);
    renderAttachBar();
    try {
      const fd = new FormData();
      fd.append('file', f);
      const res = await fetch('/api/chat/attachments', {
        method: 'POST', headers: { Authorization: 'Bearer ' + state.token }, body: fd
      });
      const r = await res.json().catch(() => ({}));
      // 后端对"不是图片/太大"也是 200 + ok:false，必须显式判
      if (!res.ok || !r.ok) throw new Error(r.message || r.detail || ('HTTP ' + res.status));
      item.id = r.id; item.url = r.url; item.size = r.size; item.uploading = false;
    } catch (e) {
      const i = pendingImgs.indexOf(item);
      if (i >= 0) pendingImgs.splice(i, 1);
      toast(e.message, true);
    }
    renderAttachBar();
  }
}

function openLightbox(src) {
  let box = $('#lightbox');
  if (!box) {
    box = document.createElement('div');
    box.id = 'lightbox';
    box.className = 'lightbox';
    box.onclick = () => { box.className = 'lightbox'; };
    document.body.appendChild(box);
  }
  box.innerHTML = `<img src="${h(src)}" alt="题目图片" />`;
  box.className = 'lightbox on';
}


/* 历史消息：带思维链折叠 + 来源列表 */
function historyBubble(m) {
  if (m.role === 'user') {
    return bubble('user', m.content, (m.attachments || []).map(a => ({ id: a.id })));
  }
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
  if (!inp || !box) return;
  const text = inp.value.trim();
  const imgs = pendingImgs.filter(i => i.id && !i.uploading);
  if (!text && !imgs.length) return;
  if (pendingImgs.some(i => i.uploading)) {
    toast('图片还在上传，稍等一下再发', true);
    return;
  }
  inp.value = ''; btn.disabled = true;
  const sendIds = imgs.map(i => i.id);
  const sendItems = imgs.map(i => ({ id: i.id, src: i.preview || i.url }));
  pendingImgs = [];          // 图片已经跟着这条消息走了，预览立刻清空
  renderAttachBar();

  if (box.querySelector('.empty')) box.innerHTML = '';
  box.dataset.live = '1';   // 标记：这里已经有实时消息，别再被历史渲染覆盖
  box.insertAdjacentHTML('beforeend', bubble('user', text, sendItems));
  hydrateImgs(box);
  const hd = createBotBubble(box);
  box.scrollTop = box.scrollHeight;

  const useWeb = state.useWeb === 'auto' ? null : (state.useWeb === 'on');
  const keepBottom = () => { box.scrollTop = box.scrollHeight; };

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + state.token },
      body: JSON.stringify({
        subject: state.subject, message: text, use_web: useWeb,
        attachments: sendIds
      })
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
    <div class="card"><h3>全部洞察</h3><div id="list"></div></div>
    <div style="height:16px"></div>
    <div class="card">
      <h3>本周学习周报 <span class="tag" id="wkTag"></span>
        <div class="spacer"></div>
        <button class="btn sm" id="wkGen">生成 / 刷新</button></h3>
      <div id="weekly"><div class="empty">还没生成过周报</div></div>
    </div>`;

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

  // ---------- 学习周报 ----------
  const renderWeekly = (r) => {
    if (!$('#weekly')) return;
    const tag = $('#wkTag');
    if (!r || !r.exists) {
      if (tag) tag.textContent = '';
      $('#weekly').innerHTML = `<div class="empty">这周还没生成周报。
        点右上角「生成 / 刷新」——会统计本周的问答、错题、考试、复习和薄弱点。</div>`;
      return;
    }
    if (tag) {
      tag.textContent = `${r.week_start} ~ ${r.week_end} · ${r.source === 'llm' ? 'AI 生成' : '数字模板'}`;
    }
    $('#weekly').innerHTML = `<div class="doc-body" style="white-space:normal">
      ${md(r.content || '')}</div>`;
  };

  const loadWeekly = async () => {
    try { renderWeekly(await api.get('/api/weekly/latest')); }
    catch (e) { if ($('#weekly')) $('#weekly').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
  };

  $('#wkGen').onclick = async () => {
    const btn = $('#wkGen');
    btn.disabled = true;
    btn.textContent = '生成中…';
    try {
      const r = await api.post('/api/weekly/generate');
      renderWeekly({ ...r, exists: true });
      toast(r.source === 'llm' ? '周报已生成' : '已用数字模板生成（模型不可用）');
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = '生成 / 刷新'; }
  };

  $('#run').onclick = async () => {
    try {
      const r = await api.post('/api/insight/run');
      toast(`分析完成，命中 ${r.found} 条`);
      load();
    } catch (e) { toast(e.message, true); }
  };
  await load();
  await loadWeekly();
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
            <option value="senior">高中</option>
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

/* ---------------- 视图：知识点汇总（含提示与跨科联动） ---------------- */
const KP_STATE = { stage: 'senior', grade: '', subject: 'all', mode: 'all', q: '', open: '' };
const KP_MODES = [
  ['all', '全部'], ['learned', '已学过'], ['current', '仅本年级'],
  ['weak', '我的薄弱'], ['due', '待复习'],
];
const KP_GRADES = {
  primary: [['primary_1', '一年级'], ['primary_2', '二年级'], ['primary_3', '三年级'],
            ['primary_4', '四年级'], ['primary_5', '五年级'], ['primary_6', '六年级']],
  junior: [['junior_1', '初一'], ['junior_2', '初二'], ['junior_3', '初三']],
  senior: [['senior_1', '高一'], ['senior_2', '高二'], ['senior_3', '高三']],
};

/* 从知识点页跳去问 AI：先把视图切到对话，再把问题填进输入框 */
function askAbout(text) {
  state.view = 'chat';
  $$('.side nav a').forEach(x => x.classList.toggle('on', x.dataset.v === 'chat'));
  route();
  let n = 0;
  const t = setInterval(() => {
    const i = $('#inp');
    n++;
    if (i && !i.disabled) {
      i.value = text; i.focus(); i.setSelectionRange(text.length, text.length);
      clearInterval(t);
    } else if (n > 40) clearInterval(t);
  }, 100);
}

async function viewKp(root) {
  root.innerHTML = `
  <div class="page-h">
    <div><h2>知识点汇总</h2>
      <div class="desc">各年级各科的知识点 · 每个都带「一句话要点 / 常见易错 / 记忆锚点」</div></div>
    <div class="row" style="gap:8px">
      <select id="kpStage" style="width:auto">
        <option value="primary">小学</option>
        <option value="junior">初中</option>
        <option value="senior">高中</option>
      </select>
      <select id="kpGrade" style="width:auto"></select>
      <select id="kpSubj" style="width:auto">
        <option value="all">全部科目</option>
        ${SUBJECTS.map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}
      </select>
    </div>
  </div>

  <div class="card" style="margin-bottom:14px">
    <div class="row" style="gap:10px;flex-wrap:wrap">
      <input id="kpQ" type="text" placeholder="搜知识点 / 别名 / 要点，例如：抛物线、楞次定律、盐类水解" style="flex:1;min-width:180px" />
      <div class="row" id="kpModes" style="gap:6px;flex-wrap:wrap"></div>
    </div>
  </div>

  <div class="grid g4" id="kpStats" style="margin-bottom:14px"></div>
  <div id="kpList"><div class="empty">加载中…</div></div>
  <div id="kpDetail"></div>`;

  const fillGrades = () => {
    const list = KP_GRADES[KP_STATE.stage] || [];
    const sel = $('#kpGrade');
    if (!sel) return;
    sel.innerHTML = `<option value="">全部年级</option>` +
      list.map(([k, n]) => `<option value="${k}">${n}</option>`).join('');
    sel.value = KP_STATE.grade || '';
  };

  const renderModes = () => {
    const box = $('#kpModes');
    if (!box) return;
    box.innerHTML = KP_MODES.map(([k, n]) => `<button class="btn sm"
      data-mode="${k}" style="${KP_STATE.mode === k
        ? 'background:var(--brand);border-color:var(--brand);color:#fff' : ''}">${n}</button>`).join('');
    $$('#kpModes [data-mode]').forEach(b => {
      b.onclick = () => { KP_STATE.mode = b.dataset.mode; renderModes(); load(); };
    });
  };

  const kpRow = (it) => {
    const pct = it.mastery == null ? 0 : Math.round(it.mastery * 100);
    const cls = it.level === 'weak' ? 'weak' : (it.level === 'good' ? 'good' : '');
    const cross = (it.cross || [])[0];
    return `<div class="kp-row" data-code="${h(it.code)}">
      <div class="kp-nm">
        <b>${h(it.name)}</b>
        <span class="pill">${h(it.grade_cn)}</span>
        ${it.due ? '<span class="pill warn">待复习</span>' : ''}
        ${it.learned ? '' : '<span class="pill">超前</span>'}
        ${cross ? `<span class="pill brand" title="${h(cross.note || '')}">联动 ${h(cross.subject_cn)}</span>` : ''}
      </div>
      <div class="kp-sm">${h(it.summary || '')}</div>
      <div class="kp-meter"><i class="${cls}" style="width:${pct}%"></i></div>
      <div class="kp-pct ${cls}">${it.mastery == null ? '未测' : pct + '%'}</div>
    </div>`;
  };

  const renderList = (subjects) => {
    const box = $('#kpList');
    if (!box) return;
    if (!subjects.length) {
      box.innerHTML = `<div class="card"><div class="empty">
        这个条件下没有知识点。试试切回「全部」或清空搜索词。</div></div>`;
      return;
    }
    box.innerHTML = subjects.map(s => `
      <div class="card" style="margin-bottom:14px">
        <h3>${h(s.cn)}
          <span class="tag">${s.total} 个 · 薄弱 ${s.weak} · 待复习 ${s.due}</span></h3>
        ${s.modules.map(m => `
          <div class="kp-mod">
            <div class="kp-mod-h">${h(m.name)}<span class="tag">${m.items.length}</span></div>
            ${m.items.map(kpRow).join('')}
          </div>`).join('')}
      </div>`).join('');
    $$('#kpList .kp-row').forEach(row => {
      row.onclick = () => openDetail(row.dataset.code);
    });
  };

  const renderStats = (st) => {
    const box = $('#kpStats');
    if (!box) return;
    const cells = [
      ['本页知识点', st.total_shown, `共 ${st.total_all} 个`],
      ['已学过', st.learned, '按我的年级算'],
      ['我的薄弱', st.weak, st.unknown ? `另有 ${st.unknown} 个未测` : '掌握度 < 50%'],
      ['待复习', st.due, '按遗忘曲线到期'],
    ];
    box.innerHTML = cells.map(([t, v, s2]) => `
      <div class="card"><div class="hint">${t}</div>
        <div class="stat">${v}<small>${s2}</small></div></div>`).join('');
  };

  const openDetail = async (code) => {
    KP_STATE.open = code;
    const box = $('#kpDetail');
    if (box) box.innerHTML = '<div class="empty">加载中…</div>';
    try {
      const r = await api.get('/api/kp/' + encodeURIComponent(code));
      if (!r.ok || !$('#kpDetail')) { if (box) box.innerHTML = `<div class="empty">${h(r.message || '读取失败')}</div>`; return; }
      const it = r.item;
      const cross = (r.cross || []).map(c => `
        <div class="kp-link">
          <b>${h(c.name)}</b>
          <span class="pill">${h(c.subject_cn)}</span>
          <span class="pill">${h(c.relation_cn)}</span>
          <div class="hint">${h(c.note || '')}</div>
        </div>`).join('') || '<div class="hint">暂无跨科联动</div>';
      const pre = (r.prerequisites || []).map(p =>
        `<span class="pill">${h(p.name)}</span>`).join('') || '<span class="hint">无</span>';
      const nxt = (r.unlocks || []).map(p =>
        `<span class="pill">${h(p.name)}</span>`).join('') || '<span class="hint">无</span>';
      const mv = r.mastery ? Math.round(r.mastery.value * 100) + '%' : '未测';
      $('#kpDetail').innerHTML = `
        <div class="card" id="kpDetailCard" style="margin-bottom:14px;border-left:3px solid var(--brand)">
          <h3>${h(it.name)}
            <span class="tag">${h(it.subject_cn)} · ${h(it.module || '')} · ${h(it.grade_cn)} · 难度 ${it.difficulty}/5</span>
            <div class="spacer"></div>
            <button class="btn sm" id="kpAsk">去问 AI</button>
            <button class="btn sm" id="kpClose">关闭</button></h3>
          <div class="kp-blk"><div class="kp-k">一句话要点</div><div>${h(it.summary || '—')}</div></div>
          <div class="kp-blk warn"><div class="kp-k">常见易错</div><div>${h(it.pitfall || '—')}</div></div>
          <div class="kp-blk ok"><div class="kp-k">记忆锚点</div><div>${h(it.mnemonic || '—')}</div></div>
          <div class="kp-blk"><div class="kp-k">前置 / 解锁</div>
            <div>前置：${pre}</div><div style="margin-top:6px">学完能解锁：${nxt}</div></div>
          <div class="kp-blk"><div class="kp-k">跨科联动（用已会的锚定新学的）</div>${cross}</div>
          <div class="kp-blk"><div class="kp-k">我的情况</div>
            <div class="hint">掌握度 ${mv} · 错题 ${r.mistakes} 道 ·
            ${r.review ? `下次复习 ${h(r.review.next_review)}` : '还没排复习'}</div></div>
        </div>`;
      $('#kpClose').onclick = () => { $('#kpDetail').innerHTML = ''; };
      $('#kpAsk').onclick = () => askAbout(
        `请讲讲「${it.name}」，重点讲我容易错的地方，再给我一个能记住的说法。`);
      $('#kpDetailCard').scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      if ($('#kpDetail')) $('#kpDetail').innerHTML = `<div class="empty">${h(e.message)}</div>`;
    }
  };

  const load = async () => {
    try {
      const qs = new URLSearchParams({
        stage: KP_STATE.stage, subject: KP_STATE.subject,
        mode: KP_STATE.mode, q: KP_STATE.q, grade: KP_STATE.grade || '',
      });
      const r = await api.get('/api/kp/overview?' + qs.toString());
      if (!$('#kpList')) return;
      if (!KP_STATE.grade && r.grade) {
        // 用画像里的年级做默认，并回填到下拉框
        const sel = $('#kpGrade');
        if (sel && (KP_GRADES[KP_STATE.stage] || []).some(([k]) => k === r.grade)) {
          sel.value = r.grade;
        }
      }
      renderStats(r.stats || {});
      renderList(r.subjects || []);
      if (KP_STATE.open) openDetail(KP_STATE.open);
    } catch (e) {
      if ($('#kpList')) $('#kpList').innerHTML = `<div class="card"><div class="empty">${h(e.message)}</div></div>`;
    }
  };

  fillGrades();
  renderModes();
  $('#kpStage').value = KP_STATE.stage;
  $('#kpStage').onchange = () => {
    KP_STATE.stage = $('#kpStage').value;
    KP_STATE.grade = '';
    KP_STATE.open = '';
    fillGrades();
    if ($('#kpDetail')) $('#kpDetail').innerHTML = '';
    load();
  };
  $('#kpGrade').onchange = () => { KP_STATE.grade = $('#kpGrade').value; load(); };
  $('#kpSubj').onchange = () => { KP_STATE.subject = $('#kpSubj').value; load(); };
  $('#kpQ').value = KP_STATE.q;
  let kpT = null;
  $('#kpQ').oninput = () => {
    KP_STATE.q = $('#kpQ').value.trim();
    clearTimeout(kpT);
    kpT = setTimeout(load, 250);
  };

  await load();
}

/* ---------------- 视图：教材 ---------------- */
const TB_STATE = {
  subject: 'math', stage: 'senior',
  currentCode: '',      // 当前教材的 code（注意是 code 不是 id，两者比较不上就永远不高亮）
  pendingEdition: ''    // 点了「导入这个版本」后，等导入完成要挂到的版本 code
};

async function viewTextbook(root) {
  TB_STATE.pendingEdition = '';   // 每次进页面清掉上次点的那张卡，避免导入挂错版本
  root.innerHTML = `
  <div class="page-h">
    <div><h2>教材</h2>
      <div class="desc">先选版本，再确认是不是最新 · 讲解按课本章节顺序与符号约定</div></div>
    <div class="row" style="gap:8px">
      <select id="tbStage" style="width:auto">
        <option value="senior">高中</option>
        <option value="junior">初中</option>
      </select>
      <select id="tbSubject" style="width:auto">
        ${SUBJECTS.map(([k, n]) => `<option value="${k}" ${k === TB_STATE.subject ? 'selected' : ''}>${n}</option>`).join('')}
      </select>
      <button class="btn" id="tbMatch">定位预览</button>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h3>① 选择教材版本 <span class="tag">不同版本章节顺序不同，选错就白搭</span></h3>
    <div id="tbEditions"></div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h3>② 当前使用 <span class="tag" id="tbCur"></span></h3>
    <div id="tbLatest"></div>
  </div>

  <div class="grid g2" style="margin-bottom:16px">
    <div class="card" id="tbImportCard">
      <h3>导入自己的教材 <span class="tag">PDF / TXT / MD</span></h3>
      <p class="hint" style="margin:0 0 12px">
        没有内置目录的版本，用自己手上的正版教材导入。<b>文件只存本机</b>
        <span class="mono">data/textbooks/</span>，不上传、不进 Git。
      </p>
      <div class="field"><label>文件</label>
        <input id="tbFile" type="file" accept=".pdf,.txt,.md" /></div>
      <div style="height:10px"></div>
      <div class="grid g2">
        <div class="field"><label>版本名</label>
          <input id="tbEdName" type="text" placeholder="例如：北师大版" /></div>
        <div class="field"><label>修订年份</label>
          <input id="tbEdYear" type="number" placeholder="例如：2019" /></div>
        <div class="field"><label>册次</label>
          <input id="tbVolume" type="text" placeholder="例如：必修第一册" /></div>
        <div class="field"><label>年级</label>
          <select id="tbGrade">
            ${Object.values(GRADE_OPTIONS).flat().map(([k, n]) =>
              `<option value="${k}" ${k === 'senior_1' ? 'selected' : ''}>${n}</option>`).join('')}
          </select></div>
      </div>
      <div style="height:14px"></div>
      <button class="btn primary" id="tbUpload">上传并解析</button>
      <p class="hint" style="margin:8px 0 0">
        扫描版 PDF（拍照转的、没有文字层）会自动走 OCR 识别，单次上限 20 页；
        整本书请用 <span class="mono">scripts/ocr_pdf.py</span> 先转 txt 再导入。
      </p>
      <div id="tbUpOut"></div>
    </div>

    <div class="card">
      <h3>粘贴目录导入 <span class="tag">没有电子版时用</span></h3>
      <p class="hint" style="margin:0 0 10px">
        每行一条，<span class="mono">|</span> 分隔：章节 | 小节 | 关键词
      </p>
      <textarea id="tbRaw" style="min-height:96px" placeholder="第一章 集合与常用逻辑用语 | 1.1 集合的概念 | 集合,元素"></textarea>
      <div style="height:10px"></div>
      <div class="field"><label>目录名称</label>
        <input id="tbTitle" type="text" value="自定义教材目录" /></div>
      <div style="height:14px"></div>
      <button class="btn" id="tbPaste">导入目录</button>
      <div id="tbPasteOut"></div>
    </div>

    <div class="card">
      <h3>粘贴正文导入 <span class="tag">从 IMA / 电子书复制正文过来，最省事</span></h3>
      <p class="hint" style="margin:0 0 10px">
        直接把课本正文粘进来（保留「第一章 / 1.1」这类标题行，我会按标题切成节）。
        粘完立刻离线可读、可检索，讲解也会引用原文。
      </p>
      <div class="field"><label>教材名称</label>
        <input id="tbxTitle" type="text" placeholder="例如：人教A版 必修第一册（从IMA复制）" /></div>
      <div style="height:10px"></div>
      <textarea id="tbxText" style="min-height:160px"
        placeholder="第一章 集合与常用逻辑用语&#10;1.1 集合的概念&#10;把一些确定的、彼此不同的对象看成一个整体……"></textarea>
      <div style="height:14px"></div>
      <button class="btn primary" id="tbxGo">切章节并入库</button>
      <div id="tbxOut"></div>
    </div>
  </div>

  <div class="card">
    <h3>章节结构 <span class="tag">点任意一节可直接看课本原文（离线可用）</span></h3>
    <div id="tbOutline"><div class="empty">选一本教材查看结构</div></div>
  </div>

  <div class="card" id="tbReader" style="display:none"></div>

  <div id="tbDialog"></div>`;

  // ---------- 版本列表 ----------
  // tbSeq：切科目/学段时 +1，用来丢弃「上一个科目」迟到的响应，
  // 否则慢请求回来会把新科目页面覆盖成旧数据（就是"切了没反应/切串了"）
  let tbSeq = 0;

  const loadEditions = async () => {
    const my = tbSeq;
    try {
      const r = await api.get(`/api/textbook/editions?subject=${TB_STATE.subject}&stage=${TB_STATE.stage}`);
      if (my !== tbSeq || !$('#tbEditions')) return;
      const eds = r.editions || [];
      if (!eds.length) {
        $('#tbEditions').innerHTML = `<div class="empty">该学段该科目暂无版本记录，可直接用下面「导入」自建</div>`;
        return;
      }
      $('#tbEditions').innerHTML = eds.map(e => {
        const books = e.books || [];
        // 没有内置/已导入目录的版本也必须给一个可点入口，
        // 否则整张卡片连按钮都没有，用户点了只会觉得"切换没反应"
        const bookBtns = books.map(b => `<button class="btn sm ${TB_STATE.currentCode === b.code ? 'primary' : ''}"
            data-use="${h(b.code)}">${h(b.volume || b.title)}</button>`).join('');
        const importBtn = e.custom ? '' : `<button class="btn sm" data-need="${h(e.code)}"
            data-name="${h(e.name)}">${books.length ? '＋导入另一册' : '导入这个版本的目录'}</button>`;
        return `
        <div class="mem" data-code="${h(e.code)}" style="border-left-color:${
          e.available ? '#16a34a' : '#e6eaf2'}">
          <div class="mem-head">
            <b style="font-size:13.5px">${h(e.name)}</b>
            <span class="pill">${h(e.edition || '')}</span>
            ${e.builtin ? '<span class="pill ok">内置目录</span>'
              : (e.available ? '<span class="pill brand">已导入</span>'
                             : '<span class="pill warn">需导入目录</span>')}
            ${e.custom ? '<span class="pill">自定义</span>' : ''}
            <span class="mem-meta">${h(e.publisher || '')}</span>
            <div class="spacer"></div>
            ${bookBtns}${importBtn}
          </div>
        </div>`;
      }).join('');

      // 绑定「切到这一册」
      $$('#tbEditions [data-use]').forEach(btn => {
        btn.onclick = async () => {
          const code = btn.dataset.use;
          const subject = TB_STATE.subject;   // 固定住科目，避免切换途中被改
          $$('#tbEditions button').forEach(b => { b.disabled = true; });
          btn.textContent = '切换中…';
          try {
            const r = await api.post(
              `/api/textbook/select?subject=${subject}&code=${encodeURIComponent(code)}`);
            // api 对 {"ok": false} 不会抛错，之前就是这样"提示成功但什么都没变"
            if (!r || r.ok === false) throw new Error((r && r.message) || '切换失败');
            TB_STATE.currentCode = code;
            toast(`已切换到「${r.title || code}」`);
            await loadCurrent();
            await loadEditions();   // 重渲染，让高亮跟着走
          } catch (e) {
            toast(e.message, true);
            await loadEditions();   // 失败也要把按钮恢复可点
          }
        };
      });

      // 没有目录的版本：引导到下面导入区，并记住要挂到哪个版本
      $$('#tbEditions [data-need]').forEach(btn => {
        btn.onclick = () => {
          const code = btn.dataset.need || '';
          const nm = btn.dataset.name || '';
          TB_STATE.pendingEdition = code;
          if ($('#tbEdName')) $('#tbEdName').value = nm;
          if ($('#tbImportCard')) $('#tbImportCard').scrollIntoView({ behavior: 'smooth', block: 'center' });
          if ($('#tbFile')) $('#tbFile').focus();
          toast(`先导入《${nm}》的目录，导入完成后会自动切到这个版本`);
        };
      });
    } catch (e) { toast(e.message, true); }
  };

  // ---------- 当前 + 最新核查 ----------
  const loadCurrent = async () => {
    const my = tbSeq;
    try {
      const c = await api.get('/api/textbook/current?subject=' + TB_STATE.subject);
      if (my !== tbSeq || !$('#tbCur')) return;
      if (!c.ok) {
        TB_STATE.currentCode = '';
        $('#tbCur').textContent = '未选择';
        $('#tbLatest').innerHTML = `<div class="empty">该科目还没有可用教材，先在上面选一个或导入</div>`;
        $('#tbOutline').innerHTML = '<div class="empty">选一本教材查看结构</div>';
        return;
      }
      $('#tbCur').textContent = `${c.title}（${c.publisher}${c.volume ? ' · ' + c.volume : ''}）`;
      TB_STATE.currentCode = c.code;

      const l = await api.get(`/api/textbook/${c.id}/latest`);
      if (my !== tbSeq || !$('#tbLatest')) return;
      const checked = l.checked_at
        ? l.checked_at.replace('T', ' ').slice(0, 16)
        : '从未核查';
      $('#tbLatest').innerHTML = `
        <div class="row" style="flex-wrap:wrap;gap:10px">
          <span class="pill ${l.checked_at ? 'ok' : 'warn'}">
            ${l.checked_at ? '已核查过最新版本' : '尚未核查是否最新'}</span>
          <span class="hint">上次核查：${h(checked)}</span>
          <div class="spacer"></div>
          <button class="btn" id="tbCheck">检查是否最新</button>
        </div>
        <div id="tbCheckOut" style="margin-top:10px">${
          l.verdict ? `<div class="insight"><div class="d">${h(l.verdict).replace(/\n/g, '<br>')}</div>
            ${(l.sources || []).length ? `<div class="a">来源：${l.sources.map((s, i) =>
              `<a href="${h(s.url)}" target="_blank" rel="noopener">[${i + 1}] ${h(s.site || s.title)}</a>`).join('　')}</div>` : ''}
          </div>` : '<div class="hint">教材会改版，内置年份可能过期。点「检查是否最新」会联网核查并给出来源。</div>'
        }</div>`;

      $('#tbCheck').onclick = async () => {
        const btn = $('#tbCheck');
        btn.disabled = true; btn.textContent = '联网核查中…';
        $('#tbCheckOut').innerHTML = '<div class="empty">正在检索最新版本信息…</div>';
        try {
          const r = await api.post(`/api/textbook/${c.id}/check-update`);
          if (!r.ok) {
            $('#tbCheckOut').innerHTML = `<div class="insight medium"><div class="d">${h(r.message || '核查失败')}</div></div>`;
          } else {
            $('#tbCheckOut').innerHTML = `<div class="insight">
              <div class="t">核查结果（记录版本：${h(r.recorded_edition || '未知')}）</div>
              <div class="d">${h(r.verdict || '').replace(/\n/g, '<br>')}</div>
              ${(r.sources || []).length ? `<div class="a">来源：${r.sources.map((s, i) =>
                `<a href="${h(s.url)}" target="_blank" rel="noopener">[${i + 1}] ${h(s.site || s.title)}</a>`).join('　')}</div>` : ''}
            </div>`;
          }
          loadEditions();
        } catch (e) { $('#tbCheckOut').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
        finally { btn.disabled = false; btn.textContent = '检查是否最新'; }
      };

      showOutline(c.id);
    } catch (e) { toast(e.message, true); }
  };

  // ---------- 结构 ----------
  const showOutline = async (id) => {
    const my = tbSeq;
    $('#tbOutline').innerHTML = '<div class="empty">加载中…</div>';
    try {
      const r = await api.get(`/api/textbook/${id}/outline`);
      if (my !== tbSeq || !$('#tbOutline')) return;
      if (!r.ok) { $('#tbOutline').innerHTML = `<div class="empty">${h(r.message)}</div>`; return; }
      const total = (r.chapters || []).reduce((a, c) => a + c.sections.length, 0);
      $('#tbOutline').innerHTML = `
        <div class="row" style="margin-bottom:12px;flex-wrap:wrap">
          <b>${h(r.title)}</b>
          <span class="pill">${h(r.volume || '')}</span>
          <span class="pill">${h(r.publisher)}</span>
          <span class="hint">${(r.chapters || []).length} 章 · ${total} 节</span>
          <div class="spacer"></div>
          ${(r.chapters || []).some(c => c.sections.some(x => !x.has_text))
            ? `<button class="btn sm" id="tbRefill" data-tb="${r.id}">补全正文</button>` : ''}
        </div>
        ${(r.chapters || []).map(c => `
          <div style="margin-bottom:12px">
            <div style="font-weight:600;font-size:13.5px;margin-bottom:6px">${h(c.chapter)}</div>
            ${c.sections.map(s => `
              <div class="row tb-sec" data-sec="${s.id}" data-text="${s.has_text ? 1 : 0}"
                   style="padding:5px 0 5px 14px;border-bottom:1px dashed #f4f6fb;font-size:12.5px;cursor:pointer">
                <span style="color:#5a6577">${s.has_text ? '📄' : '·'} ${h(s.section)}</span>
                <div class="spacer"></div>
                ${(s.kp_codes || []).map(k => `<span class="pill" style="font-size:10px">${h(k)}</span>`).join('')}
                ${s.chars ? `<span class="hint">${s.chars} 字</span>` : '<span class="hint">无正文</span>'}
              </div>`).join('')}
          </div>`).join('')}`;
      // 章节行 → 打开阅读器；补全正文 → 重解析回填
      $$('#tbOutline .tb-sec').forEach(row => {
        row.onclick = () => openReader(Number(row.dataset.sec));
      });
      const rf = $('#tbRefill');
      if (rf) rf.onclick = async () => {
        rf.disabled = true; rf.textContent = '解析中…';
        try {
          const res = await api.post(`/api/textbook/${rf.dataset.tb}/refill`);
          toast(res.message || '已处理');
          showOutline(Number(rf.dataset.tb));
        } catch (e) { toast(e.message, true); rf.disabled = false; rf.textContent = '补全正文'; }
      };
    } catch (e) { $('#tbOutline').innerHTML = `<div class="empty">${h(e.message)}</div>`; }
  };

  // ---------- 课本阅读器（离线读正文）----------
  const openReader = async (secId) => {
    const box = $('#tbReader');
    if (!box) return;
    box.style.display = 'block';
    box.innerHTML = '<div class="empty">加载正文…</div>';
    try {
      const r = await api.get('/api/textbook/section/' + secId);
      if (!$('#tbReader')) return;
      if (!r.ok) { box.innerHTML = `<div class="empty">${h(r.message)}</div>`; return; }
      box.innerHTML = `
        <h3>${h(r.chapter)} ${h(r.section)}
          <span class="tag">《${h(r.textbook)}》· ${r.chars} 字${r.has_full_text ? '' : '（仅摘录）'}</span>
          <div class="spacer"></div>
          ${r.prev ? `<button class="btn sm" id="tbPrev">上一节</button>` : ''}
          ${r.next ? `<button class="btn sm" id="tbNext">下一节</button>` : ''}
          <button class="btn sm ghost" id="tbClose">关闭</button></h3>
        <div class="doc-body" style="max-height:60vh;overflow:auto;white-space:pre-wrap;line-height:1.9">
${h(r.content || '（这一节没有正文，点上面的「补全正文」重新解析原文件）')}</div>
        <div class="hint" style="margin-top:10px">正文来自你本机导入的教材文件，只存在这台电脑上，不会上传。</div>`;
      $('#tbClose').onclick = () => { box.style.display = 'none'; box.innerHTML = ''; };
      if (r.prev) $('#tbPrev').onclick = () => openReader(r.prev.id);
      if (r.next) $('#tbNext').onclick = () => openReader(r.next.id);
      box.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      box.innerHTML = `<div class="empty">${h(e.message)}</div>`;
    }
  };

  // ---------- 上传 ----------
  // 粘贴正文 → 切章节入库
  $('#tbxGo').onclick = async () => {
    const text = $('#tbxText').value.trim();
    const title = $('#tbxTitle').value.trim() || '粘贴导入的教材';
    if (text.length < 80) return toast('正文太短，至少 80 字', true);
    const out = $('#tbxOut');
    out.innerHTML = '<div class="empty">切章节中…</div>';
    $('#tbxGo').disabled = true;
    try {
      const r = await api.post('/api/textbook/paste', {
        title, text, subject: TB_STATE.subject, stage: TB_STATE.stage,
        grade: $('#tbGrade').value,
      });
      if (!r.ok) { out.innerHTML = `<div class="empty">${h(r.message)}</div>`; return; }
      out.innerHTML = `<div class="insight"><div class="t">已入库</div>
        <div class="d">${h(r.message)} · 现在可以在下面「章节结构」里点开阅读</div></div>`;
      $('#tbxText').value = '';
      await loadEditions();     // 刷新版本列表
      showOutline(r.id);
      toast('已切成 ' + r.sections + ' 节');
    } catch (e) { out.innerHTML = `<div class="empty">${h(e.message)}</div>`; }
    finally { $('#tbxGo').disabled = false; }
  };

  $('#tbUpload').onclick = async () => {
    const f = $('#tbFile').files[0];
    if (!f) return toast('先选一个文件', true);
    const fd = new FormData();
    fd.append('file', f);
    fd.append('subject', TB_STATE.subject);
    fd.append('stage', TB_STATE.stage);
    fd.append('grade', $('#tbGrade').value);
    fd.append('volume', $('#tbVolume').value.trim());
    fd.append('edition_name', $('#tbEdName').value.trim());
    fd.append('edition_code', TB_STATE.pendingEdition || '');   // 从版本卡点进来的，挂到那个版本下
    const y = $('#tbEdYear').value.trim();
    if (y) fd.append('edition_year', y);
    $('#tbUpOut').innerHTML = '<div class="empty">解析中…（大 PDF 可能要十几秒）</div>';
    try {
      const res = await fetch('/api/textbook/upload', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + state.token },
        body: fd
      });
      const r = await res.json();
      if (!res.ok) throw new Error(r.detail || ('HTTP ' + res.status));
      $('#tbUpOut').innerHTML = `<div class="insight ${r.ok ? '' : 'high'}" style="margin-top:12px">
        <div class="t">${r.ok ? '✅ 解析完成' : '❌ 解析失败'}</div>
        <div class="d">${h(r.message || '')}</div></div>`;
      if (r.ok) {
        toast(r.message);
        TB_STATE.pendingEdition = '';
        TB_STATE.currentCode = '';
        await loadCurrent();     // 先刷新「当前」，再用新的 currentCode 重渲染版本卡（高亮才准）
        await loadEditions();
      }
    } catch (e) {
      $('#tbUpOut').innerHTML = `<div class="empty">${h(e.message)}</div>`;
    }
  };

  // ---------- 粘贴目录 ----------
  $('#tbPaste').onclick = async () => {
    const raw = $('#tbRaw').value.trim();
    if (!raw) return toast('目录内容为空', true);
    try {
      const r = await api.post('/api/textbook/outline', {
        subject: TB_STATE.subject, raw, title: $('#tbTitle').value.trim() || '自定义教材目录',
        stage: TB_STATE.stage, edition_code: TB_STATE.pendingEdition || '',
      });
      if (r.ok === false) return toast(r.message, true);
      $('#tbPasteOut').innerHTML = `<div class="insight" style="margin-top:12px"><div class="d">${h(r.message)}</div></div>`;
      toast(r.message);
      $('#tbRaw').value = '';
      TB_STATE.pendingEdition = '';
      TB_STATE.currentCode = '';
      await loadCurrent();
      await loadEditions();
    } catch (e) { toast(e.message, true); }
  };

  // ---------- 定位预览 ----------
  $('#tbMatch').onclick = () => {
    $('#tbDialog').innerHTML = `<div class="card" style="margin-top:16px">
      <h3>定位预览</h3>
      <p class="hint">输入你打算问的问题，看会命中课本哪几节（讲解时就是按这个定位）。</p>
      <div class="row">
        <input id="mtQ" type="text" placeholder="例如：二次函数顶点怎么求" style="flex:1" />
        <button class="btn primary" id="mtGo">预览</button>
      </div>
      <div id="mtOut"></div>
    </div>`;
    $('#mtGo').onclick = async () => {
      const q = $('#mtQ').value.trim();
      if (!q) return toast('先输入问题', true);
      try {
        const r = await api.get(`/api/textbook/match?subject=${TB_STATE.subject}&q=${encodeURIComponent(q)}`);
        if (!r.ok) { $('#mtOut').innerHTML = `<div class="empty">${h(r.message)}</div>`; return; }
        $('#mtOut').innerHTML = `<div class="insight" style="margin-top:12px">
          <div class="t">命中《${h(r.textbook)}》${h(r.volume || '')}</div>
          <div class="d">${(r.sections || []).map(s => '· ' + h(s)).join('<br>')}</div>
          <div class="a">识别到的知识点：${(r.kp_hints || []).map(k => h(k)).join('、') || '（无）'}</div>
        </div>`;
      } catch (e) { toast(e.message, true); }
    };
  };

  // 换科目/学段：作废在飞的旧请求，清掉上一科的残留，再按顺序重新拉
  const reloadFor = async () => {
    tbSeq++;
    TB_STATE.currentCode = '';
    TB_STATE.pendingEdition = '';
    if ($('#tbCur')) $('#tbCur').textContent = '';
    if ($('#tbLatest')) $('#tbLatest').innerHTML = '<div class="empty">加载中…</div>';
    if ($('#tbOutline')) $('#tbOutline').innerHTML = '<div class="empty">加载中…</div>';
    if ($('#tbDialog')) $('#tbDialog').innerHTML = '';
    await loadCurrent();   // 先确定"当前是哪本"，版本卡的高亮才对得上
    await loadEditions();
  };

  $('#tbStage').value = TB_STATE.stage;
  $('#tbStage').onchange = () => { TB_STATE.stage = $('#tbStage').value; reloadFor(); };
  $('#tbSubject').value = TB_STATE.subject;
  $('#tbSubject').onchange = () => { TB_STATE.subject = $('#tbSubject').value; reloadFor(); };

  // 先拿到「当前是哪本」，再渲染版本卡，否则高亮永远对不上
  await loadCurrent();
  await loadEditions();
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
  </div>

  <div class="card" id="imaCard" style="margin-top:16px">
    <h3>④ 教材知识库（IMA）<span class="tag">小学到大学的教材 · 只用来检索，不整本下载</span></h3>
    <p class="hint" style="margin:0 0 12px">
      IMA 里挂着从小学到大学的教材知识库。这里通过它的 MCP 接口做<b>检索</b>：
      讲解时把命中的片段当「课本口径」参考，<b>本地只缓存片段和出处</b>，不保存整本正文。
    </p>
    <div id="imaStatus" class="hint">读取中…</div>
    <div style="height:12px"></div>
    <div class="field"><label>IMA 访问令牌 / Cookie</label>
      <div class="row">
        <input id="imaToken" type="password" autocomplete="off" spellcheck="false"
               placeholder="粘贴后点保存，输入框会立即清空" style="flex:1" />
        <button class="btn" id="imaSave" type="button">保存</button>
      </div>
    </div>
    <p class="hint" style="margin:8px 0 0">
      <b>怎么拿</b>：浏览器打开 <span class="mono">ima.qq.com</span> 并登录 →
      <span class="mono">F12</span> → Network → 点任意 <span class="mono">cgi-bin/</span> 请求 →
      复制 Request Headers 里的 <span class="mono">X-Ima-Cookie</span> 整串粘进来即可
      （也支持只粘 <span class="mono">IMA-TOKEN</span> 的值）。令牌同样走 DPAPI 加密，只存本机。
    </p>
    <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:14px">
      <button class="btn primary" id="imaTest">测试连接（看有哪些工具）</button>
      <button class="btn" id="imaSync">一键同步本年级教材片段</button>
      <button class="btn ghost" id="imaClear" style="color:#b91c1c">清空本地片段</button>
      <label class="switch" style="margin-left:auto"><input type="checkbox" id="imaOn"><i></i></label>
      <span class="hint">对话时自动带教材摘录</span>
    </div>
    <div id="imaOut" style="margin-top:12px"></div>
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

  // ---------- 教材知识库（IMA） ----------
  const renderIma = (st) => {
    if (!$('#imaStatus')) return;
    const bits = [
      st.configured
        ? `<span class="pill ok">已配置</span> <span class="mono">${h(st.token_masked || '')}</span>`
        : '<span class="pill warn">未配置令牌</span>',
      `<span class="pill">接口 ${h(st.url || '')}</span>`,
      `<span class="pill">本地片段 ${st.cached_snippets || 0} 条</span>`,
    ];
    $('#imaStatus').innerHTML = bits.join(' ') +
      `<div class="hint" style="margin-top:6px">${h(st.note || '')}</div>`;
    if ($('#imaOn')) $('#imaOn').checked = !!st.enabled;
    if ($('#imaToken')) {
      $('#imaToken').value = '';
      $('#imaToken').placeholder = st.configured
        ? `已保存 ${st.token_masked || ''}，留空则不修改`
        : '粘贴 IMA access token';
    }
  };

  const loadIma = async () => {
    try {
      const st = await api.get('/api/ext/ima');
      if (!$('#imaStatus')) return;
      renderIma(st);
    } catch (e) {
      if ($('#imaStatus')) $('#imaStatus').textContent = '读取失败：' + e.message;
    }
  };

  $('#imaSave').onclick = async () => {
    const t = $('#imaToken').value.trim();
    $('#imaToken').value = '';
    $('#imaToken').type = 'password';
    if (!t) return toast('先粘贴令牌', true);
    try {
      const st = await api.post('/api/ext/ima/token', { token: t });
      renderIma(st);
      toast('已加密保存 IMA 令牌，建议点「测试连接」确认');
    } catch (e) { toast(e.message, true); }
  };

  $('#imaTest').onclick = async () => {
    const out = $('#imaOut');
    out.innerHTML = '<div class="empty">正在连接 IMA…</div>';
    try {
      const r = await api.post('/api/ext/ima/test');
      renderIma(r);
      const p = r.probe || {};
      const tools = (p.tools || []).map(t =>
        `<div class="kp-link"><b class="mono">${h(t.name)}</b>
           ${t.name === p.picked ? '<span class="pill ok">用作检索</span>' : ''}
           <div class="hint">${h(t.description || '')}
           ${t.args && t.args.length ? ` · 参数：${h(t.args.join(', '))}` : ''}</div></div>`).join('');
      out.innerHTML = `<div class="insight ${r.ok ? '' : 'high'}">
        <div class="t">${r.ok ? '✅ 连上了' : '❌ 连接不上'}</div>
        <div class="d">${h(p.server ? `服务端 ${p.server}` : '')}
          ${p.reason ? ` · ${h(p.reason)}` : ''}
          ${p.picked ? ` · 自动选中的检索工具：${h(p.picked)}` : ''}</div>
        ${tools ? `<div style="margin-top:8px">${tools}</div>` : ''}
      </div>`;
    } catch (e) {
      out.innerHTML = `<div class="empty">${h(e.message)}</div>`;
    }
  };

  $('#imaSync').onclick = async () => {
    const out = $('#imaOut');
    out.innerHTML = '<div class="empty">正在按知识点批量检索…（十几个查询，可能要几十秒）</div>';
    $('#imaSync').disabled = true;
    try {
      const r = await api.post('/api/ext/ima/sync', { stage: 'senior' });
      if (r.ok === false && r.message) {
        out.innerHTML = `<div class="insight high"><div class="d">${h(r.message)}</div></div>`;
      } else {
        out.innerHTML = `<div class="insight"><div class="t">同步结果</div>
          <div class="d">${h(r.message || '')}</div></div>`;
      }
      renderIma(r);
    } catch (e) {
      out.innerHTML = `<div class="empty">${h(e.message)}</div>`;
    } finally {
      $('#imaSync').disabled = false;
    }
  };

  $('#imaClear').onclick = async () => {
    if (!confirm('清空本地已缓存的教材片段？之后只能靠 IMA 实时检索。')) return;
    try {
      const st = await api.del('/api/ext/kb');
      renderIma(st);
      toast('已清空本地片段');
    } catch (e) { toast(e.message, true); }
  };

  $('#imaOn').onchange = async () => {
    try {
      const st = await api.post('/api/ext/ima/enabled', { enabled: $('#imaOn').checked });
      renderIma(st);
      toast(st.enabled ? '对话时会带教材摘录' : '已关闭教材摘录');
    } catch (e) { toast(e.message, true); }
  };

  loadIma();

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
/* 前端资源戳（后端注入的 mtime）：显示在侧栏版本号后面。
   出"还是老样子"时先看这四位——对不上就是浏览器还在跑旧缓存，刷新即可。 */
function _frontStamp() {
  try {
    const meta = document.querySelector('meta[name="front-stamp"]');
    const v = meta ? meta.content : '';
    return /^\d+$/.test(v) ? ' · ' + v.slice(-4) : '';
  } catch (e) { return ''; }
}

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
