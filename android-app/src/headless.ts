import { AppRegistry, Platform } from 'react-native';
import * as Notifications from 'expo-notifications';
import { HEADLESS_TASK } from 'hisaabbol-notification-listener';
import { handleNotification, type Deps } from './ingest';
import { getSession, queue } from './storage';
import { CHANNEL_ID } from './config';

export async function ensureChannel() {
  if (Platform.OS === 'android') await Notifications.setNotificationChannelAsync(CHANNEL_ID, { name: 'Payment questions', importance: Notifications.AndroidImportance.HIGH, vibrationPattern: [0, 200, 100, 200] });
}
export const realDeps: Deps = {
  getSession, queue, fetchFn: fetch,
  async notify({ title, body, captureId }) {
    await ensureChannel();
    await Notifications.scheduleNotificationAsync({ content: { title, body, data: { captureId }, sound: true }, trigger: { channelId: CHANNEL_ID } as Notifications.NotificationTriggerInput });
  },
};
/** Runs in the background (even when the app is closed) every time an allow-listed payment notification arrives. */
export function registerHeadless() {
  AppRegistry.registerHeadlessTask(HEADLESS_TASK, () => async (data: { notification?: string }) => { if (data?.notification) await handleNotification(data.notification, realDeps).catch(() => {}); });
}
