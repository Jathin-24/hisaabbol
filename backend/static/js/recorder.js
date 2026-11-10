// Microphone capture with live level + silence auto-stop, then converts to 16 kHz mono WAV (Gnani accepts wav/mp3/ogg/flac/aac/m4a — not webm).
export class Recorder {
  constructor({ maxMs = 12000, silenceMs = 1500, onLevel = () => {}, onAutoStop = () => {} } = {}) { Object.assign(this, { maxMs, silenceMs, onLevel, onAutoStop }); }
  async start() {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error('Microphone access requires an HTTPS server. Reconnect using the secure HTTPS address.');
    }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC(); const src = this.ctx.createMediaStreamSource(this.stream);
    this.an = this.ctx.createAnalyser(); this.an.fftSize = 512; src.connect(this.an);
    this.chunks = []; this.mr = new MediaRecorder(this.stream);
    this.mr.ondataavailable = e => e.data.size && this.chunks.push(e.data);
    this.mr.start(); this.t0 = Date.now(); this.spoke = false; this.lastVoice = Date.now(); this.stopped = false;
    const buf = new Uint8Array(this.an.fftSize);
    const tick = () => {
      if (this.stopped) return;
      this.an.getByteTimeDomainData(buf); let s = 0; for (const v of buf) { const x = (v - 128) / 128; s += x * x; }
      const rms = Math.sqrt(s / buf.length); this.onLevel(Math.min(1, rms * 5));
      const now = Date.now();
      if (rms > 0.03) { this.spoke = true; this.lastVoice = now; }
      if (now - this.t0 > this.maxMs || (this.spoke && now - this.lastVoice > this.silenceMs)) { this.onAutoStop(); return; }
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  }
  stop() {
    return new Promise(res => {
      this.stopped = true; cancelAnimationFrame(this.raf);
      const fin = () => { this.stream.getTracks().forEach(t => t.stop()); this.ctx.close().catch(() => {}); res(new Blob(this.chunks, { type: this.mr.mimeType || 'audio/webm' })); };
      if (this.mr.state === 'inactive') return fin();
      this.mr.onstop = fin; this.mr.stop();
    });
  }
  cancel() { this.stopped = true; cancelAnimationFrame(this.raf); try { this.mr.state !== 'inactive' && this.mr.stop(); } catch {} this.stream?.getTracks().forEach(t => t.stop()); this.ctx?.close().catch(() => {}); }
}
export async function toWav(blob) {
  const ab = await blob.arrayBuffer();
  const AC = window.AudioContext || window.webkitAudioContext; const ctx = new AC();
  const buf = await new Promise((ok, no) => ctx.decodeAudioData(ab, ok, no)); ctx.close().catch(() => {});
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(buf.duration * 16000)), 16000);
  const s = off.createBufferSource(); s.buffer = buf; s.connect(off.destination); s.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const dv = new DataView(new ArrayBuffer(44 + pcm.length * 2)); const w = (o, str) => [...str].forEach((c, i) => dv.setUint8(o + i, c.charCodeAt(0)));
  w(0, 'RIFF'); dv.setUint32(4, 36 + pcm.length * 2, true); w(8, 'WAVEfmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
  dv.setUint32(24, 16000, true); dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); w(36, 'data'); dv.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) dv.setInt16(44 + i * 2, Math.max(-1, Math.min(1, pcm[i])) * 0x7fff, true);
  return new Blob([dv], { type: 'audio/wav' });
}
