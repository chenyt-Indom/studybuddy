/* 手写 SVG 图表 —— 不引 CDN，避免断网/被墙时整页空白 */
(function () {
  const C = {
    brand: '#3b5bfd', brandSoft: 'rgba(59,91,253,.12)',
    ok: '#16a34a', warn: '#f59e0b', bad: '#dc2626',
    line: '#e6eaf2', grid: '#f0f3f9', ink3: '#8d97a8'
  };
  const SUBJ_COLOR = {
    math: '#3b5bfd', physics: '#8b5cf6', chemistry: '#0ea5e9',
    biology: '#16a34a', chinese: '#ef4444', english: '#f59e0b'
  };
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));

  function empty(text) {
    return `<div class="empty">${esc(text)}</div>`;
  }

  /* ---------- 折线图 ---------- */
  function lineChart(data, opt = {}) {
    if (!data || !data.length) return empty(opt.emptyText || '还没有数据');
    const w = opt.w || 560, h = opt.h || 200;
    const pad = { l: 38, r: 14, t: 14, b: 26 };
    const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
    const vals = data.map(d => d.value);
    let min = opt.yMin != null ? opt.yMin : Math.min(...vals);
    let max = opt.yMax != null ? opt.yMax : Math.max(...vals);
    if (max - min < 6) { max = min + 6; }
    const x = i => pad.l + (data.length === 1 ? iw / 2 : (i * iw) / (data.length - 1));
    const y = v => pad.t + ih - ((v - min) / (max - min)) * ih;

    let g = '';
    for (let i = 0; i <= 4; i++) {
      const v = min + ((max - min) * i) / 4;
      const yy = y(v);
      g += `<line class="gridline" x1="${pad.l}" y1="${yy}" x2="${w - pad.r}" y2="${yy}"/>`;
      g += `<text x="${pad.l - 7}" y="${yy + 3}" text-anchor="end">${Math.round(v)}</text>`;
    }
    const pts = data.map((d, i) => `${x(i)},${y(d.value)}`).join(' ');
    const area = `${pad.l},${pad.t + ih} ${pts} ${x(data.length - 1)},${pad.t + ih}`;
    let dots = data.map((d, i) => `<circle cx="${x(i)}" cy="${y(d.value)}" r="3.2" fill="#fff" stroke="${C.brand}" stroke-width="2"><title>${esc(d.label)}: ${d.value}</title></circle>`).join('');
    let labels = data.map((d, i) => {
      if (data.length > 7 && i % Math.ceil(data.length / 6) !== 0 && i !== data.length - 1) return '';
      return `<text x="${x(i)}" y="${h - 8}" text-anchor="middle">${esc((d.label || '').slice(0, 8))}</text>`;
    }).join('');

    return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
      <defs><linearGradient id="lg1" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${C.brand}" stop-opacity=".18"/>
        <stop offset="100%" stop-color="${C.brand}" stop-opacity="0"/>
      </linearGradient></defs>
      ${g}
      <polygon points="${area}" fill="url(#lg1)"/>
      <polyline points="${pts}" fill="none" stroke="${C.brand}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
      ${dots}${labels}
    </svg>`;
  }

  /* ---------- 雷达图 ---------- */
  function radarChart(items, opt = {}) {
    if (!items || items.length < 3) return empty(opt.emptyText || '至少需要 3 个科目才有雷达图');
    const size = opt.size || 260, cx = size / 2, cy = size / 2, R = size / 2 - 34;
    const n = items.length;
    const ang = i => -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const pt = (i, r) => [cx + Math.cos(ang(i)) * r, cy + Math.sin(ang(i)) * r];

    let rings = '';
    for (let k = 1; k <= 4; k++) {
      const r = (R * k) / 4;
      const poly = items.map((_, i) => pt(i, r).join(',')).join(' ');
      rings += `<polygon points="${poly}" fill="none" stroke="${C.grid}"/>`;
    }
    let axes = items.map((_, i) => {
      const [x, y] = pt(i, R);
      return `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="${C.grid}"/>`;
    }).join('');

    const poly = items.map((it, i) => pt(i, Math.max(0.02, Math.min(1, it.mastery)) * R).join(',')).join(' ');
    let labels = items.map((it, i) => {
      const [x, y] = pt(i, R + 15);
      return `<text x="${x}" y="${y + 3}" text-anchor="middle" fill="${C.ink3}">${esc(it.subject_cn)} ${Math.round(it.mastery * 100)}%</text>`;
    }).join('');
    let dots = items.map((it, i) => {
      const [x, y] = pt(i, Math.max(0.02, Math.min(1, it.mastery)) * R);
      return `<circle cx="${x}" cy="${y}" r="3" fill="${C.brand}"/>`;
    }).join('');

    return `<svg class="chart" viewBox="0 0 ${size} ${size}" style="max-width:${size}px;margin:0 auto">
      ${rings}${axes}
      <polygon points="${poly}" fill="${C.brandSoft}" stroke="${C.brand}" stroke-width="2"/>
      ${dots}${labels}
    </svg>`;
  }

  /* ---------- 条形图 ---------- */
  function barChart(items, opt = {}) {
    if (!items || !items.length) return empty(opt.emptyText || '还没有数据');
    const w = opt.w || 560, rowH = opt.rowH || 30, pad = { l: opt.labelW || 96, r: 46, t: 6, b: 6 };
    const h = pad.t + pad.b + items.length * rowH;
    const iw = w - pad.l - pad.r;
    const max = opt.max || Math.max(...items.map(i => i.value), 1);

    let rows = items.map((it, i) => {
      const y = pad.t + i * rowH;
      const bw = Math.max(2, (it.value / max) * iw);
      const col = it.color || C.brand;
      return `
        <text x="${pad.l - 10}" y="${y + rowH / 2 + 4}" text-anchor="end" fill="#5a6577">${esc(it.label)}</text>
        <rect x="${pad.l}" y="${y + rowH / 2 - 7}" width="${iw}" height="14" rx="7" fill="#f1f4fa"/>
        <rect x="${pad.l}" y="${y + rowH / 2 - 7}" width="${bw}" height="14" rx="7" fill="${col}"/>
        <text x="${pad.l + iw + 8}" y="${y + rowH / 2 + 4}" fill="#5a6577">${esc(it.text != null ? it.text : Math.round(it.value * 100) + '%')}</text>`;
    }).join('');

    return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">${rows}</svg>`;
  }

  /* ---------- 遗忘曲线 ---------- */
  function curveChart(points, opt = {}) {
    if (!points || !points.length) return empty('该知识点还没有复习记录');
    const w = opt.w || 520, h = opt.h || 190;
    const pad = { l: 34, r: 14, t: 12, b: 24 };
    const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
    const maxDay = points[points.length - 1].day || 1;
    const x = d => pad.l + (d / maxDay) * iw;
    const y = v => pad.t + ih - v * ih;

    let g = '';
    [0, 0.25, 0.5, 0.75, 1].forEach(v => {
      g += `<line class="gridline" x1="${pad.l}" y1="${y(v)}" x2="${w - pad.r}" y2="${y(v)}"/>`;
      g += `<text x="${pad.l - 6}" y="${y(v) + 3}" text-anchor="end">${Math.round(v * 100)}%</text>`;
    });
    // 50% 危险线
    g += `<line x1="${pad.l}" y1="${y(0.5)}" x2="${w - pad.r}" y2="${y(0.5)}" stroke="${C.warn}" stroke-width="1" stroke-dasharray="4 3"/>`;
    g += `<text x="${w - pad.r}" y="${y(0.5) - 5}" text-anchor="end" fill="${C.warn}">遗忘警戒线 50%</text>`;

    const pts = points.map(p => `${x(p.day)},${y(p.strength)}`).join(' ');
    const area = `${pad.l},${pad.t + ih} ${pts} ${x(maxDay)},${pad.t + ih}`;
    let ticks = '';
    for (let d = 0; d <= maxDay; d += Math.max(1, Math.round(maxDay / 5))) {
      ticks += `<text x="${x(d)}" y="${h - 6}" text-anchor="middle">${d}天</text>`;
    }

    return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">
      <defs><linearGradient id="lg2" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#3b5bfd" stop-opacity=".2"/>
        <stop offset="100%" stop-color="#3b5bfd" stop-opacity="0"/>
      </linearGradient></defs>
      ${g}<polygon points="${area}" fill="url(#lg2)"/>
      <polyline points="${pts}" fill="none" stroke="${C.brand}" stroke-width="2.2"/>
      ${ticks}
    </svg>`;
  }

  /* ---------- 知识图谱（力导向的简化版：按科目分列） ---------- */
  function graphChart(nodes, edges, opt = {}) {
    if (!nodes || !nodes.length) return empty('没有跨科关联数据');
    const w = opt.w || 720, h = opt.h || 380;
    const groups = {};
    nodes.forEach(n => { (groups[n.subject_cn] = groups[n.subject_cn] || []).push(n); });
    const keys = Object.keys(groups);
    const pos = {};
    keys.forEach((k, ci) => {
      const arr = groups[k];
      const colW = w / keys.length;
      const cx = colW * ci + colW / 2;
      arr.forEach((n, i) => {
        const gap = Math.min(48, (h - 60) / Math.max(arr.length, 1));
        pos[n.id] = { x: cx, y: 50 + i * gap, node: n };
      });
    });

    let lines = (edges || []).map(e => {
      const a = pos[e.source], b = pos[e.target];
      if (!a || !b) return '';
      const weak = a.node.mastery < 0.5 || b.node.mastery < 0.5;
      return `<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"
        stroke="${weak ? C.bad : '#c7d0e2'}" stroke-width="${weak ? 1.8 : 1.2}"
        stroke-dasharray="${weak ? '5 3' : '0'}" opacity=".75">
        <title>${esc(a.node.name)} → ${esc(b.node.name)}（${esc(e.relation_cn)}）</title></line>`;
    }).join('');

    let dots = Object.values(pos).map(p => {
      const n = p.node;
      const col = SUBJ_COLOR[n.subject] || C.brand;
      const r = 7 + (n.has_record ? 2 : 0);
      return `<g><circle cx="${p.x}" cy="${p.y}" r="${r}" fill="${n.has_record ? col : '#fff'}"
        stroke="${col}" stroke-width="2" opacity="${n.has_record ? .95 : .5}">
        <title>${esc(n.name)}（${esc(n.subject_cn)}）掌握度 ${Math.round(n.mastery * 100)}%</title></circle>
        <text x="${p.x + r + 5}" y="${p.y + 3.5}" fill="#5a6577">${esc(n.name)}</text></g>`;
    }).join('');

    let titles = keys.map((k, ci) => {
      const colW = w / keys.length;
      return `<text x="${colW * ci + colW / 2}" y="20" text-anchor="middle" fill="${SUBJ_COLOR[(groups[k][0] || {}).subject] || C.brand}" style="font-weight:600">${esc(k)}</text>`;
    }).join('');

    return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet">${lines}${dots}${titles}</svg>`;
  }

  window.Charts = { lineChart, radarChart, barChart, curveChart, graphChart, SUBJ_COLOR, empty };
})();
