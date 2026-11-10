import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { NotificationHistoryEntry, QueuedIngest, Session } from './ingest';

const SESSION = 'hb_session', SERVER = 'hb_server', REGISTRATION_KEY = 'hb_registration_key', QUEUE = 'hb_ingest_queue', HISTORY = 'hb_notification_history';
export const getSession = async (): Promise<Session | null> => { try { const v = await SecureStore.getItemAsync(SESSION); return v ? JSON.parse(v) : null; } catch { return null; } };
export const setSession = (s: Session) => SecureStore.setItemAsync(SESSION, JSON.stringify(s));
export const getServer = () => SecureStore.getItemAsync(SERVER);
export const setServer = (u: string) => SecureStore.setItemAsync(SERVER, u);
export const getRegistrationKey = () => SecureStore.getItemAsync(REGISTRATION_KEY);
export const setRegistrationKey = (key: string) => key ? SecureStore.setItemAsync(REGISTRATION_KEY, key) : SecureStore.deleteItemAsync(REGISTRATION_KEY);
export const clearAll = async () => { await SecureStore.deleteItemAsync(SESSION); await AsyncStorage.removeItem(QUEUE); };
export async function getNotificationHistory(): Promise<NotificationHistoryEntry[]> {
  return JSON.parse((await AsyncStorage.getItem(HISTORY)) || '[]');
}
export async function recordNotificationHistory(entry: NotificationHistoryEntry): Promise<void> {
  const entries = await getNotificationHistory();
  const safeEntry: NotificationHistoryEntry = {
    id: entry.id,
    receivedAt: entry.receivedAt,
    app: entry.app,
    outcome: entry.outcome,
    ...(entry.direction ? { direction: entry.direction } : {}),
    ...(Number.isFinite(entry.amountPaise) ? { amountPaise: entry.amountPaise } : {}),
    ...(typeof entry.counterparty === 'string' ? { counterparty: entry.counterparty.slice(0, 120) } : {}),
  };
  const next = [safeEntry, ...entries.filter(x => x.id !== entry.id)]
    .sort((a, b) => Date.parse(b.receivedAt) - Date.parse(a.receivedAt))
    .slice(0, 100);
  await AsyncStorage.setItem(HISTORY, JSON.stringify(next));
}
export const clearNotificationHistory = () => AsyncStorage.removeItem(HISTORY);
export const queue = {
  async push(i: QueuedIngest) { const q = JSON.parse((await AsyncStorage.getItem(QUEUE)) || '[]'); q.push(i); await AsyncStorage.setItem(QUEUE, JSON.stringify(q.slice(-200))); },
  async drain(): Promise<QueuedIngest[]> { const q = JSON.parse((await AsyncStorage.getItem(QUEUE)) || '[]'); await AsyncStorage.removeItem(QUEUE); return q; },
};
