import { beforeEach, describe, expect, it, vi } from 'vitest';

const mockStorage = vi.hoisted(() => ({ data: new Map<string, string>() }));
vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: async (key: string) => mockStorage.data.get(key) ?? null,
    setItem: async (key: string, value: string) => { mockStorage.data.set(key, value); },
    removeItem: async (key: string) => { mockStorage.data.delete(key); },
  },
}));
vi.mock('expo-secure-store', () => ({
  getItemAsync: async () => null,
  setItemAsync: async () => {},
  deleteItemAsync: async () => {},
}));

import { clearNotificationHistory, getNotificationHistory, recordNotificationHistory } from '../src/storage';

describe('notification history storage', () => {
  beforeEach(() => mockStorage.data.clear());

  it('keeps only the latest 100 structured entries and excludes extra message text', async () => {
    for (let i = 0; i < 101; i++) {
      const entry = Object.assign({
        id: `entry-${i}`, receivedAt: new Date(1_700_000_000_000 + i * 1000).toISOString(),
        app: 'com.phonepe.app', outcome: 'saved' as const, direction: 'debit' as const, amountPaise: 1000,
        counterparty: 'Cafe', rawText: 'private bank notification',
      });
      await recordNotificationHistory(entry);
    }

    const entries = await getNotificationHistory();
    expect(entries).toHaveLength(100);
    expect(entries[0].id).toBe('entry-100');
    expect(JSON.stringify(entries)).not.toContain('private bank notification');
  });

  it('updates an existing event and clears history', async () => {
    const initial = { id: 'same', receivedAt: new Date().toISOString(), app: 'messages', outcome: 'queued' as const };
    await recordNotificationHistory(initial);
    await recordNotificationHistory({ ...initial, outcome: 'saved' });
    expect(await getNotificationHistory()).toHaveLength(1);
    expect((await getNotificationHistory())[0].outcome).toBe('saved');
    await clearNotificationHistory();
    expect(await getNotificationHistory()).toEqual([]);
  });
});
