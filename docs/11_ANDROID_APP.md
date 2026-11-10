# 11 — Android app (auto-detects payments from notifications)

`android-app/` is a thin Expo (SDK 54) shell: **the same tested web UI inside a WebView**, plus the native part the web cannot do — reading payment notifications in the background.

```
bank SMS / GPay / PhonePe notification
   └► HBNotificationListenerService (Java)   drops everything not from an allow-listed app, reads text only (no icons/images)
        └► HBHeadlessTaskService → JS task "HBNotification" (runs even when the app is closed)
             └► src/ingest.ts: parsePayment() ON THE PHONE → only {amount, payee, ref, last4, time} are POSTed to /captures/ingest
                  └► server says "prompt" → local notification "₹450 paid to ZOMATO — What was it for?"
                       └► tap → app opens straight on the Capture screen → hold phone near mouth, tap, speak → draft → Save
```
**Privacy:** the message text never leaves the phone (a unit test asserts the posted body contains none of it). The allow-list is enforced in native code, before JavaScript runs. We do not use the READ_SMS permission.

**Unanswered payments:** when the app opens after onboarding, it opens the oldest pending payment directly. The Home and Activity screens also list every unanswered payment. A daily reminder at the time chosen in Settings opens Activity so the user can answer or skip the pending payments. Tapping a payment notification opens that exact capture. Tapped notification routes are queued until the WebView has registered its message handler, avoiding a startup race.

**Also in the app:** working hardware Back button and a daily check-in using `expo-notifications` and WebView messages.

## Build & install
```bash
cd android-app
npm install
npm run typecheck && npm test            # 12 tests
# Option A — cloud build (needs a free Expo account):
npm i -g eas-cli && eas login
EXPO_PUBLIC_SERVER_URL=https://YOUR-SERVER eas build -p android --profile preview     # → installable .apk link
# Option B — local (needs Android Studio + a phone with USB debugging):
EXPO_PUBLIC_SERVER_URL=https://YOUR-SERVER npx expo run:android --device
# Option C — build an installable APK locally on Windows (Android SDK + Java 17):
npx expo prebuild --platform android
cd android
.\gradlew.bat assembleRelease
# APK: app\build\outputs\apk\release\app-release.apk
```
The server must be **https** (the WebView only allows the microphone on secure origins). If no server URL is baked into the build, enter the HTTPS backend address on first launch. If the backend requires `REGISTRATION_KEY`, enter it on that same screen; it is stored with Android SecureStore and sent only during device registration. The backend must be deployed separately and have its Gnani key configured; API keys must never be embedded in the APK. Edit `src/config.ts` to change the allow-listed apps.

The Render Blueprint is configured for the free plan for hackathon demos. Free instances can sleep while idle, may take time to wake, and have ephemeral storage: SQLite data can be lost after a restart or redeploy. Do not use this deployment as the only copy of important financial data.

## First run on the phone
1. Open the app → it asks for the server address (pre-filled if you built with `EXPO_PUBLIC_SERVER_URL`) → onboarding → on the last step tap **Turn on notification access** → switch HisaabBol on in Android settings → come back. If skipped, the Home and More screens keep a notification-access shortcut until enabled.
2. Allow microphone and notifications when asked. If voice still does not start, open Android **Settings → Apps → HisaabBol → Permissions → Microphone** and allow it. The connected server must use HTTPS. On Xiaomi/Oppo/Vivo/Samsung also allow **autostart / unrestricted battery** or the OS will kill the background service.
3. Payment alerts are accepted only from the Android package allow-list in `android-app/src/config.ts` (UPI apps and supported messaging apps). Bank alerts delivered through an unsupported banking app are ignored; add its verified package ID to that list and rebuild if needed.

## Device test checklist (I could not run these — please do, in this order)
| # | Test | Expected |
|---|---|---|
| 1 | Install APK, open, connect server | onboarding appears; no crash |
| 2 | Enable notification access | Settings shows HisaabBol enabled; app shows "Notification access is on" |
| 3 | Send yourself a real payment (₹1 to a friend, or have a friend pay you) with the app **closed** | within seconds: "₹1 paid to … — What was it for?" notification (payments < your minimum are auto-saved silently — set minimum to ₹0 for this test) |
| 4 | Tap it | app opens on the Capture screen with that payment |
| 5 | Tap mic, say "chai", tap again | transcript + category draft; Save → success + Home updated |
| 6 | Airplane mode, pay, re-enable network, open app | payment appears (queued then synced) |
| 7 | Same payment via bank SMS + GPay notification | only ONE prompt (server dedupes) |
| 8 | OTP / promo SMS | nothing happens |
| 9 | Reboot phone, pay again | still detected (Android re-binds the listener automatically) |
If 3 fails: `adb logcat -s HBNotificationListener ReactNativeJS` — the first thing to check is that the package id of your UPI app is in `ALLOWED_PACKAGES` (Settings → Apps → app info, or `adb shell pm list packages | grep -i pay`).

## Honest status
✅ TypeScript compiles; 9 unit tests (whitelisting is native; parsing/privacy/queueing/prompting are tested); `expo prebuild` generates the Android project; Expo autolinking resolves the native module (`HBNotificationListenerPackage`).
❌ **Not compiled or run on a device by me** (no Android SDK here): the 5 Java files in `modules/hb-notification-listener/android` are small and follow the standard HeadlessJsTaskService pattern, but a first Gradle build may need a tweak. WebView microphone permission flow is standard but untested here.
⚠️ Package ids in the allow-list are from memory — verify on your phone. Bank apps' own notifications are not allow-listed by default (add them if you want them).
⚠️ Android only. iOS does not allow reading other apps' notifications.
