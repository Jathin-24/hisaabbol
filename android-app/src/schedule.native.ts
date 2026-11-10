import * as Notifications from 'expo-notifications';
import { CHANNEL_ID } from './config';
import type { Sched } from './schedule';

export const realSched: Sched = {
  cancel: id => Notifications.cancelScheduledNotificationAsync(id).catch(() => {}),
  schedule: async r => { await Notifications.scheduleNotificationAsync({ identifier: r.identifier, content: { title: r.title, body: r.body, data: { route: r.route } },
    trigger: { type: Notifications.SchedulableTriggerInputTypes.DAILY, hour: r.hour, minute: r.minute, channelId: CHANNEL_ID } }); },
};
