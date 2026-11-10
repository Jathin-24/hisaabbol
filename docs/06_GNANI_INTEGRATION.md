# 06 — Gnani integration (verified against docs.gnani.ai on 8 Nov 2026)

Base URL `https://api.vachana.ai`. Auth header on every call: `X-API-Key-ID: <key>`. Key lives ONLY in the backend.
Docs index for the builder: https://docs.gnani.ai/llms.txt (fetch pages as `.md`).

## STT — Prisma (REST) `POST /stt/v3`  (multipart/form-data)
| field | value we use | notes |
|---|---|---|
| `audio_file` | m4a/wav/mp3/ogg/flac/aac | **max 30 s**. We cap recording at 12 s. |
| `model` | `prisma-v3.0` | omit => Prisma v2.5 (single language only, no `codemix`) |
| `language_code` | `hi-IN,en-IN` (1–4 codes) or `indic-auto` | v3.0 only; hints not locks. Set from user's language setting, e.g. `te-IN,en-IN` |
| `format` | `codemix` | keeps English words (Zomato, petrol) in Latin script. `transcribe` = ITN (digits/₹). Amount comes from the SMS, so we do not depend on spoken numbers. |
| `keyterms` | JSON array, ≤200 | pass the user's top merchants + category words ("udhaar","Zomato","kirana") |
| `topic` | "Short voice note about what a UPI payment was for" | ≤1600 chars; test with/without — docs warn context can lower accuracy |
Response: `{success, transcript, detected_language_code, processing_time, ...}`. **Empty transcript is not an error** → ask user to retry or type.
Errors: 400 `MAX_AUDIO_DURATION_EXCEEDED|EMPTY_AUDIO|...`, 401 bad key, 402 no credit, 429 `RATE_LIMITED` (accounts may allow only ONE active request → backend serializes + retries), 504 `UPSTREAM_TIMEOUT` (v3.0).
Languages: bn-IN en-IN gu-IN hi-IN kn-IN ml-IN mr-IN pa-IN ta-IN te-IN.

## TTS — Timbre (REST) `POST /api/v1/tts/inference`  (JSON → binary audio)
```json
{"text":"₹250 Zomato, khana. Save kar diya.","voice":"Shivani","model":"timbre-v3.0","language":"auto",
 "speed":1.0,"audio_config":{"container":"mp3","sample_rate":24000,"bitrate":"64k"}}
```
- `timbre-v3.0` voices (each speaks all 10 languages): Avinash, Shivani, Lakshmi, Kalpana, Shubham, Prakash, Devansh, Yashraj, Chetana, Vasudha, Riyaa, Tarika, Harshad.
- `language`: `auto`, `hi-IN`, `en-IN`, `hi-en` (Hinglish), `te-IN`, `ta-IN`, ...
- **Say numbers as words** or follow https://docs.gnani.ai/api/TTS/tts-input-formating.md — raw digit strings mispronounce. For amounts: "do sau pachaas rupaye" / "two hundred fifty rupees"; build a small `speakAmount(paise, lang)` helper.
- Keep replies ≤ 12 words; cache identical phrases (backend does); TTS is a *toggle*, off if credits are low.

## Credits (5,000 programme credits)
Unknown unit/pricing → **VERIFY on day 1**: make one STT call and one TTS call, check the dashboard balance delta, then compute calls available. Design rule: STT is the core (every capture); TTS is optional sugar; the demo must work with TTS off.

## Evon (30B, open weights on Hugging Face)
Needs a large GPU to self-host — not realistic in 48 h, and I did not verify any hosted Evon endpoint. Default plan: **LLM_PROVIDER=gemini** (free tier) with `rules` fallback. If the Gnani Discord confirms a hosted Evon endpoint, add it as a third provider in `backend/app/llm.py::understand` behind the same JSON contract. Gnani-technology requirement is satisfied by Prisma + Timbre; say so plainly in the submission.

## Smoke test (do this FIRST, before any app code)
```bash
curl -X POST https://api.vachana.ai/stt/v3 -H "X-API-Key-ID: $GNANI_API_KEY" \
  -F audio_file=@sample.m4a -F model=prisma-v3.0 -F language_code=hi-IN,en-IN -F format=codemix
curl -X POST https://api.vachana.ai/api/v1/tts/inference -H "Content-Type: application/json" -H "X-API-Key-ID: $GNANI_API_KEY" \
  -d '{"text":"namaste","voice":"Shivani","model":"timbre-v3.0","language":"auto","audio_config":{"container":"mp3"}}' --output t.mp3
```
