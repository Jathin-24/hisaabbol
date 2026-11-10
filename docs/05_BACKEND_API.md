# 05 — Backend API reference

Base path `/api/v1`. Interactive docs: `/docs` (Swagger) when the server runs. Auth: `Authorization: Bearer <token>` from `POST /auth/register`. Money is **integer paise** everywhere. Errors: `{"error":{"code","message",...}}`.

## Core flow (what a client does)

```
1. POST /auth/register                       -> token (store on device)
2. payment SMS/notification arrives          -> POST /captures/ingest {raw_text | parsed}
      action = prompt        show notification (response.prompt), user taps
      action = auto_saved    small amount or learned merchant: already saved, no question
      action = recorded_income | duplicate | ignored | digest
3. user taps, speaks                         -> POST /captures/{id}/voice (audio <=30s)  [or /note with typed text]
      -> {transcript, draft:{items[], udhaar, confidence, follow_up_question}}   (nothing saved yet)
4. user confirms/edits                       -> POST /captures/{id}/confirm {items[]}  (+ Idempotency-Key header)
      -> {transaction, alerts[] (budget), udhaar_updates[], speech_text}
5. optional                                  -> POST /tts {transaction_id} -> audio
6. cash: POST /cash/voice -> draft -> POST /transactions
7. month end: GET /reports/monthly?month=YYYY-MM
```

**Fallback contract:** any 5xx/503 from `/voice` or `/cash/voice` (codes `gnani_*`) means *offer typing* (`/note`). `Retry-After` is set on 429 / `gnani_busy`. Use `Idempotency-Key` on confirm/create so offline retries never double-save.

**Privacy contract:** `raw_text` is parsed in memory and discarded. For maximum privacy parse on the phone with `parser/paymentParser.js` and send `parsed` instead (its camelCase output is accepted as-is).

## Endpoints

| Group | Method | Path | What |
|---|---|---|---|
| account | GET | `/diagnostics` | Diagnostics |
| account | DELETE | `/me` | Delete Me |
| account | GET | `/me` | Me |
| account | DELETE | `/me/data` | Delete My Data |
| account | GET | `/settings` | Get Settings |
| account | PUT | `/settings` | Put Settings |
| auth | POST | `/auth/register` | Register |
| budgets | DELETE | `/budgets` | Budget Del |
| budgets | GET | `/budgets` | Budgets |
| budgets | PUT | `/budgets` | Budget Put |
| captures | GET | `/captures` | List Captures |
| captures | GET | `/captures/digest` | Digest |
| captures | POST | `/captures/ingest` | Ingest |
| captures | GET | `/captures/{cid}` | Get Capture |
| captures | POST | `/captures/{cid}/confirm` | Capture Confirm |
| captures | POST | `/captures/{cid}/skip` | Skip |
| demo | GET | `/demo/presets` | Presets |
| demo | POST | `/demo/seed-month` | Seed |
| demo | POST | `/demo/simulate` | Simulate |
| learning | DELETE | `/merchants` | Merchant Del |
| learning | GET | `/merchants` | Merchants |
| learning | PUT | `/merchants` | Merchant Put |
| meta | GET | `/categories` | Categories |
| meta | GET | `/health` | Health |
| reports | GET | `/export/csv` | Export |
| reports | GET | `/export/json` | Export Json |
| reports | GET | `/reports/monthly` | Monthly |
| reports | GET | `/reports/months` | Months |
| transactions | GET | `/review` | Review Queue |
| transactions | GET | `/transactions` | List Tx |
| transactions | POST | `/transactions` | Create Tx |
| transactions | DELETE | `/transactions/{tid}` | Del Tx |
| transactions | GET | `/transactions/{tid}` | Get Tx |
| transactions | PATCH | `/transactions/{tid}` | Patch Tx |
| udhaar | GET | `/udhaar` | Udhaar |
| udhaar | POST | `/udhaar` | Udhaar Add |
| udhaar | GET | `/udhaar/reminders` | Udhaar Reminders |
| udhaar | DELETE | `/udhaar/{uid_}` | Udhaar Delete |
| udhaar | POST | `/udhaar/{uid_}/settle` | Udhaar Settle |
| voice | POST | `/captures/{cid}/note` | Capture Note |
| voice | POST | `/captures/{cid}/voice` | Capture Voice |
| voice | POST | `/cash/note` | Cash Note |
| voice | POST | `/cash/voice` | Cash Voice |
| voice | POST | `/tts` | Tts |

## Draft object
```json
{"transcript":"biryani for team lunch","language":"hi-IN","amount_paise":45000,
 "items":[{"label":"Biryani Team Lunch","amount_paise":45000,"category":"Food & Dining","note":null}],
 "udhaar":null,"confidence":0.65,"follow_up_question":null,"needs_review":false,"provider":"rules|gemini|rules(fallback:...)"}
```
Items always sum to the payment amount (repaired server-side if the LLM gets it wrong; repaired drafts are flagged `needs_review`).

## Categories
`Food & Dining, Groceries, Transport, Fuel, Bills & Recharge, Shopping, Health, Entertainment, Education, Rent & Home, Personal Care, Travel, Gifts & Donations, Family & Friends, Other` + special: `Lent (udhaar), Repaid, Income` (excluded from 'spent'; udhaar/repayments tracked in the ledger).

## Behaviours worth knowing
- **Prompt policy:** under `min_prompt_paise` (default ₹50) or merchant learned (3 consistent confirmations) → auto-saved, no prompt. After `max_prompts_per_day` (default 5) → `digest`, listed by `GET /captures/digest`.
- **Dedupe:** same UPI ref, or same direction+amount within 10 min across SMS + app notification → merged (missing payee/ref/account filled in).
- **Udhaar:** 'Ramesh ko 500 udhaar diya' → ledger entry (i_lent). 'Ramesh ne 300 wapas kiye' → FIFO settlement. Reminders: overdue, due tomorrow, open 30+ days.
- **Budgets:** per category or overall; alert once at 80% and once at 100% per month, returned in the confirm response.
- **Reports:** computed in your timezone (`settings.tz`); insights phrased by Gemini if configured, else deterministic facts; cached until data changes.
- **Diagnostics:** `GET /diagnostics` shows Gnani call counts/latency so you can see how fast the 5,000 credits are used.
