'use strict';

const INDEXES = ['SPX', 'SPY', 'QQQ'];
const STOCK_SCOPE_AR = { near: 'أقرب انتهاء', '14d': '14 يوم', '45d': '45 يوم' };
const REFRESH_MS = 60 * 1000;

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* private mode */ } },
};

const state = {
  sym: store.get('sym', 'SPX'),
  scope: store.get('scope', ''),
  tab: store.get('tab', 'session'),
  sort: 'usd',
  index: null,
  data: {},
  error: null,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const fmt = {
  num(x, d = 2) {
    return x == null ? '—' : Number(x).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  },
  signed(x, d = 2) { return x == null ? '—' : (x >= 0 ? '+' : '−') + fmt.num(Math.abs(x), d); },
  strike(k) {
    if (k == null) return '—';
    const d = Number.isInteger(k) ? 0 : (Math.round(k * 10) === k * 10 ? 1 : 2);
    return fmt.num(k, d);
  },
  k(x) {
    if (x == null) return '—';
    if (x >= 1e6) return (x / 1e6).toFixed(2) + 'M';
    if (x >= 1e3) return (x / 1e3).toFixed(1) + 'K';
    return String(Math.round(x));
  },
  usd(x) {
    if (x == null) return '—';
    if (x >= 1e9) return '$' + (x / 1e9).toFixed(2) + 'B';
    if (x >= 1e6) return '$' + (x / 1e6).toFixed(1) + 'M';
    if (x >= 1e3) return '$' + (x / 1e3).toFixed(0) + 'K';
    return '$' + Math.round(x);
  },
  date(iso) { const [, m, d] = iso.split('-'); return `${m}/${d}`; },
};

async function getJSON(path) {
  const r = await fetch(`${path}?t=${Date.now()}`, { cache: 'no-store' });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function load() {
  try {
    state.index = await getJSON('data/index.json');
    const names = state.index.symbols.map((s) => s.symbol);
    if (!names.includes(state.sym)) state.sym = names[0];
    if (state.sym) state.data[state.sym] = await getJSON(`data/${state.sym}.json`);
    state.error = null;
  } catch (e) {
    state.error = 'تعذّر تحميل البيانات. أعد المحاولة بعد شوي.';
  }
  render();
}

function current() {
  const d = state.data[state.sym];
  if (!d || !d.scopes || !d.scopes.length) return { d, s: null };
  let s = d.scopes.find((x) => x.id === state.scope);
  if (!s) { s = d.scopes[0]; state.scope = s.id; }
  return { d, s };
}

function minutesAgo(iso) {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 60000));
}

