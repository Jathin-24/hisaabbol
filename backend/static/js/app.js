import { t, setLang, getLang, LANGS } from './i18n.js';
import { api, ApiErr, session, outbox, native } from './api.js';
import { Recorder, toWav } from './recorder.js';

// ───────────────────────────── helpers
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const inr = p => '₹' + (p / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const inr0 = p => '₹' + Math.round(p / 100).toLocaleString('en-IN');
const monthName = m => new Date(m + '-15').toLocaleDateString('en-IN', { month: 'long', year: 'numeric' });
const rupeesToPaise = v => Math.round(parseFloat(v) * 100);
const I = {
  home: '<svg viewBox="0 0 24 24"><path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>',
  list: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/></svg>',
  mic: '<svg viewBox="0 0 24 24"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg>',
};
const CAT_ICON = { 'Food & Dining': '🍽️', Groceries: '🥬', Transport: '🛺', Fuel: '⛽', 'Bills & Recharge': '📱', Shopping: '🛍️', Health: '💊', Entertainment: '🎬', Education: '📚', 'Rent & Home': '🏠', 'Personal Care': '💈', Travel: '🧳', 'Gifts & Donations': '🎁', 'Lent (udhaar)': '🤝', Repaid: '↩️', 'Family & Friends': '👪', Other: '🔹', Income: '💰' };
const CAT_COLOR = { 'Food & Dining': '#e8590c', Groceries: '#2f9e44', Transport: '#1c7ed6', Fuel: '#f08c00', 'Bills & Recharge': '#7048e8', Shopping: '#d6336c', Health: '#e03131', Entertainment: '#ae3ec9', Education: '#0c8599', 'Rent & Home': '#5c7cfa', 'Personal Care': '#e599f7', Travel: '#20c997', 'Gifts & Donations': '#f06595', 'Lent (udhaar)': '#868e96', Repaid: '#868e96', 'Family & Friends': '#fd7e14', Other: '#adb5bd', Income: '#2b8a3e' };
const catColor = c => CAT_COLOR[c] || '#868e96';
const bubble = c => `<div class="ico" style="--c:${catColor(c)}">${CAT_ICON[c] || '🔹'}</div>`;
const PALETTE = ['#d9480f', '#0f766e', '#4f46e5', '#e11d48', '#15803d', '#9333ea', '#ca8a04', '#0369a1', '#be185d', '#475569', '#65a30d', '#c2410c'];
const ACCENTS = { Marigold: '#d9480f', Teal: '#0f766e', Indigo: '#4f46e5', Rose: '#e11d48', Forest: '#15803d', Plum: '#9333ea' };
const SPEAK = [['hi-IN,en-IN', 'हिन्दी + English'], ['te-IN,en-IN', 'తెలుగు + English'], ['ta-IN,en-IN', 'தமிழ் + English'], ['kn-IN,en-IN', 'ಕನ್ನಡ + English'], ['ml-IN,en-IN', 'മലയാളം + English'],
  ['bn-IN,en-IN', 'বাংলা + English'], ['mr-IN,en-IN', 'मराठी + English'], ['gu-IN,en-IN', 'ગુજરાતી + English'], ['pa-IN,en-IN', 'ਪੰਜਾਬੀ + English'], ['en-IN', 'English only'], ['indic-auto', 'Detect automatically']];
const PERSON_CHIPS = [['Rent & Home', 'rent'], ['Family & Friends', 'family'], ['Lent (udhaar)', 'lent'], ['Repaid', 'repaying'], ['Gifts & Donations', 'gift']];

// ───────────────────────────── prefs (device-local look & feel)
const prefs = Object.assign({ theme: 'auto', accent: 'Marigold', ui: 'en', compact: false, onboarded: false, name: '' }, JSON.parse(localStorage.getItem('hb_prefs') || '{}'));
const savePrefs = () => localStorage.setItem('hb_prefs', JSON.stringify(prefs));
function applyPrefs() {
  const r = document.documentElement; r.dataset.theme = prefs.theme;
  const a = ACCENTS[prefs.accent] || ACCENTS.Marigold; r.style.setProperty('--accent', a);
  r.style.setProperty('--accent-soft', `color-mix(in srgb, ${a} 14%, var(--surface))`);
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', a);
  document.body.classList.toggle('compact', !!prefs.compact); setLang(prefs.ui);
}
function savedMessage(tx) {
  const labels = tx.items.map(i => i.label).filter(Boolean);
  const purpose = labels.length > 1 ? labels.slice(0, 2).join(' + ') : labels[0] || tx.items[0]?.category || t('expenses');
  return t(tx.direction === 'credit' ? 'loggedIncome' : 'loggedExpense', { amount: inr(tx.amount_paise), purpose });
}

// ───────────────────────────── state & ui primitives
const S = { settings: null, cats: [], pending: [], month: null, C: null, rid: 0 };
let toastT;
function toast(msg, err, action) {
  $('.toast')?.remove(); const d = document.createElement('div'); d.className = 'toast' + (err ? ' err' : ''); d.setAttribute('role', 'status');
  const sp = document.createElement('span'); sp.textContent = msg; d.append(sp);
  if (action) { const b = document.createElement('button'); b.textContent = action.label; b.onclick = () => { d.remove(); action.fn(); }; d.append(b); }
  document.body.append(d); clearTimeout(toastT); toastT = setTimeout(() => d.remove(), action ? 7000 : err ? 5000 : 2800);
}
function sheet(html, onClose) {
  const bg = document.createElement('div'); bg.className = 'sheet-bg'; bg.innerHTML = `<div class="sheet" role="dialog" aria-modal="true"><div class="grab"></div>${html}</div>`;
  const close = () => { bg.remove(); onClose?.(); }; bg.addEventListener('click', e => { if (e.target === bg) close(); }); bg.close = close; document.body.append(bg); return bg;
}
const dayLabel = iso => { const d = new Date(iso), n = new Date(), y = new Date(Date.now() - 864e5); const same = (a, b) => a.toDateString() === b.toDateString(); return same(d, n) ? 'Today' : same(d, y) ? 'Yesterday' : d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }); };
const dateKeyInZone = (date, timeZone) => {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(date).map(({ type, value }) => [type, value]));
  return `${parts.year}-${parts.month}-${parts.day}`;
};
const timeLabel = iso => new Date(iso).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' });
const skeleton = () => '<div class="card"><div class="skel" style="width:40%"></div><div class="skel" style="height:40px;width:70%"></div></div><div class="card"><div class="skel"></div><div class="skel"></div><div class="skel"></div></div>';
const empty = (emoji, title, body = '') => `<div class="empty"><div class="e">${emoji}</div><h3>${esc(title)}</h3><p class="sm">${esc(body)}</p></div>`;
const catPick = (cur, cb) => {
  const s = sheet(`<h2>Category</h2><div class="chips" style="margin-top:12px">${S.cats.map(c => `<button class="chip ${c === cur ? 'on' : ''}" data-cat="${esc(c)}">${CAT_ICON[c] || ''} ${esc(c)}</button>`).join('')}</div>`);
  s.addEventListener('click', e => { const b = e.target.closest('[data-cat]'); if (b) { s.close(); cb(b.dataset.cat); } });
};
const txRow = x => `<button class="tx" data-act="tx" data-id="${x.id}">${bubble(x.items[0].category)}<div class="grow"><div><b>${esc(x.items.length > 1 ? x.items.map(i => i.label).join(' + ') : x.items[0].label)}</b>${x.needs_review ? ` <span class="pill acc">${t('review')}</span>` : ''}</div>
  <div class="sm mut">${esc(x.counterparty && x.counterparty.toLowerCase() !== x.items[0].label.toLowerCase() ? x.counterparty : x.items[0].category)} · ${timeLabel(x.occurred_at)}</div></div><div class="amt ${x.direction === 'credit' ? 'in' : ''}">${x.direction === 'credit' ? '+' : ''}${inr(x.amount_paise)}</div></button>`;

