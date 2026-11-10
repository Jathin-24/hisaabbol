/** Apps whose notifications are ever looked at. Everything else is dropped in native code. Verify ids on your device. */
export const ALLOWED_PACKAGES = [
  'com.google.android.apps.nbu.paisa.user', // Google Pay
  'com.phonepe.app', 'net.one97.paytm', 'in.org.npci.upiapp', // PhonePe, Paytm, BHIM
  'in.amazon.mShop.android.shopping', 'com.dreamplug.androidapp', // Amazon, CRED
  'com.google.android.apps.messaging', 'com.samsung.android.messaging', 'com.android.mms', 'com.android.messaging', // SMS apps (bank alerts)
];
export const DEFAULT_SERVER_URL = process.env.EXPO_PUBLIC_SERVER_URL ?? '';
export const CHANNEL_ID = 'payments';
export const REQUEST_TIMEOUT_MS = 10000;
