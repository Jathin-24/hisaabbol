# 07 — Payment detection (Tier B) and the parser

> **Status note:** the backend now implements the server-side logic described here (see `05_BACKEND_API.md`). Anything below about on-device SQLite or a stateless proxy is superseded by `03_ARCHITECTURE.md`; the screen/flow descriptions still apply to any client.


## What is built
`parser/paymentParser.js` (client) and `backend/app/parser.py` (server) — `parsePayment(text,{source,receivedAt})` → normalized txn or `null`; `isDuplicate(a,b)`; 16 fixtures pass (`node parser/test.js`): HDFC, SBI, ICICI, Axis, Kotak-style UPI debits, card spend, GPay/PhonePe notifications, UPI credit, person payee; and **negatives**: OTP, cashback promo, credit-limit/statement, failed txn, collect request.
**Caveat:** fixtures are representative samples written from known formats, not scraped real SMS. Banks change templates. Day-1 task: collect 15–20 of the user's *own* real payment messages/notifications (mask account numbers), add to `fixtures.json`, fix the parser until green. Never loosen a negative test.

## Pipeline
`NotificationListener(pkg,title,text,time)` → if pkg ∉ whitelist drop → `text = title + " | " + body` → `parsePayment` → null? drop silently (never log content) → `direction=credit`? store capture status `auto_categorized`, no prompt → `debit`: dedupe against captures within 10 min (`isDuplicate`) → insert capture (`dedupe_key UNIQUE` ignores repeats) → if `amount < min_prompt` or merchant rule `auto_apply` → create transaction directly, no prompt → else schedule local notification "₹450 paid to Zomato — What was it for?" (max 5 prompts/day, rest go to the evening digest).

## Why notification access instead of READ_SMS
Bank SMS shows up as a notification in the messaging app, UPI apps post their own; one permission covers both. It avoids READ_SMS, which Google Play restricts (money-management is a permitted use, but needs a declaration and review). Trade-off: only notifications posted *after* the user enables access are seen; if a notification is dismissed instantly by another app, it can be missed → provide "Paste an SMS" fallback and (optional, Tier C) a one-time import of the last 30 days via READ_SMS for sideloaded builds only.

## Reliability checklist (this is where real apps fail)
- Onboarding screen 1: why access is needed, exactly which apps are read, "nothing leaves your phone". Screen 2: deep-link to Notification access settings. Screen 3: battery optimization exemption + OEM-specific hint (Xiaomi "Autostart", Oppo/Vivo "Allow background activity").
- Rebind: call `requestRebind` / re-enable listener on app start; show a banner if the listener is disconnected.
- Test matrix: GPay pay, PhonePe pay, bank SMS debit, app killed from recents, phone locked, airplane mode, duplicate (SMS+app), OTP present, credit received.
- Unknown notification that *looks* financial → dev-mode log of package name only (not content).