// ───────────────────────────── boot & router
async function ensureSession() {
  if (!session.token) {
    const key = await native.requestRegistrationKey();
    const headers = key ? { 'X-Registration-Key': key } : {};
    const r = await api('/auth/register', { json: { name: prefs.name || 'device' }, headers }); session.token = r.token;
  }
  native.send({ type: 'session', token: session.token, base: location.origin });
}
async function loadCore() {
  const [me, c] = await Promise.all([api('/me'), api('/categories')]);
  S.settings = me.settings; S.cats = c.all; if (me.settings.ui_lang !== prefs.ui) api('/settings', { method: 'PUT', json: { ui_lang: prefs.ui } }).catch(() => {});
}
async function boot() {
  applyPrefs(); showLock();
  native.on(m => { if (m.type === 'open_capture') location.hash = '#/capture/' + m.id; if (m.type === 'navigate' && /^#\/[a-z]+$/.test(m.hash || '')) location.hash = m.hash; if (m.type === 'back') goBack(); if (m.type === 'notif_status' && /^#\/(home|more|onboarding)/.test(location.hash)) route(); });
  try { await ensureSession(); await loadCore(); } catch (e) {
    if (e instanceof ApiErr && e.code === 'registration_closed') native.send({ type: 'registration_rejected' });
    $('#view').innerHTML = empty('⚠️', 'Can’t reach the server', e.message); return;
  }
  const q = new URLSearchParams(location.search).get('capture');
  if (q) { history.replaceState(null, '', location.pathname); location.hash = '#/capture/' + q; }
  else if (prefs.onboarded && !location.hash) {
    try {
      const pending = await api('/captures?status=pending');
      const next = pending.items.filter(c => c.direction === 'debit')
        .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at))[0];
      if (next) location.hash = '#/capture/' + next.id;
    } catch { /* the home screen still provides the pending list when online */ }
  }
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) navigator.serviceWorker.register('/sw.js').catch(() => {});
  S.demo = !!(await fetch('/api/v1/health').then(r => r.json()).catch(() => ({}))).demo_enabled; sendDigest();
  native.send({ type: 'get_notif_status' });
  window.addEventListener('hashchange', route); window.addEventListener('online', syncBadge); window.addEventListener('offline', syncBadge);
  window.addEventListener('hb-synced', e => { toast(`Synced ${e.detail} offline ${e.detail > 1 ? 'entries' : 'entry'}`); route(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) { outbox.flush(); refreshPending(); } });
  setInterval(refreshPending, 15000); outbox.flush();
  native.send({ type: 'web_ready' });
  if (!prefs.onboarded) location.hash = '#/onboarding';
  route();
}
function sendDigest() { if (S.settings) native.send({ type: 'digest', time: S.settings.digest_time }); }
function goBack() {
  const sh = [...document.querySelectorAll('.sheet-bg')].pop(); if (sh) return sh.close ? sh.close() : sh.remove();
  if ($('.cap')) return ACT['cap-close']();
  if ($('.lock')) return;
  if (!/^#\/(home)?$/.test(location.hash)) { location.hash = '#/home'; return; }
  native.send({ type: 'exit' });
}
async function refreshPending() {
  try { const r = await api('/captures?status=pending'); const was = S.pending.length; S.pending = r.items.filter(c => c.direction === 'debit'); syncBadge(); if (S.pending.length !== was && /^#\/(home)?$/.test(location.hash || '#/')) route(); } catch { /* offline */ }
}
function syncBadge() {
  const b = $('#nav-badge'); if (b) { b.textContent = S.pending.length; b.classList.toggle('hide', !S.pending.length); }
  const d = $('#net'); if (d) d.className = 'dot' + (navigator.onLine ? '' : ' off'); const o = $('#offline'); if (o) o.classList.toggle('hide', navigator.onLine);
}
const ROUTES = { home, activity, report, more, udhaar, budgets, shops, settings, diagnostics, privacy, onboarding };
async function route() {
  const h = (location.hash || '#/home').replace(/^#\/?/, ''); const [name, arg] = h.split('/'); const id = ++S.rid;
  $('.cap')?.remove(); document.querySelectorAll('.sheet-bg').forEach(x => x.remove());
  const showNav = name !== 'onboarding'; $('nav.tabs').classList.toggle('hide', !showNav);
  document.querySelectorAll('nav.tabs [data-go]').forEach(b => b.classList.toggle('on', b.dataset.go === (['udhaar', 'budgets', 'shops', 'settings', 'diagnostics', 'privacy'].includes(name) ? 'more' : name || 'home')));
  if (name === 'capture') return renderCapture(arg);
  const fn = ROUTES[name || 'home'] || home; $('#view').innerHTML = skeleton();
  try { const html = await fn(arg); if (id === S.rid) { $('#view').innerHTML = html; window.scrollTo(0, 0); syncBadge(); afterRender(name); } }
  catch (e) { if (id === S.rid) $('#view').innerHTML = empty('⚠️', 'Something went wrong', e.message) + `<button class="full" data-act="reload">${t('ok')}</button>`; }
}
function afterRender() { /* hook for page-specific wiring */ }

// ───────────────────────────── HOME
async function home() {
  const [rep, tx, caps, rem] = await Promise.all([api(`/reports/monthly?language=${prefs.ui}`), api('/transactions?limit=5'), api('/captures?status=pending'), api('/udhaar/reminders').catch(() => ({ items: [] }))]);
  S.pending = caps.items.filter(c => c.direction === 'debit'); syncBadge();
  const v = rep.vs_last_month, ob = rep.budgets.find(b => !b.category);
  const todayKey = dateKeyInZone(new Date(), S.settings.tz);
  const todaySpent = rep.daily.find(d => d.date === todayKey)?.amount_paise || 0;
  const hero = `<div class="card accent"><div class="sm mut">${monthName(rep.month)} · ${t('spentMonth')}</div><div class="big">${inr(rep.total_spent_paise)}</div>
    ${v.delta_pct == null ? '' : `<div style="margin-top:10px"><span class="pill">${v.delta_pct > 0 ? '▲' : '▼'} ${Math.abs(v.delta_pct)}% ${t('vsLast')}</span></div>`}
    ${ob ? `<div class="bar" style="margin-top:16px;background:rgba(255,255,255,.25)"><i style="width:${Math.min(100, ob.percent)}%;background:#fff"></i></div><div class="xs" style="margin-top:4px">${ob.percent}% · ${inr(ob.limit_paise)}</div>` : ''}</div>`;
  const todayCard = `<div class="card flat row between"><span class="sm mut">${t('spentToday')}</span><b class="amt">${inr(todaySpent)}</b></div>`;
  const pend = S.pending.length ? `<div class="card"><h2>${t('needsNote')} <span class="pill acc">${S.pending.length}</span></h2><div class="list" style="margin-top:6px">${S.pending.slice(0, 3).map(c => `<div class="row between"><div><b>${inr(c.amount_paise)}</b> <span class="mut">${esc(c.counterparty || '—')}</span><div class="xs mut">${dayLabel(c.occurred_at)} · ${timeLabel(c.occurred_at)}</div></div><button class="primary" data-act="open-cap" data-id="${c.id}">🎙️ ${t('sayIt')}</button></div>`).join('')}</div>${S.pending.length > 3 ? `<button class="ghost full" data-go="activity">${t('seeAll')}</button>` : ''}</div>` : '';
  const reminders = rem.items.length ? `<div class="card flat"><b>🔔 ${t('reminders')}</b><div class="list" style="margin-top:4px">${rem.items.slice(0, 3).map(r => `<div class="row between sm"><span>${esc(r.message)}</span><button class="ghost" style="min-height:0;padding:4px 8px" data-go="udhaar">›</button></div>`).join('')}</div></div>` : '';
  const recent = tx.total ? `<div class="card"><div class="row between"><h2>${t('recent')}</h2><button class="ghost" data-go="activity" style="padding:4px 8px;min-height:0">${t('seeAll')}</button></div><div class="list">${tx.items.map(txRow).join('')}</div></div>`
    : `<div class="card">${empty('🎙️', t('welcomeTitle'), t('obAutoBody'))}${S.demo ? `<button class="primary full" data-act="demo">${t('tryDemo')}</button><button class="full" style="margin-top:8px" data-act="seed">${t('sample')}</button>` : `<button class="primary full" data-act="open-cap" data-id="cash">🎙️ ${t('addCash')}</button>`}</div>`;
  const allDone = tx.total && !S.pending.length ? `<div class="card flat row"><div class="ico" style="--c:#2b8a3e">✅</div><div><b>${t('allCaught')}</b><div class="sm mut">${t('undoneHint')}</div></div></div>` : '';
  const notifSetup = native.present && native.status !== 'authorized' ? accessCard({ compact: true }) : '';
  return `<div class="topbar" style="padding:6px 0 0"><div><div class="mut sm">${t('hello')}${prefs.name ? ', ' + esc(prefs.name) : ''} 👋</div><h1>HisaabBol</h1></div><span id="net" class="dot"></span></div><div id="offline" class="card flat sm hide">${t('offline')}</div>${hero}${todayCard}${notifSetup}${pend}${allDone}${reminders}${recent}`;
}

// ───────────────────────────── ACTIVITY
let ACT_F = { q: '', cat: '' };
async function activity() {
  const p = new URLSearchParams({ limit: 100 }); if (ACT_F.q) p.set('q', ACT_F.q); if (ACT_F.cat) p.set('category', ACT_F.cat);
  const [tx, caps] = await Promise.all([api('/transactions?' + p), api('/captures?status=pending')]);
  S.pending = caps.items.filter(c => c.direction === 'debit');
  const groups = {}; tx.items.forEach(x => (groups[dayLabel(x.occurred_at)] ||= []).push(x));
  const list = tx.items.length ? Object.entries(groups).map(([d, xs]) => `<div class="card" style="padding:4px 16px"><div class="xs mut" style="padding-top:10px;font-weight:700;text-transform:uppercase">${d}</div><div class="list">${xs.map(txRow).join('')}</div></div>`).join('') : empty('🔎', t('nothingYet'));
  return `<div class="topbar" style="padding:6px 0"><h1>${t('activity')}</h1></div>
   ${S.pending.length ? `<div class="card flat"><b>${t('pendingTitle')}</b><div class="list">${S.pending.map(c => `<div class="row between"><span><b>${inr(c.amount_paise)}</b> <span class="mut">${esc(c.counterparty || '—')}</span></span><span class="row"><button data-act="skip" data-id="${c.id}">${t('skip')}</button><button class="primary" data-act="open-cap" data-id="${c.id}">${t('sayIt')}</button></span></div>`).join('')}</div></div>` : ''}
   <input id="q" data-in="search" type="search" placeholder="${t('search')}" value="${esc(ACT_F.q)}" aria-label="${t('search')}">
   <div class="scroll-x" style="margin-top:10px"><button class="chip ${ACT_F.cat === '' ? 'on' : ''}" data-act="fcat" data-cat="">${t('all')}</button>${S.cats.filter(c => c !== 'Income').map(c => `<button class="chip ${ACT_F.cat === c ? 'on' : ''}" data-act="fcat" data-cat="${esc(c)}">${CAT_ICON[c]} ${esc(c)}</button>`).join('')}</div>${list}`;
}
async function txSheet(id) {
  const x = await api('/transactions/' + id); let items = x.items.map(i => ({ ...i }));
  const draw = () => { s.querySelector('.sheet').innerHTML = `<div class="grab"></div><div class="row between"><h2>${inr(x.amount_paise)}</h2><span class="mut sm">${esc(x.counterparty || '')} · ${dayLabel(x.occurred_at)}</span></div>
   ${x.user_note ? `<p class="sm mut">“${esc(x.user_note)}”</p>` : ''}
   ${items.map((it, i) => `<label>${esc(it.label)} · ${inr(it.amount_paise)}</label><button class="full" data-pick="${i}" style="text-align:left">${CAT_ICON[it.category] || ''} ${esc(it.category)} ▾</button>`).join('')}
   <div class="row" style="margin-top:16px"><button class="danger" data-del>${t('delete')}</button><span class="grow"></span><button class="primary" data-save>${t('save')}</button></div>`; };
  const s = sheet(''); draw();
  s.addEventListener('click', async e => {
    const pk = e.target.closest('[data-pick]'); if (pk) return catPick(items[+pk.dataset.pick].category, c => { items[+pk.dataset.pick].category = c; draw(); });
    if (e.target.closest('[data-save]')) { try { await api('/transactions/' + id, { method: 'PATCH', json: { items: items.map(({ label, amount_paise, category, note }) => ({ label, amount_paise, category, note })) } }); s.close(); toast(t('saved')); route(); } catch (er) { toast(er.message, 1); } }
    if (e.target.closest('[data-del]')) { await api('/transactions/' + id, { method: 'DELETE' }); s.close(); route(); }
  });
}

// ───────────────────────────── REPORT
async function report() {
  const m = S.month ? `&month=${S.month}` : ''; const r = await api(`/reports/monthly?language=${prefs.ui}${m}`); S.month = r.month;
  const v = r.vs_last_month, total = r.total_spent_paise, max = Math.max(...r.daily.map(d => d.amount_paise), 1);
  const todayKey = dateKeyInZone(new Date(), S.settings.tz);
  const recentDaily = r.daily.filter(d => d.date <= todayKey).slice(-7).reverse();
  const dailyRows = recentDaily.map(d => `<div class="row between"><span>${new Date(`${d.date}T12:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</span><b>${inr(d.amount_paise)}</b></div>`).join('');
  let acc = 0; const R = 54, C = 2 * Math.PI * R;
  const arcs = r.by_category.map(c => { const len = c.amount_paise / (total || 1) * C; const el = `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${catColor(c.category)}" stroke-width="20" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-acc}" transform="rotate(-90 70 70)"/>`; acc += len; return el; }).join('');
  const donut = total ? `<div class="donut"><svg width="170" height="170" viewBox="0 0 140 140" role="img" aria-label="Spending by category"><circle r="${R}" cx="70" cy="70" fill="none" stroke="var(--surface2)" stroke-width="20"/>${arcs}</svg><div class="c"><div class="xs mut">${t('thisMonth')}</div><b style="font-size:20px">${inr(total)}</b></div></div>` : '';
  const cats = S.legendAll ? r.by_category : r.by_category.slice(0, 5);
  return `<div class="topbar" style="padding:6px 0"><h1>${t('report')}</h1><span class="row tight"><button data-act="mprev" aria-label="Previous month">‹</button><b style="min-width:92px;text-align:center">${monthName(r.month)}</b><button data-act="mnext" aria-label="Next month">›</button></span></div>
  <div class="card accent"><div class="big">${inr(total)}</div><div class="row wrap" style="margin-top:10px">${v.delta_pct == null ? '' : `<span class="pill">${v.delta_pct > 0 ? '▲' : '▼'} ${Math.abs(v.delta_pct)}% ${t('vsLast')}</span>`}<span class="pill">${r.transaction_count} ${t('entries')}</span><span class="pill">${inr0(r.avg_per_day_paise)} ${t('perDay')}</span></div></div>
  ${r.pending_notes ? `<div class="card flat sm">⏳ ${r.pending_notes} ${t('pendingTitle').toLowerCase()}</div>` : ''}
  ${total ? `<div class="card"><h2>${t('noticed')}</h2><ul style="padding-left:18px;margin:10px 0 0">${r.insights.map(i => `<li style="margin:8px 0">${esc(i)}</li>`).join('')}</ul></div>
  <div class="card"><h2>${t('whereWent')}</h2>${donut}<div class="legend">${cats.map(c => `<div><span class="sq" style="background:${catColor(c.category)}"></span><span class="grow">${esc(c.category)}</span><b>${inr(c.amount_paise)}</b><span class="mut xs" style="width:38px;text-align:right">${Math.round(c.percent)}%</span></div>`).join('')}</div>${r.by_category.length > 5 ? `<button class="ghost legend-more" data-act="legend">${S.legendAll ? t('moreLess') : t('moreShow')}</button>` : ''}</div>
  <div class="card"><h2>${t('daily')}</h2><div class="bars" style="margin-top:12px">${r.daily.map(d => `<i title="${d.date}: ${inr(d.amount_paise)}" style="height:${Math.max(3, d.amount_paise / max * 100)}%"></i>`).join('')}</div><div class="list sm" style="margin-top:12px">${dailyRows}</div></div>
  <div class="card"><h2>${t('topMerchants')}</h2><div class="list">${r.top_merchants.map(x => `<div class="row between"><span>${esc(x.merchant)} <span class="mut xs">×${x.count}</span></span><b>${inr(x.amount_paise)}</b></div>`).join('')}</div></div>`
   : `<div class="card">${empty('📊', t('nothingYet'), t('tryDemo'))}${S.demo ? `<button class="primary full" data-act="seed">${t('sample')}</button>` : ''}</div>`}
  ${r.budgets.length ? `<div class="card"><h2>${t('budgets')}</h2>${r.budgets.map(budgetRow).join('')}</div>` : ''}
  ${r.udhaar.you_will_get_paise || r.udhaar.you_have_to_give_paise ? `<div class="card"><h2>${t('udhaar')}</h2><div class="row between" style="margin-top:8px"><span>${t('youWillGet')}</span><b>${inr(r.udhaar.you_will_get_paise)}</b></div><div class="row between"><span>${t('youHaveToGive')}</span><b>${inr(r.udhaar.you_have_to_give_paise)}</b></div></div>` : ''}
  <div class="row" style="gap:10px"><button class="grow" data-act="share">${t('share')}</button><button class="grow" data-act="csv">${t('export')}</button></div>`;
}
const budgetRow = b => `<div style="margin-top:12px"><div class="row between"><span>${b.category ? (CAT_ICON[b.category] || '') + ' ' + esc(b.category) : t('overall')}</span><span class="sm mut">${inr(b.spent_paise)} / ${inr(b.limit_paise)}</span></div><div class="bar ${b.state === 'over' ? 'over' : b.state === 'warning' ? 'warn' : ''}" style="margin-top:6px"><i style="width:${Math.min(100, b.percent)}%"></i></div></div>`;

// ───────────────────────────── MORE / UDHAAR / BUDGETS / SETTINGS / DIAGNOSTICS / PRIVACY
const accessCard = ({ compact = false } = {}) => native.present
  ? `<div class="card notif-card ${native.status === 'authorized' ? 'is-on' : 'is-off'}"><div class="row"><div class="ico">${native.status === 'authorized' ? '🟢' : '🔔'}</div><div class="grow"><b>${native.status === 'authorized' ? t('accessOn') : t('accessOff')}</b><div class="sm mut">${t('notifSteps')}</div></div></div>${native.status === 'authorized' ? `<div class="sm mut notif-sources">${t('notifSources')}</div>` : `<button class="primary full" style="margin-top:12px" data-act="enable-access">${t('enableAccess')}</button>${compact ? '' : `<div class="xs mut" style="margin-top:8px">${t('notifSources')}</div>`}`}</div>`
  : `<div class="card flat sm">ℹ️ ${t('webOnly')}</div>`;
async function more() {
  const row = (go, ico, label, sub = '') => `<button class="rowbtn" data-go="${go}"><div class="ico">${ico}</div><div class="grow"><b>${label}</b>${sub ? `<span class="sm mut">${sub}</span>` : ''}</div><span class="chev">›</span></button>`;
  const act = (a, ico, label, sub = '') => `<button class="rowbtn" data-act="${a}"><div class="ico">${ico}</div><div class="grow"><b>${label}</b>${sub ? `<span class="sm mut">${sub}</span>` : ''}</div><span class="chev">›</span></button>`;
  return `<div class="topbar" style="padding:6px 0"><h1>${t('more')}</h1></div>${accessCard()}
   <div class="card" style="padding:4px 16px"><div class="list">${row('udhaar', '🤝', t('udhaar'))}${row('budgets', '🎯', t('budgets'))}${row('shops', '🏪', t('shops'))}</div></div>
   <div class="card" style="padding:4px 16px"><div class="list">${row('settings', '⚙️', t('settings'))}${act('backup', '💾', t('dataTitle'), t('backupKey') + ' · JSON · CSV')}${row('privacy', '🔒', t('privacy'))}${S.demo ? act('demo', '✨', t('demoTools')) : ''}${row('diagnostics', '🩺', t('diagnostics'))}</div></div>`;
}
async function udhaar() {
  const u = await api('/udhaar');
  return `<div class="topbar" style="padding:6px 0"><h1>${t('udhaar')}</h1><button class="primary" data-act="add-udhaar">+ ${t('add')}</button></div>
  <div class="card"><div class="row between"><span>${t('youWillGet')}</span><b class="amt in">${inr(u.you_will_get_paise)}</b></div><div class="row between" style="margin-top:6px"><span>${t('youHaveToGive')}</span><b class="amt">${inr(u.you_have_to_give_paise)}</b></div></div>
  ${u.items.length ? `<div class="card"><div class="list">${u.items.map(i => `<div class="row"><div class="avatar">${esc(i.person[0].toUpperCase())}</div><div class="grow"><b>${esc(i.person)}</b> <span class="pill ${i.direction === 'i_lent' ? 'down' : 'up'}">${i.direction === 'i_lent' ? t('owesYou') : t('youOwe')}</span><div class="sm mut">${i.outstanding_display}${i.due_date ? ' · ' + i.due_date : ''}</div></div><button data-act="settle" data-id="${i.id}">${t('settle')}</button><button class="ghost" aria-label="${t('delete')}" data-act="del-udhaar" data-id="${i.id}" style="padding:8px">✕</button></div>`).join('')}</div></div>` : empty('🤝', t('nothingYet'))}`;
}
async function shops() {
  const r = await api('/merchants');
  return `<div class="topbar" style="padding:6px 0"><h1>${t('shops')}</h1><button class="primary" data-act="add-shop">+ ${t('add')}</button></div><p class="sm mut" style="margin-top:0">${t('shopsHint')}</p>
  ${r.items.length ? `<div class="card" style="padding:4px 16px"><div class="list">${r.items.map(x => `<div class="row">${bubble(x.category)}<button class="tx grow" style="padding:8px 0" data-act="shop-cat" data-m="${esc(x.merchant)}" data-cat="${esc(x.category)}"><div class="grow"><b style="text-transform:capitalize">${esc(x.merchant)}</b><div class="sm mut">${esc(x.category)} · ${t('learnedFrom', { n: x.times_confirmed })}</div></div></button><label class="sw"><input type="checkbox" data-in="shop-auto" data-m="${esc(x.merchant)}" data-cat="${esc(x.category)}" ${x.auto_apply ? 'checked' : ''} aria-label="auto"><i></i></label><button class="ghost" aria-label="${t('delete')}" data-act="shop-del" data-m="${esc(x.merchant)}" style="padding:8px">✕</button></div>`).join('')}</div></div>` : empty('🏪', t('nothingYet'), t('shopsHint'))}`;
}
async function budgets() {
  const b = await api('/budgets');
  return `<div class="topbar" style="padding:6px 0"><h1>${t('budgets')}</h1><button class="primary" data-act="add-budget">+ ${t('add')}</button></div>
  ${b.items.length ? `<div class="card">${b.items.map(x => `${budgetRow(x)}<div style="text-align:right"><button class="ghost danger" style="min-height:0;padding:2px 6px" data-act="del-budget" data-cat="${esc(x.category || '')}">${t('delete')}</button></div>`).join('')}</div>` : empty('🎯', t('nothingYet'))}`;
}
function settings() {
  const s = S.settings;
  return `<div class="topbar" style="padding:6px 0"><h1>${t('settings')}</h1></div>
  <div class="card"><h2>${t('theme')}</h2><div class="seg" style="margin-top:10px">${['auto', 'light', 'dark'].map(x => `<button class="${prefs.theme === x ? 'on' : ''}" data-act="theme" data-v="${x}">${t(x)}</button>`).join('')}</div>
   <label>${t('accent')}</label><div class="row wrap">${Object.entries(ACCENTS).map(([n, c]) => `<button class="swatch ${prefs.accent === n ? 'on' : ''}" style="background:${c}" data-act="accent" data-v="${n}" aria-label="${n}"></button>`).join('')}</div>
   <div class="row between" style="margin-top:14px"><span>${t('compact')}</span><label class="sw"><input type="checkbox" data-in="compact" ${prefs.compact ? 'checked' : ''}><i></i></label></div></div>
  <div class="card"><h2>${t('language')}</h2><div class="seg" style="margin-top:10px">${Object.entries(LANGS).map(([k, v]) => `<button class="${prefs.ui === k ? 'on' : ''}" data-act="ui" data-v="${k}">${v}</button>`).join('')}</div>
   <label>${t('speaking')}</label><select data-in="speak">${SPEAK.map(([v, n]) => `<option value="${v}" ${s.language_hint === v ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
  <div class="card"><h2>${t('obAsk')}</h2><label>${t('minAmount')} (₹)</label><input type="number" inputmode="numeric" min="0" data-in="min" value="${s.min_prompt_paise / 100}">
   <label>${t('maxPrompts')}</label><input type="number" inputmode="numeric" min="0" max="50" data-in="maxp" value="${s.max_prompts_per_day}">
   <label>${t('digest')}</label><input type="time" data-in="digest" value="${s.digest_time}">
   <div class="row between" style="margin-top:14px"><span>${t('speakBack')}</span><label class="sw"><input type="checkbox" data-in="tts" ${s.tts_enabled ? 'checked' : ''}><i></i></label></div></div>
  <div class="card"><div class="row between"><div><b>${t('appLock')}</b><div class="sm mut">${lockOn() ? t('pinSet') : t('pinOff')}</div></div><label class="sw"><input type="checkbox" data-in="lock" ${lockOn() ? 'checked' : ''} aria-label="${t('appLock')}"><i></i></label></div>
   <button class="full" style="margin-top:12px" data-act="backup">💾 ${t('backupKey')}</button></div>
  <div class="card"><label style="margin-top:0">${t('hello')}</label><input data-in="name" placeholder="Name" value="${esc(prefs.name)}">
   <div class="row" style="margin-top:14px;gap:10px"><button class="grow" data-act="csv">${t('export')}</button><button class="grow" data-act="seed">${t('sample')}</button></div>
   <button class="danger full" style="margin-top:10px" data-act="wipe">${t('deleteData')}</button></div>`;
}
async function diagnostics() {
  const [d, h] = await Promise.all([api('/diagnostics'), fetch('/api/v1/health').then(r => r.json())]);
  return `<div class="topbar" style="padding:6px 0"><h1>${t('diagnostics')}</h1></div><div class="card"><h3>${t('server')}</h3><p class="sm mut">Speech: ${h.gnani_mock ? 'mock' : h.gnani_configured ? 'Gnani live' : 'not configured'} · ${h.stt_model} · Understanding: ${h.llm}</p></div>
  <div class="card"><h3>${t('usage')}</h3><p class="sm mut">${t('credits')}</p>${Object.entries(d.gnani_usage).map(([k, v]) => `<div class="row between"><span>${k.toUpperCase()}</span><span>${v.calls_total} calls · ${v.avg_latency_ms} ms</span></div>`).join('') || '<p class="sm mut">—</p>'}</div>
  <div class="card"><h3>API</h3>${d.recent_api_calls.map(c => `<div class="row between xs"><span>${c.method} ${esc(c.route.replace('/api/v1', ''))}</span><span>${c.status} · ${c.latency_ms}ms</span></div>`).join('')}</div>`;
}
function privacy() {
  return `<div class="topbar" style="padding:6px 0"><h1>${t('privacy')}</h1></div><div class="card"><ul style="padding-left:18px;margin:0"><li style="margin:8px 0">Notifications are read on your phone. Only payment alerts from banks and UPI apps are looked at; everything else is ignored.</li><li style="margin:8px 0">Only the amount, payee and time are sent to the server. The text of the message is never stored.</li><li style="margin:8px 0">Your voice clip is sent to Gnani for transcription and is not kept by this app.</li><li style="margin:8px 0">No bank login. No account. Delete everything any time from Settings.</li></ul></div>`;
}

// ───────────────────────────── ONBOARDING
let OB = 0;
async function onboarding() {
  const steps = [
    `<div><div class="hero-ico">🎙️</div><h1>${t('welcomeTitle')}</h1><p class="mut" style="margin-top:12px">${t('welcomeBody')}</p>
      <div class="row wrap" style="margin-top:18px">${Object.entries(LANGS).map(([k, v]) => `<button class="chip ${prefs.ui === k ? 'on' : ''}" data-act="ui" data-v="${k}" data-ob="1">${v}</button>`).join('')}</div>
      <button class="ghost" style="margin-top:20px" data-act="restore">${t('restore')}</button></div>`,
    `<div><h1>${t('obLang')}</h1><p class="mut">${t('obLangBody')}</p><div class="chips" style="margin-top:16px">${SPEAK.map(([v, n]) => `<button class="chip ${S.settings.language_hint === v ? 'on' : ''}" data-act="speak" data-v="${v}">${n}</button>`).join('')}</div></div>`,
    `<div><h1>${t('obAsk')}</h1><p class="mut">${t('obAskBody')}</p>
      <label>${t('minAmount')} (₹)</label><input type="number" inputmode="numeric" data-in="min" value="${S.settings.min_prompt_paise / 100}">
      <label>${t('accent')}</label><div class="row wrap">${Object.entries(ACCENTS).map(([n, c]) => `<button class="swatch ${prefs.accent === n ? 'on' : ''}" style="background:${c}" data-act="accent" data-v="${n}" data-ob="1" aria-label="${n}"></button>`).join('')}</div></div>`,
    `<div><div class="hero-ico">🔔</div><h1>${t('obAuto')}</h1><p class="mut" style="margin-top:12px">${t('obAutoBody')}</p>${accessCard()}</div>`,
  ];
  return `<div class="ob"><div><div class="steps">${steps.map((_, i) => `<i class="${i <= OB ? 'on' : ''}"></i>`).join('')}</div><div style="margin-top:24px">${steps[OB]}</div></div>
   <div class="row" style="gap:10px">${OB ? `<button data-act="ob-back">${t('back')}</button>` : ''}<button class="primary grow" data-act="ob-next">${OB === steps.length - 1 ? t('getStarted') : t('next')}</button></div></div>`;
}

// ───────────────────────────── CAPTURE (the heart of the app)
async function renderCapture(idStr) {
  const cash = idStr === 'cash'; let cap = null;
  if (!cash) {
    try { cap = await api('/captures/' + idStr); } catch { toast('Payment not found', 1); location.hash = '#/home'; return; }
    if (cap.status === 'answered') { toast(t('duplicate')); location.hash = '#/home'; return; }
  }
  S.C?.rec?.cancel(); S.C = { cash, cap, phase: 'idle', draft: null, transcript: '', rec: null, hint: '' };
  drawCap();
}
function drawCap() {
  const C = S.C; if (!C) return; let el = $('.cap'); if (!el) { el = document.createElement('div'); el.className = 'cap'; document.body.append(el); }
  const head = `<div class="row between"><button class="ghost" data-act="cap-close" aria-label="${t('back')}">‹ ${t('back')}</button>${C.cap ? `<button class="ghost" data-act="skip" data-id="${C.cap.id}">${t('skip')}</button>` : ''}</div>
   <div class="center" style="margin-top:8px"><div class="mut sm">${C.cash ? t('cash') : `${t('paidTo')} <b>${esc(C.cap.counterparty || '—')}</b> · ${timeLabel(C.cap.occurred_at)}`}</div>
   <div class="big">${C.cash ? t('addCash') : inr(C.cap.amount_paise)}</div></div>`;
  let body = '';
  if (C.phase === 'idle' || C.phase === 'rec') {
    const person = C.cap?.counterparty_is_person;
    body = `<h2 class="center" style="margin-top:6px">${person ? t('whoFor') : C.cash ? t('howMuch').replace('?', '…') : t('whatFor')}</h2>
     <div class="micwrap"><button class="mic ${C.phase === 'rec' ? 'rec' : ''}" data-act="mic" aria-label="${t('tapSpeak')}">${I.mic}</button><div class="ring" id="ring"></div></div>
      ${C.phase === 'rec' ? `<div class="wave" id="wave">${'<i></i>'.repeat(28)}</div>` : ''}<p class="center ${C.phase === 'rec' ? '' : 'mut'}" id="cap-hint" style="font-weight:600">${C.phase === 'rec' ? t('listening') : t('tapSpeak')}</p>
     <p class="center mut sm">${C.hint || '🎙️ ' + t('holdClose')}</p>
     ${person && C.phase === 'idle' ? `<div class="chips" style="justify-content:center;margin:14px 0">${PERSON_CHIPS.map(([c, k]) => `<button class="chip" data-act="quick" data-cat="${esc(c)}">${CAT_ICON[c]} ${t(k)}</button>`).join('')}</div>` : ''}
     <div class="center" style="margin-top:12px"><button class="ghost" data-act="cap-type">⌨️ ${t('typeInstead')}</button></div>`;
  } else if (C.phase === 'busy') {
    body = `<div style="margin:70px 0" class="center"><div class="spin"></div><p class="mut" style="margin-top:16px">${t('understanding')}</p></div>`;
  } else if (C.phase === 'type') {
    body = `<h2 style="margin-top:20px">${t('whatFor')}</h2><textarea id="typed" rows="3" placeholder="${t('whatFor')}" style="margin-top:10px">${esc(C.transcript)}</textarea>
     ${C.cash ? `<label>${t('amount')} (₹)</label><input id="typed-amt" type="number" inputmode="decimal">` : ''}
     <div class="row" style="margin-top:14px;gap:10px"><button data-act="cap-back">${t('back')}</button><button class="primary grow" data-act="cap-text">${t('process')}</button></div>`;
  } else if (C.phase === 'draft') body = draftHtml();
  else if (C.phase === 'done') body = `<div class="check">${I.check}</div><h2 class="center">${t('saved')}</h2><div class="center mut sm" style="margin-top:6px">${esc(C.doneMsg || '')}</div>`;
  el.innerHTML = `<div class="inner">${head}${body}</div>`;
}
const draftSum = d => d.items.reduce((a, i) => a + (i.amount_paise || 0), 0);
function draftHtml() {
  const C = S.C, d = C.draft, total = C.cap ? C.cap.amount_paise : d.amount_paise, left = total ? total - draftSum(d) : 0, many = d.items.length > 1;
  return `<div class="card flat" style="margin-top:18px"><div class="xs mut">${t('heard')}</div><div style="font-weight:600">“${esc(C.transcript)}” <button class="ghost" style="min-height:0;padding:2px 8px" data-act="cap-type">${t('edit')}</button></div></div>
   ${d.follow_up_question ? `<div class="card flat" style="border-color:var(--accent)">💬 ${esc(d.follow_up_question)}</div>` : ''}
   ${!total ? `<label>${t('amount')} (₹)</label><input id="d-total" type="number" inputmode="decimal" data-in="dtotal" placeholder="0">` : ''}
   ${d.udhaar ? `<div class="pill acc" style="margin:6px 0">🤝 ${esc(d.udhaar.person || '')} · ${d.udhaar.direction.replace(/_/g, ' ')}</div>` : ''}
   ${d.items.map((it, i) => `<div class="card" style="margin:10px 0"><div class="row"><input data-in="label" data-i="${i}" value="${esc(it.label)}" aria-label="label"><button style="flex:none" data-act="rm-item" data-i="${i}" class="${many ? '' : 'hide'}" aria-label="remove">✕</button></div>
     <div class="row between" style="margin-top:10px"><button data-act="pick-cat" data-i="${i}">${CAT_ICON[it.category] || ''} ${esc(it.category)} ▾</button>
     ${many || !total ? `<input type="number" inputmode="decimal" style="width:110px" data-in="iamt" data-i="${i}" value="${it.amount_paise ? it.amount_paise / 100 : ''}" placeholder="₹">` : `<b class="amt">${inr(it.amount_paise)}</b>`}</div></div>`).join('')}
   ${total && left !== 0 ? `<div class="sm ${left < 0 ? '' : 'mut'}" style="${left < 0 ? 'color:var(--bad)' : ''}">${inr(Math.abs(left))} ${left < 0 ? 'over' : t('amountLeft')}</div>` : ''}
   <div class="row" style="margin-top:14px;gap:10px"><button data-act="add-item" ${total ? '' : 'disabled'}>+ ${t('addSplit')}</button><button class="primary grow" data-act="cap-save" ${total && left !== 0 ? 'disabled' : ''}>${t('save')}</button></div>`;
}
async function toggleMic() {
  const C = S.C;
  if (C.phase === 'rec') return stopAndProcess();
  if (C.phase !== 'idle') return;
  try {
    C.rec = new Recorder({ maxMs: window.HB_MAXREC || 12000, onLevel: l => { const r = $('#ring'); if (r) r.style.transform = `scale(${1 + l * 0.9})`; const w = $('#wave'); if (w) { C.lv = [...(C.lv || []), l].slice(-28); [...w.children].forEach((b, i) => { b.style.height = (6 + (C.lv[i - (28 - C.lv.length)] || 0) * 40) + 'px'; }); } }, onAutoStop: () => stopAndProcess() });
    await C.rec.start(); C.phase = 'rec'; drawCap();
  } catch (e) {
    C.rec = null;
    C.hint = e.name === 'NotAllowedError' || e.name === 'SecurityError'
      ? '🔇 Microphone permission is blocked. Allow it in the app/browser settings, then try again.'
      : e.message || '🔇 Microphone unavailable. Check the app permissions, or type instead.';
    C.phase = 'idle'; drawCap(); toast(C.hint, 1);
  }
}
async function stopAndProcess() {
  const C = S.C; if (!C?.rec || C.phase !== 'rec') return; C.phase = 'busy'; drawCap();
  try {
    const blob = await C.rec.stop(); C.rec = null; const wav = await toWav(blob);
    const fd = new FormData(); fd.append('audio', wav, 'clip.wav');
    const r = await api(C.cash ? '/cash/voice' : `/captures/${C.cap.id}/voice`, { form: fd });
    if (r.empty) { C.phase = 'idle'; C.hint = t('couldntHear'); drawCap(); return; }
    C.transcript = r.transcript; C.draft = r.draft; C.phase = 'draft'; drawCap();
  } catch (e) {
    C.phase = 'type'; C.hint = ''; drawCap();
    toast(e instanceof ApiErr && e.status < 500 && e.status !== 429 ? e.message : 'Voice is unavailable right now — type it instead.', 1);
  }
}
async function submitText(text, amount) {
  const C = S.C; if (!text.trim()) return; C.phase = 'busy'; drawCap();
  try {
    const r = await api(C.cash ? '/cash/note' : `/captures/${C.cap.id}/note`, { json: { text, amount_paise: C.cash && amount ? amount : undefined } });
    C.transcript = text; C.draft = r.draft; C.phase = 'draft'; drawCap();
  } catch (e) { C.phase = 'type'; drawCap(); toast(e.message, 1); }
}
async function saveDraft() {
  const C = S.C, d = C.draft; const total = C.cap ? C.cap.amount_paise : d.amount_paise || draftSum(d);
  if (!total) return toast(t('howMuch'), 1);
  if (d.items.length === 1 && !d.items[0].amount_paise) d.items[0].amount_paise = total;
  if (draftSum(d) !== total) return toast('Amounts must add up', 1);
  const body = { items: d.items.map(({ label, amount_paise, category, note }) => ({ label: label || 'Item', amount_paise, category, note })), transcript: C.transcript, confidence: d.confidence, needs_review: d.needs_review, udhaar: d.udhaar || undefined };
  try {
    const res = C.cap ? await outbox.post(`/captures/${C.cap.id}/confirm`, body) : await outbox.post('/transactions', { ...body, amount_paise: total, source: 'voice' });
    if (res.queued) { toast(t('queued')); location.hash = '#/home'; return; }
    const r = res.data; C.phase = 'done'; C.doneMsg = [savedMessage(r.transaction), ...r.alerts.map(a => a.message)].filter(Boolean).join(' '); drawCap(); refreshPending();
    if (S.settings.tts_enabled) api('/tts', { json: { transaction_id: r.transaction.id }, raw: true }).then(x => x.blob()).then(b => { const a = new Audio(URL.createObjectURL(b)); a.play().catch(() => {}); }).catch(() => {});
    const txId = r.transaction.id;
    setTimeout(() => { if (S.C === C) { S.C = null; location.hash = '#/home'; setTimeout(() => toast(C.doneMsg || t('saved'), false, { label: t('undo'), fn: async () => { try { await api('/transactions/' + txId, { method: 'DELETE' }); toast(t('undone')); refreshPending(); route(); } catch (e) { toast(e.message, 1); } } }), 150); } }, 1300);
  } catch (e) { toast(e.message, 1); }
}

// ───────────────────────────── app lock (PIN stored only as a salted hash on this device)
const LOCK_KEY = 'hb_lock'; let hiddenAt = 0;
const lockOn = () => !!localStorage.getItem(LOCK_KEY);
async function pinHash(pin, salt) { const b = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(salt + pin)); return [...new Uint8Array(b)].map(x => x.toString(16).padStart(2, '0')).join(''); }
function pinPad(host, { title, sub = '', onPin }) {
  let pin = '';
  const draw = (bad) => { host.innerHTML = `<h2>${title}</h2><div class="sm mut">${sub}</div><div class="dots ${bad ? 'bad' : ''}">${[0, 1, 2, 3].map(i => `<i class="${i < pin.length ? 'on' : ''}"></i>`).join('')}</div>
    <div class="pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => `<button data-k="${n}">${n}</button>`).join('')}<span></span><button data-k="0">0</button><button data-k="⌫" aria-label="Delete">⌫</button></div>`; };
  host.onclick = async e => { const b = e.target.closest('[data-k]'); if (!b) return; if (b.dataset.k === '⌫') pin = pin.slice(0, -1); else if (pin.length < 4) pin += b.dataset.k; draw();
    if (pin.length === 4) { const p = pin; pin = ''; const ok = await onPin(p); if (ok === false) { draw(true); } else draw(); } };
  draw();
}
function showLock() {
  if ($('.lock') || !lockOn()) return; const el = document.createElement('div'); el.className = 'lock'; document.body.append(el);
  const { salt, hash } = JSON.parse(localStorage.getItem(LOCK_KEY)); const host = document.createElement('div'); el.append(host);
  const help = document.createElement('div'); help.innerHTML = `<button class="ghost" style="margin-top:18px" data-fp>${t('forgotPin')}</button>`; el.append(help); help.onclick = () => toast(t('forgotHelp'));
  pinPad(host, { title: t('enterPin'), onPin: async p => { if ((await pinHash(p, salt)) === hash) { el.remove(); return true; } toast(t('wrongPin'), 1); return false; } });
}
function setupPin(done) {
  const s = sheet(''); const host = s.querySelector('.sheet'); let first = null;
  const step = () => pinPad(host, { title: first ? t('confirmPin') : t('setPin'), onPin: async p => {
    if (!first) { first = p; step(); return true; } if (p !== first) { first = null; toast(t('pinMismatch'), 1); step(); return false; }
    const salt = crypto.randomUUID(); localStorage.setItem(LOCK_KEY, JSON.stringify({ salt, hash: await pinHash(p, salt) })); s.close(); done(); return true; } });
  step();
}
function disablePin(done) {
  const s = sheet(''); const host = s.querySelector('.sheet'); const { salt, hash } = JSON.parse(localStorage.getItem(LOCK_KEY));
  pinPad(host, { title: t('enterPin'), onPin: async p => { if ((await pinHash(p, salt)) === hash) { localStorage.removeItem(LOCK_KEY); s.close(); done(); return true; } toast(t('wrongPin'), 1); return false; } });
}
document.addEventListener('visibilitychange', () => { if (document.hidden) hiddenAt = Date.now(); else if (lockOn() && Date.now() - hiddenAt > 30000) showLock(); });

// ───────────────────────────── demo tools
async function demoSheet() {
  let presets = []; try { presets = (await api('/demo/presets')).items; } catch { /* demo disabled */ }
  const s = sheet(`<h2>${t('tryDemo')}</h2><p class="sm mut">${t('webOnly')}</p><div class="chips" style="margin:12px 0">${presets.map(p => `<button class="chip" data-p="${p.id}">${esc(p.name)}</button>`).join('')}</div>
    <label>${t('pasteSms')}</label><textarea id="raw" rows="3"></textarea><button class="primary full" style="margin-top:10px" data-go-raw>${t('process')}</button>`);
  const run = async body => { try { const r = await api('/demo/simulate', { json: body }); s.close(); const msg = { auto_saved: 'autoSaved', duplicate: 'duplicate', ignored: 'ignored', digest: 'digest2', recorded_income: 'income' }[r.action]; if (r.action === 'prompt') location.hash = '#/capture/' + r.capture.id; else { toast(t(msg)); route(); } } catch (e) { toast(e.message, 1); } };
  s.addEventListener('click', e => { const p = e.target.closest('[data-p]'); if (p) run({ preset: +p.dataset.p }); if (e.target.closest('[data-go-raw]')) { const v = $('#raw').value.trim(); if (v) run({ raw_text: v }); } });
}

// ───────────────────────────── actions (event delegation)
const ACT = {
  reload: () => route(),
  'open-cap': el => { location.hash = '#/capture/' + el.dataset.id; },
  tx: el => txSheet(el.dataset.id),
  skip: async el => { await api(`/captures/${el.dataset.id}/skip`, { method: 'POST' }); S.C = null; toast(t('skip')); location.hash = '#/home'; route(); refreshPending(); },
  fcat: el => { ACT_F.cat = el.dataset.cat; route(); },
  demo: demoSheet,
  seed: async () => { await api('/demo/seed-month', { method: 'POST' }).catch(e => toast(e.message, 1)); toast(t('saved')); route(); },
  mprev: () => { const [y, m] = S.month.split('-').map(Number); S.month = m === 1 ? `${y - 1}-12` : `${y}-${String(m - 1).padStart(2, '0')}`; route(); },
  mnext: () => { const [y, m] = S.month.split('-').map(Number); S.month = m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`; route(); },
  csv: async () => { const r = await api('/export/csv', { raw: true }); const b = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'hisaabbol.csv'; a.click(); },
  share: async () => { const r = await api(`/reports/monthly?month=${S.month}&language=${prefs.ui}`); const text = `HisaabBol ${r.month}: ${inr(r.total_spent_paise)} spent.\n` + r.insights.join('\n'); if (navigator.share) navigator.share({ text }).catch(() => {}); else { await navigator.clipboard?.writeText(text); toast('Copied'); } },
  theme: el => { prefs.theme = el.dataset.v; savePrefs(); applyPrefs(); route(); },
  accent: el => { prefs.accent = el.dataset.v; savePrefs(); applyPrefs(); route(); },
  ui: el => { prefs.ui = el.dataset.v; savePrefs(); applyPrefs(); api('/settings', { method: 'PUT', json: { ui_lang: prefs.ui } }).catch(() => {}); route(); },
  speak: async el => { S.settings = await api('/settings', { method: 'PUT', json: { language_hint: el.dataset.v } }); route(); },
  wipe: async () => { if (confirm(t('confirmDelete'))) { await api('/me/data', { method: 'DELETE' }); toast(t('saved')); route(); } },
  'enable-access': () => native.send({ type: 'request_notif_access' }),
  'ob-next': async () => { if (OB < 3) { OB++; route(); } else { prefs.onboarded = true; savePrefs(); OB = 0; location.hash = '#/home'; } },
  'ob-back': () => { OB = Math.max(0, OB - 1); route(); },
  'add-udhaar': () => { const s = sheet(`<h2>${t('udhaar')}</h2><label>${t('person')}</label><input id="up"><label>${t('amount')} (₹)</label><input id="ua" type="number" inputmode="decimal"><div class="seg" style="margin-top:14px"><button class="on" data-d="i_lent">${t('owesYou')}</button><button data-d="i_borrowed">${t('youOwe')}</button></div><button class="primary full" style="margin-top:14px" data-ok>${t('add')}</button>`); let dir = 'i_lent';
    s.addEventListener('click', async e => { const b = e.target.closest('[data-d]'); if (b) { dir = b.dataset.d; s.querySelectorAll('[data-d]').forEach(x => x.classList.toggle('on', x === b)); } if (e.target.closest('[data-ok]')) { try { await api('/udhaar', { json: { person: $('#up').value, direction: dir, amount_paise: rupeesToPaise($('#ua').value) } }); s.close(); route(); } catch (er) { toast(er.message, 1); } } }); },
  settle: async el => { await api(`/udhaar/${el.dataset.id}/settle`, { json: {} }); route(); },
  'add-budget': () => { let cat = ''; const s = sheet(`<h2>${t('budgetSet')}</h2><label>${t('budgets')}</label><button class="full" data-c style="text-align:left">${t('overall')} ▾</button><label>₹ / month</label><input id="bl" type="number" inputmode="numeric"><button class="primary full" style="margin-top:14px" data-ok>${t('save')}</button>`);
    s.addEventListener('click', async e => { if (e.target.closest('[data-c]')) { const sp = S.cats; S.cats = S.cats.filter(c => !['Income', 'Lent (udhaar)', 'Repaid'].includes(c)); catPick('', c => { cat = c; s.querySelector('[data-c]').textContent = c + ' ▾'; }); S.cats = sp; }
      if (e.target.closest('[data-ok]')) { try { await api('/budgets', { method: 'PUT', json: { category: cat || null, limit_paise: rupeesToPaise($('#bl').value) } }); s.close(); route(); } catch (er) { toast(er.message, 1); } } }); },
  'del-budget': async el => { await api('/budgets?category=' + encodeURIComponent(el.dataset.cat), { method: 'DELETE' }); route(); },
  legend: () => { S.legendAll = !S.legendAll; route(); },
  'del-udhaar': async el => { await api('/udhaar/' + el.dataset.id, { method: 'DELETE' }); route(); },
  'shop-cat': el => catPick(el.dataset.cat, async c => { await api('/merchants', { method: 'PUT', json: { merchant: el.dataset.m, category: c, auto_apply: true } }); route(); }),
  'shop-del': async el => { await api('/merchants?merchant=' + encodeURIComponent(el.dataset.m), { method: 'DELETE' }); route(); },
  'add-shop': () => { const s = sheet(`<h2>${t('addShop')}</h2><label>${t('shopName')}</label><input id="sn"><label>Category</label><button class="full" data-c style="text-align:left">Pick ▾</button><button class="primary full" style="margin-top:14px" data-ok>${t('save')}</button>`); let cat = '';
    s.addEventListener('click', async e => { if (e.target.closest('[data-c]')) { const sp = S.cats; S.cats = S.cats.filter(c => !['Income', 'Lent (udhaar)', 'Repaid'].includes(c)); catPick('', c => { cat = c; s.querySelector('[data-c]').textContent = (CAT_ICON[c] || '') + ' ' + c + ' ▾'; }); S.cats = sp; }
      if (e.target.closest('[data-ok]')) { try { await api('/merchants', { method: 'PUT', json: { merchant: $('#sn').value, category: cat, auto_apply: true } }); s.close(); route(); } catch (er) { toast(er.message, 1); } } }); },
  backup: () => { const s = sheet(`<h2>${t('backupKey')}</h2><p class="sm mut">${t('backupHelp')}</p><div class="keybox" id="bk">${esc(session.token)}</div>
      <div class="row" style="margin-top:12px;gap:10px"><button class="grow primary" data-copy>${t('copy')}</button><button class="grow" data-json>${t('backupJson')}</button></div><button class="ghost full" style="margin-top:8px" data-csv>${t('export')}</button>`);
    s.addEventListener('click', async e => { if (e.target.closest('[data-copy]')) { try { await navigator.clipboard.writeText(session.token); toast(t('copied')); } catch { const r = document.createRange(); r.selectNodeContents($('#bk')); getSelection().removeAllRanges(); getSelection().addRange(r); } }
      if (e.target.closest('[data-json]')) { const r = await api('/export/json', { raw: true }); const b = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = 'hisaabbol-backup.json'; a.click(); }
      if (e.target.closest('[data-csv]')) ACT.csv(); }); },
  restore: () => { const s = sheet(`<h2>${t('restore')}</h2><p class="sm mut">${t('restoreHelp')}</p><textarea id="rk" rows="3" placeholder="hb_…"></textarea><button class="primary full" style="margin-top:12px" data-ok>${t('restore')}</button>`);
    s.addEventListener('click', async e => { if (!e.target.closest('[data-ok]')) return; const k = $('#rk').value.trim();
      try { const r = await fetch('/api/v1/me', { headers: { Authorization: 'Bearer ' + k } }); if (!r.ok) throw 0; session.token = k; prefs.onboarded = true; savePrefs(); location.hash = '#/home'; location.reload(); } catch { toast(t('restoreFail'), 1); } }); },
  // capture
  mic: toggleMic,
  'cap-close': () => { S.C?.rec?.cancel(); S.C = null; location.hash = '#/home'; route(); },
  'cap-type': () => { S.C.rec?.cancel(); S.C.phase = 'type'; drawCap(); $('#typed')?.focus(); },
  'cap-back': () => { S.C.phase = S.C.draft ? 'draft' : 'idle'; drawCap(); },
  'cap-text': () => { const a = $('#typed-amt')?.value; submitText($('#typed').value, a ? rupeesToPaise(a) : null); },
  quick: el => { const C = S.C; C.transcript = el.textContent.trim(); C.draft = { items: [{ label: C.cap.counterparty || 'Payment', amount_paise: C.cap.amount_paise, category: el.dataset.cat, note: null }], udhaar: /Lent|Repaid/.test(el.dataset.cat) ? { person: C.cap.counterparty, direction: el.dataset.cat === 'Repaid' ? 'repaid_by_me' : 'i_lent' } : null, confidence: 1, needs_review: false }; C.phase = 'draft'; drawCap(); },
  'pick-cat': el => { const it = S.C.draft.items[+el.dataset.i]; catPick(it.category, c => { it.category = c; drawCap(); }); },
  'rm-item': el => { S.C.draft.items.splice(+el.dataset.i, 1); drawCap(); },
  'add-item': () => { const C = S.C, d = C.draft, total = C.cap ? C.cap.amount_paise : d.amount_paise; let left = total - draftSum(d);
    if (left <= 0 && d.items.length === 1) { const half = Math.floor(total / 200) * 100 || Math.floor(total / 2); d.items[0].amount_paise = half; left = total - half; }  // first split: halve it, user adjusts
    if (left > 0) d.items.push({ label: 'Other', amount_paise: left, category: 'Other', note: null }); drawCap(); },
  'cap-save': saveDraft,
};
document.addEventListener('click', e => {
  const g = e.target.closest('[data-go]'); if (g && !g.dataset.act) { location.hash = '#/' + g.dataset.go; return; }
  const a = e.target.closest('[data-act]'); if (a) { e.preventDefault(); ACT[a.dataset.act]?.(a, e); }
});
let searchT;
document.addEventListener('input', e => {
  const k = e.target.dataset.in; if (!k) return; const C = S.C;
  if (k === 'search') { clearTimeout(searchT); searchT = setTimeout(() => { ACT_F.q = e.target.value; route(); setTimeout(() => { const q = $('#q'); q?.focus(); q?.setSelectionRange(q.value.length, q.value.length); }, 120); }, 350); }
  if (k === 'label') C.draft.items[+e.target.dataset.i].label = e.target.value;
  if (k === 'iamt') { C.draft.items[+e.target.dataset.i].amount_paise = e.target.value ? rupeesToPaise(e.target.value) : null; const btn = $('[data-act=cap-save]'); const total = C.cap ? C.cap.amount_paise : draftSum(C.draft); if (btn) btn.disabled = !total || draftSum(C.draft) !== total; }
  if (k === 'dtotal') { const v = e.target.value ? rupeesToPaise(e.target.value) : null; C.draft.amount_paise = v; if (C.draft.items.length === 1) C.draft.items[0].amount_paise = v; }
});
document.addEventListener('change', async e => {
  const k = e.target.dataset.in; if (!k) return;
  const put = async j => { try { S.settings = await api('/settings', { method: 'PUT', json: j }); toast(t('saved')); } catch (er) { toast(er.message, 1); route(); } };
  if (k === 'speak') put({ language_hint: e.target.value });
  if (k === 'min') put({ min_prompt_paise: Math.max(0, rupeesToPaise(e.target.value || 0)) });
  if (k === 'maxp') put({ max_prompts_per_day: +e.target.value });
  if (k === 'digest') { await put({ digest_time: e.target.value }); sendDigest(); }
  if (k === 'tts') put({ tts_enabled: e.target.checked });
  if (k === 'lock') { const done = () => route(); if (e.target.checked) { e.target.checked = false; setupPin(done); } else { e.target.checked = true; disablePin(done); } }
  if (k === 'shop-auto') { await api('/merchants', { method: 'PUT', json: { merchant: e.target.dataset.m, category: e.target.dataset.cat, auto_apply: e.target.checked } }).catch(er => toast(er.message, 1)); }
  if (k === 'compact') { prefs.compact = e.target.checked; savePrefs(); applyPrefs(); }
  if (k === 'name') { prefs.name = e.target.value.trim(); savePrefs(); }
});

boot();
