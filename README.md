# HisaabBol — voice-first personal finance tracker
Payments log themselves; you *say* what each was for (Hindi / Telugu / English / mixed); month-end shows where the money really went.
Built for the Great Indian AI Internship Challenge with **Gnani Prisma (STT)** and **Timbre (TTS)**.

```
backend/       FastAPI + SQLite — all the logic (ingest, dedupe, voice → draft, learning, udhaar, budgets, reports, CSV, TTS)
  static/      the app UI (installable PWA: onboarding, voice capture, activity, report, udhaar, budgets, themes, 3 UI languages)
android-app/   Expo shell: same UI in a WebView + background notification listener that detects payments and asks you
parser/        on-device payment parser (JS) + fixtures      e2e/   browser end-to-end test + 30 screenshots      docs/   spec & guides
```

## Features
**Capture:** auto-detect from payment notifications (Android) · paste/forward SMS · speak in Hindi/Telugu/Tamil/Kannada/Malayalam/Bengali/Marathi/Gujarati/Punjabi/English or a mix · cash by voice · splits ("500 food, 200 gift") · smart prompts (small amounts and learned shops are never asked) · evening check-in · type instead · works offline (queued).
**Understand:** categories with learned shops you can review/edit · udhaar ledger with reminders and part-payments · budgets with 80%/100% alerts · monthly report (donut, trend vs last month, top places, daily bars, plain-language insights) · CSV + full JSON backup.
**Care:** Undo after every save · app lock (PIN, stored as a salted hash) · backup key to restore on a new phone · delete-all · light/dark, 6 colours, compact mode, English/हिन्दी/తెలుగు UI.

## Run the server + app (2 minutes)
```bash
cd backend && pip install -r requirements.txt
cp .env.example .env            # add GNANI_API_KEY (or GNANI_MOCK=true to try everything without a key)
set -a; source .env; set +a
uvicorn app.main:app --reload   # open http://localhost:8000  (API docs: /docs)
```
Phone: deploy the backend to any https host (Dockerfile + render.yaml included), open the URL in Chrome → "Add to Home screen". For **automatic** payment detection, build the Android app (`docs/11_ANDROID_APP.md`).

## Tests (all green when this zip was made)
| Suite | Command | Result |
|---|---|---|
| Backend (parser, flows, Gnani client w/ mocked HTTP, LLM fallback, auth, budgets, reports, undo, learned shops, backup…) | `cd backend && python -m pytest -q` | 51 passed |
| Browser end-to-end (real Chromium, fake microphone, live server in mock-speech mode) | `pip install playwright && python -m playwright install chromium && python e2e/run_e2e.py` | 36 checks passed, 0 console errors |
| On-device parser | `node parser/test.js` | 16 passed |
| Android app logic | `cd android-app && npm install && npm run typecheck && npm test` | tsc clean, 12 passed |

## What is and is not verified — read this before the demo
✅ The whole UI flow works in a real browser: onboarding → payment → **voice recording (browser mic → WAV → server)** → draft → save → activity/edit → report → udhaar → budgets → themes/Hindi → typed cash entry → **offline save + auto-sync** → delete-all.
⚠️ **Speech was mocked in those tests.** Real Gnani STT/TTS and Gemini were never called (no keys/network from my sandbox). Request formats follow docs.gnani.ai; run the two curls in `docs/06_GNANI_INTEGRATION.md` with your key first.
⚠️ **The Android app has not been compiled or run on a phone** (see `docs/11_ANDROID_APP.md` for the device checklist). The web app works without it; automatic detection needs it.
⚠️ Parser fixtures are representative bank formats, not your real SMS — add your own (docs/07).
⚠️ The Render hackathon Blueprint uses the free instance with ephemeral storage: it may sleep when idle, and SQLite data can be lost when the service restarts or redeploys. Use it for demos only, not as the sole copy of important financial data.
