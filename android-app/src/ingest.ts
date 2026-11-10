import { parsePayment } from './paymentParser';
import { REQUEST_TIMEOUT_MS } from './config';

export interface Session { token: string; base: string }
export interface QueuedIngest { body: unknown; at: number }
export interface Deps {
  getSession(): Promise<Session | null>;
  fetchFn: typeof fetch;
  notify(n: { title: string; body: string; captureId: number }): Promise<void>;
  queue: { push(i: QueuedIngest): Promise<void>; drain(): Promise<QueuedIngest[]> };
}
export type Outcome = 'ignored' | 'prompt' | 'saved' | 'duplicate' | 'queued' | 'no_session' | 'error';

async function post(deps: Deps, s: Session, body: unknown) {
  const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await deps.fetchFn(`${s.base}/api/v1/captures/ingest`, { method: 'POST', signal: ctl.signal, body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${s.token}` } });
  } finally { clearTimeout(t); }
}

/** Replays ingests that failed while offline. 4xx = invalid/stale → dropped. Network/5xx → kept for later. */
export async function flushQueue(deps: Deps): Promise<number> {
  const s = await deps.getSession(); if (!s) return 0;
  const items = await deps.queue.drain(); let sent = 0;
  for (const it of items) {
    try { const r = await post(deps, s, it.body); if (r.status >= 500 || r.status === 429) await deps.queue.push(it); else sent++; }
    catch { await deps.queue.push(it); }
  }
  return sent;
}

/** Handles one forwarded notification (JSON string from the native service). Only structured fields leave the phone. */
export async function handleNotification(raw: string, deps: Deps): Promise<Outcome> {
  let n: { app?: string; title?: string; text?: string; bigText?: string; time?: string };
  try { n = JSON.parse(raw); } catch { return 'ignored'; }
  const text = [n.title, n.bigText || n.text].filter(Boolean).join(' | ');
  const when = new Date(Number(n.time) || Date.now()).toISOString();
  const p = parsePayment(text, { source: 'notification', receivedAt: when });
  if (!p) return 'ignored'; // OTPs, promos, chats, anything that isn't a completed payment

  const body = { parsed: { direction: p.direction, amount: p.amount, counterparty: p.counterparty, counterparty_is_person: p.counterpartyIsPerson, upi_ref: p.upiRef, account_last4: p.accountLast4, instrument: p.instrument, occurred_at: p.occurredAt },
    source: 'notification', received_at: when, package: n.app }; // NOTE: no raw text, title or body is ever included
  const s = await deps.getSession();
  if (!s) { await deps.queue.push({ body, at: Date.now() }); return 'no_session'; }
  await flushQueue(deps).catch(() => {});
  try {
    const r = await post(deps, s, body);
    if (r.status >= 500 || r.status === 429) { await deps.queue.push({ body, at: Date.now() }); return 'queued'; }
    if (!r.ok) return 'error';
    const j = await r.json();
    if (j.action === 'prompt' && j.prompt) { await deps.notify({ title: j.prompt.title, body: j.prompt.body, captureId: j.prompt.capture_id }); return 'prompt'; }
    return j.action === 'duplicate' ? 'duplicate' : 'saved';
  } catch { await deps.queue.push({ body, at: Date.now() }); return 'queued'; }
}
