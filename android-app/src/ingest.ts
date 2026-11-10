import { parsePayment } from './paymentParser';
import { REQUEST_TIMEOUT_MS } from './config';

export interface Session { token: string; base: string }
export interface QueuedIngest { body: unknown; at: number; historyId?: string }
export interface NotificationHistoryEntry {
  id: string;
  receivedAt: string;
  app: string;
  outcome: Outcome;
  direction?: 'debit' | 'credit';
  amountPaise?: number;
  counterparty?: string | null;
}
export interface Deps {
  getSession(): Promise<Session | null>;
  fetchFn: typeof fetch;
  notify(n: { title: string; body: string; captureId: number }): Promise<void>;
  queue: { push(i: QueuedIngest): Promise<void>; drain(): Promise<QueuedIngest[]> };
  recordHistory(entry: NotificationHistoryEntry): Promise<void>;
}
export type Outcome = 'ignored' | 'prompt' | 'saved' | 'duplicate' | 'queued' | 'no_session' | 'error' | 'prompt_failed';

function historyId() { return `${Date.now()}-${Math.random().toString(36).slice(2)}`; }

async function saveHistory(deps: Deps, entry: NotificationHistoryEntry) {
  try { await deps.recordHistory(entry); }
  catch (error) { console.warn('Could not save local notification history', error); }
}

function queuedHistory(item: QueuedIngest, outcome: Outcome): NotificationHistoryEntry {
  const body = item.body as { package?: string; received_at?: string; parsed?: { direction?: 'debit' | 'credit'; amount?: number; amount_paise?: number; counterparty?: string | null } };
  const parsed = body.parsed;
  return {
    id: item.historyId || historyId(),
    receivedAt: body.received_at || new Date(item.at).toISOString(),
    app: body.package || 'unknown',
    outcome,
    ...(parsed ? {
      direction: parsed.direction,
      amountPaise: parsed.amount_paise ?? (parsed.amount ? Math.round(parsed.amount * 100) : undefined),
      counterparty: parsed.counterparty,
    } : {}),
  };
}

async function notifyForResult(deps: Deps, response: Response, item: QueuedIngest): Promise<Outcome> {
  if (!response.ok) return 'error';
  const result = await response.json();
  if (result.action === 'prompt' && result.prompt) {
    try {
      await deps.notify({ title: result.prompt.title, body: result.prompt.body, captureId: result.prompt.capture_id });
      return 'prompt';
    } catch (error) {
      console.warn('Payment was ingested, but its question notification could not be shown', error);
      return 'prompt_failed';
    }
  }
  return result.action === 'duplicate' ? 'duplicate' : 'saved';
}

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
    try {
      const r = await post(deps, s, it.body);
      if (r.status >= 500 || r.status === 429) await deps.queue.push(it);
      else {
        const outcome = await notifyForResult(deps, r, it);
        await saveHistory(deps, queuedHistory(it, outcome));
        sent++;
      }
    }
    catch { await deps.queue.push(it); }
  }
  return sent;
}

/** Handles one forwarded notification (JSON string from the native service). Only structured fields leave the phone. */
export async function handleNotification(raw: string, deps: Deps): Promise<Outcome> {
  let n: { app?: string; title?: string; text?: string; bigText?: string; time?: string };
  try { n = JSON.parse(raw); } catch { return 'ignored'; }
  const text = [n.title, n.bigText || n.text].filter(Boolean).join(' | ');
  const parsedDate = new Date(Number(n.time) || Date.now());
  const when = Number.isFinite(parsedDate.getTime()) ? parsedDate.toISOString() : new Date().toISOString();
  const id = historyId();
  const app = n.app || 'unknown';
  const log = (outcome: Outcome, p?: ReturnType<typeof parsePayment>) => saveHistory(deps, {
    id, receivedAt: when, app, outcome,
    ...(p ? { direction: p.direction, amountPaise: Math.round(p.amount * 100), counterparty: p.counterparty } : {}),
  });
  const p = parsePayment(text, { source: 'notification', receivedAt: when });
  if (!p) { await log('ignored'); return 'ignored'; } // OTPs, promos, chats, anything that isn't a completed payment

  const body = { parsed: { direction: p.direction, amount: p.amount, counterparty: p.counterparty, counterparty_is_person: p.counterpartyIsPerson, upi_ref: p.upiRef, account_last4: p.accountLast4, instrument: p.instrument, occurred_at: p.occurredAt },
    source: 'notification', received_at: when, package: n.app }; // NOTE: no raw text, title or body is ever included
  const s = await deps.getSession();
  if (!s) { await deps.queue.push({ body, at: Date.now(), historyId: id }); await log('no_session', p); return 'no_session'; }
  await flushQueue(deps).catch(() => {});
  try {
    const r = await post(deps, s, body);
    if (r.status >= 500 || r.status === 429) {
      await deps.queue.push({ body, at: Date.now(), historyId: id }); await log('queued', p); return 'queued';
    }
    const outcome = await notifyForResult(deps, r, { body, at: Date.now(), historyId: id });
    await log(outcome, p);
    return outcome;
  } catch {
    await deps.queue.push({ body, at: Date.now(), historyId: id }); await log('queued', p); return 'queued';
  }
}
