import * as SecureStore from 'expo-secure-store';
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { QueuedIngest, Session } from './ingest';

const SESSION = 'hb_session', SERVER = 'hb_server', REGISTRATION_KEY = 'hb_registration_key', QUEUE = 'hb_ingest_queue';
export const getSession = async (): Promise<Session | null> => { try { const v = await SecureStore.getItemAsync(SESSION); return v ? JSON.parse(v) : null; } catch { return null; } };
export const setSession = (s: Session) => SecureStore.setItemAsync(SESSION, JSON.stringify(s));
export const getServer = () => SecureStore.getItemAsync(SERVER);
export const setServer = (u: string) => SecureStore.setItemAsync(SERVER, u);
export const getRegistrationKey = () => SecureStore.getItemAsync(REGISTRATION_KEY);
export const setRegistrationKey = (key: string) => key ? SecureStore.setItemAsync(REGISTRATION_KEY, key) : SecureStore.deleteItemAsync(REGISTRATION_KEY);
export const clearAll = async () => { await SecureStore.deleteItemAsync(SESSION); await AsyncStorage.removeItem(QUEUE); };
export const queue = {
  async push(i: QueuedIngest) { const q = JSON.parse((await AsyncStorage.getItem(QUEUE)) || '[]'); q.push(i); await AsyncStorage.setItem(QUEUE, JSON.stringify(q.slice(-200))); },
  async drain(): Promise<QueuedIngest[]> { const q = JSON.parse((await AsyncStorage.getItem(QUEUE)) || '[]'); await AsyncStorage.removeItem(QUEUE); return q; },
};
