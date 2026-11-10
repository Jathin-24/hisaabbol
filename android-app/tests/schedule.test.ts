import { describe, expect, it } from 'vitest';
import { DIGEST_ID, parseHHMM, scheduleDigest, type Sched } from '../src/schedule';

const fake = () => { const log: any[] = []; const s: Sched = { cancel: async id => { log.push(['cancel', id]); }, schedule: async r => { log.push(['schedule', r]); } }; return { s, log }; };
describe('evening check-in', () => {
  it('parses times', () => { expect(parseHHMM('21:00')).toEqual({ hour: 21, minute: 0 }); expect(parseHHMM('07:45')).toEqual({ hour: 7, minute: 45 }); for (const bad of ['', '24:00', '9:00', 'abc', '12:60']) expect(parseHHMM(bad)).toBeNull(); });
  it('replaces the previous schedule and opens Activity on tap', async () => {
    const { s, log } = fake(); expect(await scheduleDigest('20:30', s)).toBe(true);
    expect(log[0]).toEqual(['cancel', DIGEST_ID]); expect(log[1][1]).toMatchObject({ identifier: DIGEST_ID, hour: 20, minute: 30, route: '#/activity' });
  });
  it('ignores an invalid time without scheduling', async () => { const { s, log } = fake(); expect(await scheduleDigest('nope', s)).toBe(false); expect(log).toHaveLength(0); });
});