function renderHeader(d, s) {
  $('tabName').textContent = `GAMMA · ${state.tab.toUpperCase()}`;
  $('spot').textContent = d ? fmt.num(d.spot, 2) : '—';
  const chg = $('chg');
  if (d && d.change != null) {
    chg.textContent = `${fmt.signed(d.change, 2)} (${fmt.signed(d.change_pct, 2)}%)`;
    chg.className = `mono small ${d.change >= 0 ? 'pos' : 'neg'}`;
  } else { chg.textContent = ''; }
  const built = state.index && state.index.built;
  const ago = built ? minutesAgo(built) : null;
  $('age').textContent = ago == null ? '' : (ago < 1 ? 'حُدّثت الحين' : `حُدّثت قبل ${ago} د`);

  const syms = state.index ? state.index.symbols : [];
  $('symbols').innerHTML = INDEXES.filter((n) => syms.some((x) => x.symbol === n))
    .map((n) => `<button type="button" class="pill" data-sym="${n}" aria-pressed="${n === state.sym}">${n}</button>`).join('');
  const stocks = syms.filter((x) => x.kind === 'stock').map((x) => x.symbol);
  const sel = $('stock');
  const isStock = stocks.includes(state.sym);
  sel.innerHTML = `<option value="">اختر سهم</option>` +
    stocks.map((n) => `<option value="${n}"${n === state.sym ? ' selected' : ''}>${n}</option>`).join('');
  sel.classList.toggle('on', isStock);

  $('scopes').innerHTML = d && d.scopes ? d.scopes.map((x) => {
    const label = d.kind === 'stock' ? (STOCK_SCOPE_AR[x.id] || x.label) : x.label;
    return `<button type="button" data-scope="${esc(x.id)}" aria-pressed="${s && x.id === s.id}" class="${d.kind === 'stock' ? 'ar' : ''}">${esc(label)}</button>`;
  }).join('') : '';
  $('expiries').textContent = s ? `EXP ${s.expiries.map(fmt.date).join(' · ')} · ${s.contracts} contracts` : '';

  document.querySelectorAll('#nav button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tab === state.tab)));
}

function session(d, s) {
  const regime = {
    positive: ['● POSITIVE GAMMA — MEAN REVERSION', 'قاما موجبة: السعر يميل يرتد بين الجدارين'],
    negative: ['● NEGATIVE GAMMA — AMPLIFIED MOVES', 'قاما سالبة: الحركة تتضخم وتتسارع'],
    unknown: ['● GAMMA — NO CLEAR READ', 'ما فيه قراءة واضحة'],
  }[s.regime] || ['', ''];
  const dist = (k) => (k == null ? '' : `${fmt.signed(k - d.spot, 1)} pts`);
  const flipSub = s.flip == null ? 'ما فيه انقلاب قريب' : (d.spot > s.flip ? 'السعر فوق الـ Flip' : 'السعر تحت الـ Flip');

  const rows = s.profile.rows;
  const maxAbs = rows.reduce((m, r) => Math.max(m, Math.abs(r.gex)), 0) || 1;
  const items = rows.map((r) => ({ kind: 'bar', key: r.k, r }));
  items.push({ kind: 'spot', key: d.spot });
  if (s.flip != null && rows.length && s.flip <= rows[0].k && s.flip >= rows[rows.length - 1].k) items.push({ kind: 'flip', key: s.flip });
  items.sort((a, b) => b.key - a.key);
  const prof = items.map((it) => {
    if (it.kind === 'spot') return '<div class="prow marker"><span class="k"></span><div class="line spot"></div><span class="tag blue">SPOT</span></div>';
    if (it.kind === 'flip') return '<div class="prow marker"><span class="k"></span><div class="line flip"></div><span class="tag amber">FLIP</span></div>';
    const r = it.r;
    const w = (Math.abs(r.gex) / maxAbs * 100).toFixed(1);
    const isCW = r.k === s.profile.cw_bin;
    const isPW = r.k === s.profile.pw_bin;
    const left = r.gex < 0 ? `<div class="b n" style="width:${w}%"></div>` : '';
    const right = r.gex > 0 ? `<div class="b p" style="width:${w}%"></div>` : '';
    const tag = isCW ? '<span class="tag pos">CW</span>' : (isPW ? '<span class="tag neg">PW</span>' : '<span class="tag"></span>');
    return `<div class="prow"><span class="k ${isCW ? 'cw' : isPW ? 'pw' : ''}">${fmt.strike(r.k)}</span>` +
      `<div class="bars"><div class="half l">${left}</div><div class="axis"></div><div class="half">${right}</div></div>${tag}</div>`;
  }).join('');

  return `
  <div class="grid2">
    <div class="card"><span class="label">NET GEX</span><span class="val ${s.net >= 0 ? 'pos' : 'neg'}">${fmt.signed(s.net, 2)}</span><span class="mono small muted">$bn / 1% move</span></div>
    <div class="card"><span class="label">FLIP</span><span class="val amber">${s.flip == null ? '—' : fmt.num(s.flip, 1)}</span><span class="ar small muted" dir="rtl">${flipSub}</span></div>
  </div>
  <div class="grid3">
    <div class="card"><span class="label">CALL WALL</span><span class="val sm pos">${fmt.strike(s.cw)}</span><span class="mono small muted">${dist(s.cw)}</span></div>
    <div class="card"><span class="label">PUT WALL</span><span class="val sm neg">${fmt.strike(s.pw)}</span><span class="mono small muted">${dist(s.pw)}</span></div>
    <div class="card"><span class="label">EXP MOVE</span><span class="val sm blue">${s.em == null ? '—' : '±' + fmt.num(s.em, s.em < 10 ? 2 : 0)}</span><span class="mono small muted">${s.em_pct == null ? '' : s.em_pct.toFixed(2) + '%'}</span></div>
  </div>
  <div class="regime ${esc(s.regime)}"><span class="t">${regime[0]}</span><span class="d" dir="rtl">${regime[1]}</span></div>
  <section class="card" aria-label="GEX profile">
    <div class="row between"><span class="label">GEX PROFILE · NET $ PER 1%</span><span class="bin">${s.profile.bin == null ? '' : fmt.strike(s.profile.bin) + '-pt bins'}</span></div>
    ${rows.length ? prof : '<div class="empty">ما فيه بيانات قاما لهذا الاستحقاق</div>'}
    <div class="prow"><span class="k"></span><div class="bars mono small muted" style="justify-content:space-between"><span>−${maxAbs.toFixed(2)}bn</span><span>0</span><span>+${maxAbs.toFixed(2)}bn</span></div><span class="tag"></span></div>
    <div class="legend"><span class="blue">— SPOT ${fmt.num(d.spot, 2)}</span>${s.flip == null ? '' : `<span class="amber">- - FLIP ${fmt.num(s.flip, 1)}</span>`}</div>
  </section>`;
}

function levels(d, s) {
  if (!s.levels.length) return '<div class="empty">ما فيه مستويات لهذا الاستحقاق</div>';
  const nearest = s.levels.reduce((b, r) => (Math.abs(r.k - d.spot) < Math.abs(b.k - d.spot) ? r : b), s.levels[0]);
  const rows = s.levels.map((r) => {
    const tag = r.k === s.cw ? '<span class="pos" style="font-size:9.5px;font-weight:700">CW</span>' : (r.k === s.pw ? '<span class="neg" style="font-size:9.5px;font-weight:700">PW</span>' : '');
    return `<div class="tr lv${r === nearest ? ' near' : ''}"><span style="color:#E7EDF3">${fmt.strike(r.k)} ${tag}</span>` +
      `<span class="r ${r.gex >= 0 ? 'pos' : 'neg'}">${fmt.signed(r.gex, 1)}</span><span class="r">${fmt.k(r.oi)}</span>` +
      `<span class="r">${fmt.k(r.vol)}</span><span class="r">${r.iv == null ? '—' : r.iv.toFixed(1) + '%'}</span></div>`;
  }).join('');
  return `
  <div class="row between"><span class="label">TOP 10 STRIKES BY |GEX|</span><span class="ar small muted" dir="rtl">المظلل الأقرب للسعر</span></div>
  <div class="table"><div class="tr lv head"><span>STRIKE</span><span class="r">GEX $M</span><span class="r">OI</span><span class="r">VOL</span><span class="r">IV</span></div>${rows}</div>
  <p class="note" dir="rtl">CW أكبر قاما موجبة، و PW أكبر قاما سالبة. الموجب يثبّت السعر غالبًا، والسالب يضخّم الحركة.</p>`;
}

function flowView(d, s) {
  const f = s.flow;
  const sorts = [['usd', '$ Notional'], ['vol', 'Volume'], ['voi', 'Vol/OI']];
  const many = s.expiries.length > 1;
  const rows = (f.top[state.sort] || []).map((r) => {
    const voi = r.voi == null ? 'NEW' : r.voi.toFixed(1) + '×';
    const hot = r.voi == null || r.voi > 1;
    return `<div class="tr fl"><span class="row gap" style="gap:6px"><span style="color:#E7EDF3">${fmt.strike(r.k)}</span>` +
      `<span class="side ${r.side}">${r.side}</span><span class="small muted">${many ? fmt.date(r.exp) : (r.itm ? 'ITM' : 'OTM')}</span></span>` +
      `<span class="r">${fmt.k(r.vol)}</span><span class="r ${hot ? 'amber' : ''}">${voi}</span><span class="r">${fmt.usd(r.usd)}</span></div>`;
  }).join('');
  return `
  <div class="grid2">
    <div class="card"><span class="label">CALL VOL</span><span class="val pos" style="font-size:20px">${fmt.k(f.call_vol)}</span></div>
    <div class="card"><span class="label">PUT VOL</span><span class="val neg" style="font-size:20px">${fmt.k(f.put_vol)}</span></div>
    <div class="card"><span class="label">P / C</span><span class="val amber" style="font-size:20px">${f.pc == null ? '—' : f.pc.toFixed(2)}</span></div>
    <div class="card"><span class="label">TOTAL $</span><span class="val blue" style="font-size:20px">${fmt.usd(f.usd)}</span></div>
  </div>
  <div class="seg" role="group" aria-label="الترتيب">${sorts.map(([k, n]) => `<button type="button" data-sort="${k}" aria-pressed="${k === state.sort}">${n}</button>`).join('')}</div>
  <div class="table"><div class="tr fl head"><span>STRIKE</span><span class="r">VOL</span><span class="r">V/OI</span><span class="r">$</span></div>${rows || '<div class="empty">ما فيه تداول لهذا الاستحقاق</div>'}</div>
  <p class="note" dir="rtl">V/OI فوق 1× يعني حجم اليوم تجاوز العقود المفتوحة، وهذا غالبًا تموضع جديد. NEW = ما كان عليه عقود مفتوحة.</p>`;
}

function render() {
  const { d, s } = current();
  renderHeader(d, s);
  const main = $('main');
  let html = '';
  if (state.error) html += `<p class="warn" dir="rtl">${esc(state.error)}</p>`;
  if (d && d.stale) html += '<p class="warn" dir="rtl">آخر جلب لهذا الرمز ما نجح، المعروض آخر بيانات سليمة.</p>';
  if (!d || !s) {
    html += state.index ? '<div class="empty">ما فيه بيانات لهذا الرمز الحين</div>' : '<div class="empty">جاري التحميل…</div>';
  } else if (state.tab === 'levels') {
    html += levels(d, s);
  } else if (state.tab === 'flow') {
    html += flowView(d, s);
  } else {
    html += session(d, s);
  }
  const asof = d && d.asof ? `بيانات Cboe: ${esc(d.asof)}` : '';
  html += `<p class="note" dir="rtl">${asof}${asof ? ' · ' : ''}للتعليم والمعلومات فقط، وليست توصية. حسبة القاما تفترض إن صناع السوق شارين الكول وبايعين البوت.</p>`;
  main.innerHTML = html;
}

async function pick(sym) {
  state.sym = sym;
  store.set('sym', sym);
  if (!state.data[sym]) {
    render();
    try { state.data[sym] = await getJSON(`data/${sym}.json`); } catch { state.error = 'تعذّر تحميل البيانات.'; }
  }
  render();
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.sym) pick(b.dataset.sym);
  else if (b.dataset.scope) { state.scope = b.dataset.scope; store.set('scope', state.scope); render(); }
  else if (b.dataset.tab) { state.tab = b.dataset.tab; store.set('tab', state.tab); render(); window.scrollTo(0, 0); }
  else if (b.dataset.sort) { state.sort = b.dataset.sort; render(); }
});
document.getElementById('stock').addEventListener('change', (e) => { if (e.target.value) pick(e.target.value); });

load();
setInterval(load, REFRESH_MS);
