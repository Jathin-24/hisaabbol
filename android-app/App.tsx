import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, BackHandler, Linking, PermissionsAndroid, Platform, Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { WebView, type WebViewMessageEvent } from 'react-native-webview';
import * as Notifications from 'expo-notifications';
import { getPermissionStatus, requestPermission, setAllowedPackages, isIgnoringBatteryOptimizations, requestIgnoreBatteryOptimizations } from 'hisaabbol-notification-listener';
import { ALLOWED_PACKAGES, DEFAULT_SERVER_URL } from './src/config';
import { ensureChannel, realDeps } from './src/headless';
import { flushQueue } from './src/ingest';
import { getRegistrationKey, getServer, setRegistrationKey, setServer, setSession } from './src/storage';
import { scheduleDigest } from './src/schedule';
import { realSched } from './src/schedule.native';

Notifications.setNotificationHandler({ handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: true, shouldSetBadge: false }) });
const ACCENT = '#d9480f';
const clean = (u: string) => u.trim().replace(/\/+$/, '');

export default function App() {
  const [server, setServerState] = useState<string | null | undefined>(undefined);
  const [input, setInput] = useState(DEFAULT_SERVER_URL);
  const [registrationSecret, setRegistrationSecret] = useState('');
  const [err, setErr] = useState('');
  const [failed, setFailed] = useState(false);
  const web = useRef<WebView>(null);
  const loaded = useRef(false);
  const pendingCapture = useRef<number | null>(null);
  const pendingRoute = useRef<string | null>(null);
  const last = Notifications.useLastNotificationResponse();

  const toWeb = useCallback((m: object) => web.current?.postMessage(JSON.stringify(m)), []);
  const sendStatus = useCallback(async () => toWeb({ type: 'notif_status', status: await getPermissionStatus(), battery: await isIgnoringBatteryOptimizations() }), [toWeb]);
  const openCapture = useCallback((id: number) => { if (loaded.current) toWeb({ type: 'open_capture', id }); else pendingCapture.current = id; }, [toWeb]);
  const navigate = useCallback((hash: string) => { if (loaded.current) toWeb({ type: 'navigate', hash }); else pendingRoute.current = hash; }, [toWeb]);

  useEffect(() => {
    Promise.all([getServer(), getRegistrationKey()]).then(([s, k]) => {
      setInput(s || DEFAULT_SERVER_URL); setRegistrationSecret(k || ''); setServerState(s || null);
    });
  }, []);
  useEffect(() => { // permissions + native allow-list, once
    (async () => {
      setAllowedPackages(ALLOWED_PACKAGES); await ensureChannel();
      if (Platform.OS === 'android') await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.RECORD_AUDIO).catch(() => {});
      await Notifications.requestPermissionsAsync().catch(() => {});
    })();
  }, []);
  useEffect(() => { const s = AppState.addEventListener('change', st => { if (st === 'active') { sendStatus(); flushQueue(realDeps).catch(() => {}); } }); return () => s.remove(); }, [sendStatus]);
  useEffect(() => {
    const d = last?.notification.request.content.data as { captureId?: number; route?: string } | undefined;
    if (typeof d?.captureId === 'number') openCapture(d.captureId);
    else if (typeof d?.route === 'string') navigate(d.route);
  }, [last, navigate, openCapture]);
  useEffect(() => { const h = BackHandler.addEventListener('hardwareBackPress', () => { if (loaded.current) { toWeb({ type: 'back' }); return true; } return false; }); return () => h.remove(); }, [toWeb]);

  const connect = async () => {
    const u = clean(input); setErr('');
    try { const r = await fetch(`${u}/api/v1/health`); if (!(await r.json()).ok) throw new Error(); await setServer(u); await setRegistrationKey(registrationSecret.trim()); setServerState(u); }
    catch { setErr('Could not reach that server. Check the address (it must be https for the microphone to work).'); }
  };

  const onMessage = async (e: WebViewMessageEvent) => {
    let m: any; try { m = JSON.parse(e.nativeEvent.data); } catch { return; }
    if (m.type === 'web_ready') {
      loaded.current = true;
      if (pendingCapture.current !== null) { toWeb({ type: 'open_capture', id: pendingCapture.current }); pendingCapture.current = null; }
      if (pendingRoute.current) { toWeb({ type: 'navigate', hash: pendingRoute.current }); pendingRoute.current = null; }
      sendStatus();
    }
    if (m.type === 'get_registration_key') toWeb({ type: 'registration_key', key: registrationSecret });
    if (m.type === 'registration_rejected') { await setServer(''); setServerState(null); }
    if (m.type === 'session' && m.token && m.base) { await setSession({ token: m.token, base: m.base }); flushQueue(realDeps).catch(() => {}); }
    if (m.type === 'get_notif_status') sendStatus();
    if (m.type === 'request_notif_access') { requestPermission(); }
    if (m.type === 'request_battery') requestIgnoreBatteryOptimizations();
    if (m.type === 'digest' && typeof m.time === 'string') scheduleDigest(m.time, realSched).catch(() => {});
    if (m.type === 'exit') BackHandler.exitApp();
  };

  if (server === undefined) return <View style={s.c}><ActivityIndicator color={ACCENT} /></View>;
  if (!server) return (
    <SafeAreaView style={[s.c, { padding: 24 }]}><StatusBar style="dark" />
      <Text style={s.h}>HisaabBol</Text><Text style={s.p}>Enter your HisaabBol server address.</Text>
      <TextInput style={s.in} value={input} onChangeText={setInput} placeholder="https://your-server.example.com" autoCapitalize="none" autoCorrect={false} keyboardType="url" />
      <Text style={s.p}>Registration key (only if your server requires one)</Text>
      <TextInput style={s.in} value={registrationSecret} onChangeText={setRegistrationSecret} placeholder="Optional" autoCapitalize="none" autoCorrect={false} secureTextEntry />
      {!!err && <Text style={s.err}>{err}</Text>}
      <Pressable style={s.btn} onPress={connect}><Text style={s.bt}>Connect</Text></Pressable>
    </SafeAreaView>);
  if (failed) return (
    <SafeAreaView style={[s.c, { padding: 24 }]}><Text style={s.h}>Can’t reach the server</Text><Text style={s.p}>{server}</Text>
      <Pressable style={s.btn} onPress={() => setFailed(false)}><Text style={s.bt}>Try again</Text></Pressable>
      <Pressable onPress={() => { setServer(''); setServerState(null); setFailed(false); }}><Text style={[s.p, { color: ACCENT, marginTop: 16 }]}>Change server</Text></Pressable>
    </SafeAreaView>);
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#fbf8f3' }}><StatusBar style="auto" />
      <WebView ref={web} source={{ uri: server + '/' }} originWhitelist={[server]} javaScriptEnabled domStorageEnabled
        mediaCapturePermissionGrantType="grantIfSameHostElsePrompt" mediaPlaybackRequiresUserAction={false} allowsInlineMediaPlayback onMessage={onMessage} setSupportMultipleWindows={false}
        onError={() => setFailed(true)} onHttpError={e => e.nativeEvent.statusCode >= 500 && setFailed(true)}
        onShouldStartLoadWithRequest={r => { if (r.url.startsWith(server)) return true; Linking.openURL(r.url).catch(() => {}); return false; }} />
    </SafeAreaView>);
}
const s = StyleSheet.create({
  c: { flex: 1, justifyContent: 'center', backgroundColor: '#fbf8f3' }, h: { fontSize: 28, fontWeight: '800', color: '#1f1b16' }, p: { color: '#6b645a', marginVertical: 8 },
  in: { borderWidth: 1, borderColor: '#e9e2d6', borderRadius: 12, padding: 14, backgroundColor: '#fff', marginVertical: 12, fontSize: 16 }, err: { color: '#c0392b', marginBottom: 8 },
  btn: { backgroundColor: ACCENT, borderRadius: 12, padding: 16, alignItems: 'center' }, bt: { color: '#fff', fontWeight: '700', fontSize: 16 },
});
