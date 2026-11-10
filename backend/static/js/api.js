// API client: bearer token, Idempotency-Key outbox for offline writes, native-shell bridge.
const BASE = (window.HB_API_BASE || '') + '/api/v1';
export const session = {
  get token() { return localStorage.getItem('hb_token'); },
  set token(v) { v ? localStorage.setItem('hb_token', v) : localStorage.removeItem('hb_token'); },
};
export class ApiErr extends Error { constructor(m, code, status, extra) { super(m); this.code = code; this.status = status; this.extra = extra || {}; } }

export const native = {
  present: !!window.ReactNativeWebView,
  status: 'unknown',
  notificationsEnabled: null,
  send(msg) { if (this.present) window.ReactNativeWebView.postMessage(JSON.stringify(msg)); },
  listeners: [],
  on(fn) { this.listeners.push(fn); return () => { this.listeners = this.listeners.filter(x => x !== fn); }; },
  requestRegistrationKey() {
    if (!this.present) return Promise.resolve(null);
    return new Promise(resolve => {
      let timer, done = false;
      let off = () => {};
      const finish = key => {
        if (done) return;
        done = true; clearTimeout(timer); off(); resolve(key || null);
      };
      off = this.on(m => { if (m.type === 'registration_key') finish(typeof m.key === 'string' ? m.key : null); });
      timer = setTimeout(() => finish(null), 2000);
      this.send({ type: 'get_registration_key' });
    });
  },
};
function onNativeMsg(ev) {
  let m = ev.data; if (typeof m === 'string') { try { m = JSON.parse(m); } catch { return; } }
  if (!m || !m.type) return;
  if (m.type === 'notif_status') { native.status = m.status; native.notificationsEnabled = m.notifications; }
  native.listeners.forEach(f => f(m));
}
window.addEventListener('message', onNativeMsg); document.addEventListener('message', onNativeMsg);

export async function api(path, { method, json, form, headers = {}, raw } = {}) {
  const h = { ...headers };
  if (session.token) h.Authorization = 'Bearer ' + session.token;
  let body;
  if (json !== undefined) { body = JSON.stringify(json); h['Content-Type'] = 'application/json'; method = method || 'POST'; }
  if (form) { body = form; method = method || 'POST'; }
  const r = await fetch(BASE + path, { method: method || 'GET', headers: h, body });
  if (!r.ok) {
    let e = {}; try { e = (await r.json()).error || {}; } catch { /* non-json */ }
    throw new ApiErr(e.message || r.statusText, e.code, r.status, e);
  }
  if (raw) return r;
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r;
}

// ---- outbox: writes made offline are replayed with the same Idempotency-Key, so nothing is ever saved twice.
const OB = 'hb_outbox';
const load = () => { try { return JSON.parse(localStorage.getItem(OB) || '[]'); } catch { return []; } };
const store = q => localStorage.setItem(OB, JSON.stringify(q));
export const outbox = {
  size: () => load().length,
  async post(path, json) {
    const key = crypto.randomUUID();
    try { return { queued: false, data: await api(path, { json, headers: { 'Idempotency-Key': key } }) }; }
    catch (e) {
      if (e instanceof ApiErr) throw e;           // real server answer (validation etc.) — not a network problem
      const q = load(); q.push({ path, json, key, at: Date.now() }); store(q);
      return { queued: true };
    }
  },
  async flush() {
    let q = load(); if (!q.length) return 0; let done = 0;
    for (const it of q.slice()) {
      try { await api(it.path, { json: it.json, headers: { 'Idempotency-Key': it.key } }); }
      catch (e) { if (!(e instanceof ApiErr)) break; /* still offline */ else if (e.status >= 500 || e.status === 429) break; }  // 4xx = drop (stale/invalid)
      q = q.filter(x => x.key !== it.key); store(q); done++;
    }
    return done;
  },
};
window.addEventListener('online', () => outbox.flush().then(n => n && window.dispatchEvent(new CustomEvent('hb-synced', { detail: n }))));
