import json
import httpx
import pytest
from app import gnani, llm, core
from app.errors import ApiError

H = "/api/v1"


def mock_transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "k")


@pytest.mark.asyncio
async def test_stt_request_shape_and_parse(keyed):
    seen = {}

    def h(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-api-key-id"), req.content
        return httpx.Response(200, json={"success": True, "transcript": "chai aur samosa", "detected_language_code": "hi-IN", "model": "prisma-v3.0"})
    gnani._transport = mock_transport(h)
    r = await gnani.stt(b"RIFF", "x.wav", "audio/wav", "hi-IN,en-IN", keyterms=["Zomato"])
    assert r["transcript"] == "chai aur samosa" and seen["key"] == "k" and seen["url"].endswith("/stt/v3")
    assert b'name="model"' in seen["body"] and b"prisma-v3.0" in seen["body"] and b"codemix" in seen["body"] and b"Zomato" in seen["body"]


@pytest.mark.asyncio
async def test_stt_retries_429_then_succeeds(keyed, monkeypatch):
    calls = {"n": 0}

    async def nosleep(_): pass
    monkeypatch.setattr(gnani.asyncio, "sleep", nosleep)

    def h(req):
        calls["n"] += 1
        return httpx.Response(429, json={}) if calls["n"] < 3 else httpx.Response(200, json={"transcript": "ok"})
    gnani._transport = mock_transport(h)
    assert (await gnani.stt(b"RIFF", "x.wav", "audio/wav", "hi-IN"))["transcript"] == "ok" and calls["n"] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status,body,code", [(402, "", "gnani_credits_exhausted"), (401, "", "gnani_auth"),
                                              (400, "MAX_AUDIO_DURATION_EXCEEDED", "audio_too_long"), (400, "EMPTY_AUDIO", "empty_audio")])
async def test_stt_error_mapping(keyed, status, body, code):
    gnani._transport = mock_transport(lambda r: httpx.Response(status, text=body))
    with pytest.raises(ApiError) as e:
        await gnani.stt(b"RIFF", "x.wav", "audio/wav", "hi-IN")
    assert e.value.code == code


def test_language_hint_validation():
    assert gnani.validate_language_hint("hi-IN, en-IN") == "hi-IN,en-IN"
    assert gnani.validate_language_hint("indic-auto") == "indic-auto"
    for bad in ("", "xx-XX", "hi-IN,en-IN,ta-IN,te-IN,kn-IN"):
        with pytest.raises(ApiError):
            gnani.validate_language_hint(bad)


def test_audio_format_mapping_and_rejection(monkeypatch):
    assert gnani.prepare_audio(b"x", "blob", "audio/mp4")[1] == "clip.m4a"
    monkeypatch.setattr(gnani.shutil, "which", lambda _: None)
    with pytest.raises(ApiError) as e:
        gnani.prepare_audio(b"x", "blob.webm", "audio/webm;codecs=opus")
    assert e.value.code == "unsupported_audio"


@pytest.mark.asyncio
async def test_tts_payload(keyed):
    seen = {}

    def h(req):
        seen.update(json.loads(req.content)); return httpx.Response(200, content=b"ID3audio")
    gnani._transport = mock_transport(h)
    audio, ct = await gnani.tts("Saved.", "hi-en")
    assert audio == b"ID3audio" and ct == "audio/mpeg" and seen["model"] == "timbre-v3.0" and seen["language"] == "hi-en" and seen["audio_config"]["container"] == "mp3"


def test_tts_route_mock_and_disabled(client, user, mock_gnani):
    r = client.post(f"{H}/tts", json={"text": "hello"}, headers=user)
    assert r.status_code == 200 and r.content[:4] == b"RIFF"
    client.put(f"{H}/settings", json={"tts_enabled": False}, headers=user)
    assert client.post(f"{H}/tts", json={"text": "hello"}, headers=user).status_code == 409


def test_diagnostics_counts_gnani_calls(client, user, mock_gnani):
    client.post(f"{H}/tts", json={"text": "hello"}, headers=user)
    d = client.get(f"{H}/diagnostics", headers=user).json()
    assert d["gnani_usage"]["tts"]["calls_total"] == 1 and d["recent_api_calls"]


@pytest.mark.asyncio
async def test_gemini_understand_and_repair(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini"); monkeypatch.setenv("GEMINI_API_KEY", "g"); monkeypatch.setenv("GEMINI_MODEL", "m")
    out = {"items": [{"label": "Team lunch", "amount_rupees": 300, "category": "Food & Dining"}, {"label": "Gift", "amount_rupees": 100, "category": "Made Up"}],
           "confidence": 0.9}
    llm._transport = mock_transport(lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(out)}]}}]}))
    res = await llm.understand("x", 45000, "Zomato", False, "debit", {}, "hi-IN")
    assert res["provider"] == "gemini" and res["items"][1]["category"] == "Other"
    d = core.normalize_draft(res, 45000, "Zomato", {}, "debit", "x", None)   # 300+100 < 450 -> remainder item added, flagged for review
    assert sum(i["amount_paise"] for i in d["items"]) == 45000 and d["needs_review"] and d["items"][-1]["label"] == "Remaining"


@pytest.mark.asyncio
async def test_gemini_failure_falls_back_to_rules(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini"); monkeypatch.setenv("GEMINI_API_KEY", "g"); monkeypatch.setenv("GEMINI_MODEL", "m")
    llm._transport = mock_transport(lambda r: httpx.Response(500))
    res = await llm.understand("biryani lunch", 45000, "Zomato", False, "debit", {}, "hi-IN")
    assert res["provider"].startswith("rules(fallback") and res["items"][0]["category"] == "Food & Dining"
    ins, prov = await llm.phrase_insights(["a", "b", "c", "d"], {}, "en")
    assert ins == ["a", "b", "c"] and prov == "rules(fallback)"


def test_draft_over_sum_collapses_to_single_item():
    res = {"items": [{"label": "a", "amount_paise": 40000, "category": "Food & Dining"}, {"label": "b", "amount_paise": 40000, "category": "Other"}], "confidence": 0.9}
    d = core.normalize_draft(res, 45000, None, {}, "debit", "t", None)
    assert len(d["items"]) == 1 and d["items"][0]["amount_paise"] == 45000 and d["needs_review"]
