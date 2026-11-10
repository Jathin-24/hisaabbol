import { NativeModules, Platform } from 'react-native';

const Native = NativeModules.HBNotificationListener;
export const HEADLESS_TASK = 'HBNotification';

export async function getPermissionStatus() {
  if (Platform.OS !== 'android' || !Native) return 'unavailable';
  return Native.getPermissionStatus(); // 'authorized' | 'denied'
}
export function requestPermission() { if (Native) Native.requestPermission(); }
export function setAllowedPackages(pkgs) { if (Native) Native.setAllowedPackages(pkgs); }
export async function isIgnoringBatteryOptimizations() { return Native ? Native.isIgnoringBatteryOptimizations() : true; }
export function requestIgnoreBatteryOptimizations() { if (Native) Native.requestIgnoreBatteryOptimizations(); }
