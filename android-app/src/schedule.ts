export const DIGEST_ID = 'hb-digest';
export function parseHHMM(s: string): { hour: number; minute: number } | null {
  const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(s || ''); return m ? { hour: +m[1], minute: +m[2] } : null;
}
export interface Sched { cancel(id: string): Promise<void>; schedule(req: { identifier: string; hour: number; minute: number; title: string; body: string; route: string }): Promise<void> }
/** One repeating evening check-in at the user's chosen time. Re-scheduling replaces the previous one. Returns false for a bad time. */
export async function scheduleDigest(time: string, s: Sched): Promise<boolean> {
  const t = parseHHMM(time); if (!t) return false;
  await s.cancel(DIGEST_ID);
  await s.schedule({ identifier: DIGEST_ID, ...t, title: 'Evening check-in', body: 'Any payments to explain? Tap to see them.', route: '#/activity' });
  return true;
}
