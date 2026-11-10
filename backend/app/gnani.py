"""Gnani Vachana client: Prisma STT (REST) + Timbre TTS (REST). Verified against docs.gnani.ai (Nov 2026).
Behaviour that matters in production:
  * accounts may be limited to ONE active request -> a semaphore serializes calls, 429 is retried with backoff
  * every failure becomes an ApiError with a stable code so the client can fall back to typing
  * GNANI_MOCK=true gives fake STT/TTS for demos/tests; responses are flagged provider="mock"
"""
import asyncio
import shutil
import struct
import subprocess
import tempfile
import time
import os

import httpx

from .config import cfg
from .errors import ApiError

SUPPORTED_EXT = {"wav", "mp3", "ogg", "flac", "aac", "m4a"}
STT_LANGS = {"bn-IN", "en-IN", "gu-IN", "hi-IN", "kn-IN", "ml-IN", "mr-IN", "pa-IN", "ta-IN", "te-IN"}

_sem: asyncio.Semaphore | None = None
_sem_size = 0
_transport: httpx.AsyncBaseTransport | None = None  # tests inject httpx.MockTransport here


def _semaphore() -> asyncio.Semaphore:
    global _sem, _sem_size
    if _sem is None or _sem_size != cfg.gnani_concurrency:
        _sem, _sem_size = asyncio.Semaphore(cfg.gnani_concurrency), cfg.gnani_concurrency
    return _sem


def validate_language_hint(hint: str) -> str:
    hint = (hint or "").strip()
    if hint == "indic-auto":
        return hint
    codes = [c.strip() for c in hint.split(",") if c.strip()]
    if not 1 <= len(codes) <= 4 or any(c not in STT_LANGS for c in codes):
        raise ApiError(422, "bad_language_hint", f"language_hint must be 1-4 of {sorted(STT_LANGS)} or 'indic-auto'")
    return ",".join(codes)


def prepare_audio(data: bytes, filename: str | None, content_type: str | None) -> tuple[bytes, str, str]:
    """Gnani accepts wav/mp3/ogg/flac/aac/m4a. Browsers often record webm/mp4 -> map or convert with ffmpeg."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    ct = (content_type or "").lower()
    if ext not in SUPPORTED_EXT:
        if "mp4" in ct or "m4a" in ct or "aac" in ct:
            ext = "m4a"
        elif "wav" in ct or "wave" in ct:
            ext = "wav"
        elif "mpeg" in ct or "mp3" in ct:
            ext = "mp3"
        elif "ogg" in ct and "opus" not in ct:
            ext = "ogg"
    if ext in SUPPORTED_EXT:
        return data, f"clip.{ext}", {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "flac": "audio/flac",
                                     "aac": "audio/aac", "m4a": "audio/mp4"}[ext]
    ff = shutil.which("ffmpeg")
    if not ff:
        raise ApiError(415, "unsupported_audio", "Send wav/mp3/ogg/flac/aac/m4a (this server has no ffmpeg to convert webm).")
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.bin"), os.path.join(d, "out.wav")
        open(src, "wb").write(data)
        r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "16000", dst], capture_output=True, timeout=20)
        if r.returncode != 0 or not os.path.exists(dst):
            raise ApiError(415, "audio_conversion_failed", "Could not decode the audio clip.")
        return open(dst, "rb").read(), "clip.wav", "audio/wav"


def _map_error(status: int, body: str) -> ApiError:
    b = (body or "")[:300]
    if status == 400:
        if "MAX_AUDIO_DURATION" in b:
            return ApiError(400, "audio_too_long", "Clip is longer than 30 seconds.")
        if "EMPTY_AUDIO" in b:
            return ApiError(400, "empty_audio", "The audio clip was empty.")
        return ApiError(400, "gnani_bad_request", b)
    if status == 402:
        return ApiError(503, "gnani_credits_exhausted", "Gnani credits are exhausted.")
    if status in (401, 403):
        return ApiError(502, "gnani_auth", "Gnani rejected the API key / scope.")
    if status == 429:
        return ApiError(503, "gnani_busy", "Gnani is busy (rate limit). Retry shortly.", retry_after=2)
    return ApiError(503, "gnani_unavailable", f"Gnani error {status}")


async def _call(method: str, path: str, **kw) -> httpx.Response:
    if not cfg.gnani_key:
        raise ApiError(503, "gnani_not_configured", "GNANI_API_KEY is not set on the server.")
    headers = kw.pop("headers", {})
    headers["X-API-Key-ID"] = cfg.gnani_key
    async with _semaphore():
        r = None
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=30, transport=_transport) as c:
                    r = await c.request(method, cfg.gnani_base + path, headers=headers, **kw)
            except httpx.HTTPError as e:
                if attempt == 3:
                    raise ApiError(503, "gnani_unavailable", f"Network error talking to Gnani: {type(e).__name__}")
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                await asyncio.sleep(0.6 * (attempt + 1))
                continue
            return r
    return r


async def stt(audio: bytes, filename: str | None, content_type: str | None, language_code: str,
              keyterms: list[str] | None = None, topic: str | None = None, mock_transcript: str | None = None) -> dict:
    t0 = time.time()
    if cfg.gnani_mock:
        txt = "" if mock_transcript == "__empty__" else (mock_transcript if mock_transcript is not None else "chai aur samosa")
        return {"transcript": txt, "language": "hi-IN",
                "provider": "mock", "latency_s": 0.0}
    data, fname, ctype = prepare_audio(audio, filename, content_type)
    form = {"language_code": validate_language_hint(language_code)}
    if cfg.stt_model == "prisma-v3.0":
        form["model"] = "prisma-v3.0"
        form["format"] = "codemix"
        if keyterms:
            import json
            form["keyterms"] = json.dumps(keyterms[:200], ensure_ascii=False)
        if topic:
            form["topic"] = topic[:1600]
    else:  # Prisma v2.5: one language only, ITN via format=transcribe
        form["language_code"] = form["language_code"].split(",")[0]
        form["format"] = "transcribe"
    r = await _call("POST", "/stt/v3", data=form, files={"audio_file": (fname, data, ctype)})
    if r.status_code != 200:
        raise _map_error(r.status_code, r.text)
    j = r.json()
    return {"transcript": (j.get("transcript") or "").strip(), "language": j.get("detected_language_code"),
            "provider": "gnani:" + (j.get("model") or cfg.stt_model), "latency_s": round(time.time() - t0, 2)}


def _silent_wav(ms: int = 300, rate: int = 16000) -> bytes:
    n = rate * ms // 1000
    return (b"RIFF" + struct.pack("<I", 36 + n * 2) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n * 2) + b"\x00\x00" * n)


async def tts(text: str, language: str = "auto") -> tuple[bytes, str]:
    if cfg.gnani_mock:
        return _silent_wav(), "audio/wav"
    payload = {"text": text, "voice": cfg.tts_voice, "model": cfg.tts_model, "language": language, "speed": 1.0,
               "audio_config": {"container": "mp3", "sample_rate": 24000, "bitrate": "64k"}}
    r = await _call("POST", "/api/v1/tts/inference", json=payload)
    if r.status_code != 200:
        raise _map_error(r.status_code, r.text)
    return r.content, "audio/mpeg"
