import { describe, expect, it } from 'vitest';
import { flushQueue, handleNotification, type Deps, type QueuedIngest } from '../src/ingest';

function mk(over: Partial<{ status: number; json: any; throws: boolean; session: boolean }> = {}) {
  const calls: { url: string; body: string; auth: string }[] = []; const notes: any[] = []; const history: any[] = []; let q: QueuedIngest[] = [];
  const deps: Deps = {
    getSession: async () => (over.session === false ? null : { token: 'tok', base: 'https://srv' }),
    fetchFn: (async (url: string, init: any) => {
      calls.push({ url, body: init.body, auth: init.headers.Authorization }); if (over.throws) throw new TypeError('network');
      return { ok: (over.status ?? 200) < 400, status: over.status ?? 200, json: async () => over.json ?? { action: 'prompt', prompt: { title: '₹450 paid to ZOMATO', body: 'What was it for?', capture_id: 7 } } };
    }) as any,
    notify: async n => { notes.push(n); },
    queue: { push: async i => { q.push(i); }, drain: async () => { const d = q; q = []; return d; } },
    recordHistory: async entry => { const i = history.findIndex(x => x.id === entry.id); if (i >= 0) history.splice(i, 1); history.unshift(entry); },
  };
  return { deps, calls, notes, history, queued: () => q };
}
const n = (o: object) => JSON.stringify({ app: 'com.phonepe.app', time: '1762600000000', title: '', text: '', bigText: '', ...o });
const HDFC = 'Sent Rs.450.00 From HDFC Bank A/C *1234 To ZOMATO On 08/11/26 Ref 123456789012 Not You? Call 18002586161';

describe('handleNotification', () => {
  it('ignores non-payments (OTP, promos, chat) without touching the network', async () => {
    const t = mk();
    for (const text of ['123456 is your OTP for Rs 250.00', 'Get flat Rs 200 cashback now', 'hey are you coming tonight?', 'Your payment of Rs 250 failed']) expect(await handleNotification(n({ text }), t.deps)).toBe('ignored');
    expect(t.calls).toHaveLength(0);
    expect(t.history).toHaveLength(4);
    expect(t.history.every(x => x.outcome === 'ignored' && !JSON.stringify(x).includes('OTP'))).toBe(true);
  });
  it('ignores malformed input', async () => { const t = mk(); expect(await handleNotification('not json', t.deps)).toBe('ignored'); });
  it('parses on-device, posts ONLY structured fields (never the message text), and shows the prompt', async () => {
    const t = mk(); expect(await handleNotification(n({ title: 'Bank', text: HDFC }), t.deps)).toBe('prompt');
    expect(t.calls).toHaveLength(1); const { url, body, auth } = t.calls[0];
    expect(url).toBe('https://srv/api/v1/captures/ingest'); expect(auth).toBe('Bearer tok');
    const b = JSON.parse(body); expect(b.parsed).toMatchObject({ direction: 'debit', amount: 450, counterparty: 'ZOMATO', upi_ref: '123456789012', account_last4: '1234' });
    for (const leak of ['Not You', 'HDFC Bank A/C', 'Call 1800', 'Sent Rs']) expect(body).not.toContain(leak);
    expect(t.notes).toEqual([{ title: '₹450 paid to ZOMATO', body: 'What was it for?', captureId: 7 }]);
    expect(t.history[0]).toMatchObject({ app: 'com.phonepe.app', outcome: 'prompt', direction: 'debit', amountPaise: 45000, counterparty: 'ZOMATO' });
    expect(JSON.stringify(t.history)).not.toContain('HDFC Bank');
  });
  it('handles UPI-app notifications (title + text)', async () => { const t = mk(); expect(await handleNotification(n({ title: 'Google Pay', text: 'Paid ₹250 to Zomato' }), t.deps)).toBe('prompt'); expect(JSON.parse(t.calls[0].body).parsed.amount).toBe(250); });
  it('does not notify for auto-saved / duplicate results', async () => {
    let t = mk({ json: { action: 'auto_saved' } }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('saved'); expect(t.notes).toHaveLength(0);
    t = mk({ json: { action: 'duplicate' } }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('duplicate'); expect(t.notes).toHaveLength(0);
  });
  it('queues when offline or the server errors, and keeps the data', async () => {
    let t = mk({ throws: true }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('queued'); expect(t.queued()).toHaveLength(1);
    t = mk({ status: 503 }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('queued'); expect(t.queued()).toHaveLength(1);
  });
  it('queues when not signed in yet (no session) instead of dropping the payment', async () => { const t = mk({ session: false }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('no_session'); expect(t.queued()).toHaveLength(1); expect(t.calls).toHaveLength(0); });
  it('updates the same local history entry when a queued payment is replayed', async () => {
    const t = mk({ session: false }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('no_session');
    const originalId = t.history[0].id;
    const replay = mk(); (replay.deps.queue as any) = t.deps.queue;
    replay.deps.recordHistory = t.deps.recordHistory;
    await flushQueue(replay.deps);
    expect(t.history).toHaveLength(1);
    expect(t.history[0]).toMatchObject({ id: originalId, outcome: 'prompt' });
  });
  it('drops requests the server rejects (4xx) rather than retrying forever', async () => { const t = mk({ status: 422 }); expect(await handleNotification(n({ text: HDFC }), t.deps)).toBe('error'); expect(t.queued()).toHaveLength(0); });
  it('flushQueue replays queued items once a session exists', async () => {
    const t = mk({ throws: true }); await handleNotification(n({ text: HDFC }), t.deps); expect(t.queued()).toHaveLength(1);
    const ok = mk(); (ok.deps.queue as any) = t.deps.queue; expect(await flushQueue(ok.deps)).toBe(1); expect(ok.calls).toHaveLength(1); expect(t.queued()).toHaveLength(0);
  });
});
