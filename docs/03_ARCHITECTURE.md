# 03 — Architecture (backend-centric)

```
 Client (any)                         FastAPI backend (this repo)                         External
┌───────────────────────────┐      ┌──────────────────────────────────────────┐
│ Web UI (included, minimal)│      │ api.py  routes, validation, error shape  │
│ or Android app (optional) │─────►│ auth.py bearer tokens + rate limits      │
│  - sends SMS/notification │ JSON │ core.py ingest · dedupe · prompt policy  │      ┌─ Gnani Prisma STT  /stt/v3
│    text or pre-parsed     │ +    │         drafts · transactions · learning │─────►├─ Gnani Timbre TTS  /api/v1/tts/inference
│  - records ≤12 s audio    │ audio│         udhaar · budgets · reports · CSV │      └─ Gemini (optional) structured understanding
│  - shows prompts/report   │◄─────│ gnani.py semaphore, 429 retry, error map │
└───────────────────────────┘      │ llm.py   gemini | rules fallback         │
                                   │ parser.py / rules.py / textutil.py       │
                                   │ db.py    SQLite (WAL), paise integers    │
                                   └──────────────────────────────────────────┘
```
**Decisions**
- **Backend does all the logic**; clients are thin: forward payment notifications, record audio, render JSON.
- **SQLite** is enough for a hackathon and a modest user base on one box. It lives at `DB_PATH`; mount a persistent disk in production or data resets on redeploy. Moving to Postgres = swap `db.py` and the `?` placeholders.
- **Never block the user:** STT fail → typed note; LLM fail → rules; duplicate request → idempotency key; Gnani busy → serialized + retried.
- **Privacy:** raw SMS is parsed in memory and dropped (not stored; error handler and access log never record bodies). Clients may parse on-device and send only structured fields. `DELETE /me/data` wipes everything; `DELETE /me` removes the account.
- **Credits:** only `/voice`, `/cash/voice` and `/tts` call Gnani; they have a stricter rate bucket and are counted in `/diagnostics`.
- **Auth:** per-device random token (hash stored). Set `REGISTRATION_KEY` in production so only your client can create accounts.
- **Known limits:** in-memory rate limiter and Gnani semaphore (correct for one instance only); synchronous SQLite calls inside async routes (fast, but not for heavy concurrent load).

## Layout
```
backend/app/{main,api,core,auth,db,gnani,llm,parser,rules,textutil,config,errors}.py
backend/static/index.html   minimal web UI (record → WAV → upload; report; udhaar; settings)
backend/tests/              46 tests
parser/                     on-device JS parser + fixtures for a mobile client (same behaviour as app/parser.py)
```
