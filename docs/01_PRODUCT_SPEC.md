# 01 — Product spec: HisaabBol ("bol ke hisaab")

> **Status note:** the backend now implements the server-side logic described here (see `05_BACKEND_API.md`). Anything below about on-device SQLite or a stateless proxy is superseded by `03_ARCHITECTURE.md`; the screen/flow descriptions still apply to any client.


**One line:** Your payments log themselves; you just *say* what each one was for — in your own language — and at month-end you see where the money actually went.

## The user (design for this person)
Primary: 18–30, Android, pays mostly via UPI, 30–80 payments/month, mixes English with Hindi/Telugu/Tamil etc. when speaking. Knows they "spend too much" but can't say on what. Has tried a tracker and quit within 2 weeks because logging was a chore.
Secondary (stretch): small shopkeeper/gig worker with cash + udhaar.

## The core insight (what makes this different from existing apps)
Auto-import apps know the **merchant** but not the **why** ("₹450 Zomato" could be lunch, a team treat, or a gift). Manual/voice apps know the why but rely on you to remember to log. **HisaabBol captures the payment automatically and asks one 5-second voice question right when memory is fresh.** Zero typing, no category menus.

## Principles
1. **Ask less, not more.** Never prompt for payments under ₹50 (setting), or for merchants it already learned (auto-apply after 3 consistent confirmations). Batch low-priority asks into one evening digest.
2. **One tap → talk → done.** Tapping the notification opens straight on a big mic. No menus before talking.
3. **Forgive everything.** Wrong category → one tap to fix, and the app learns it. Skip is always allowed. Nothing is lost if STT/LLM/network fails.
4. **Private by default.** On-device storage, on-device SMS/notification parsing, no account, no bank login.
5. **Neutral tone.** Report says "where it went", never "you overspent / bad". No guilt.

## MVP features (in priority order → see 09_BUILD_PLAN)
**Tier A — must ship (works in Expo Go)**
- A1 Simulate/paste payment → parser → pending capture (Settings → Demo tools).
- A2 Pending list ("Needs a note") and Capture screen: big mic, 12 s max, waveform, "type instead".
- A3 Voice → `/api/stt` → `/api/understand` → Confirm card (items, categories, editable) → save. Splits supported ("500 food, 200 gift").
- A4 Manual voice add for **cash** ("chai bees rupaye") — same pipeline with no payment attached.
- A5 Home: this month spent, last 10 entries, "N payments need a note" banner.
- A6 Monthly report: total, vs last month, category donut, top 5 merchants, daily bar chart, 3 insights (`/api/insights`), tap a category → its entries.
- A7 Merchant learning (merchant_rules) + review queue for low-confidence items.
- A8 Offline: clip queued in `voice_queue`, auto-retry when online.
- A9 Settings: language (Hindi/English, Telugu/English, Tamil/English...), min prompt amount, TTS on/off, CSV export, delete all data.

**Tier B — real auto-detect (needs a dev build)**
- B1 Android `NotificationListenerService` bridge → feeds `parsePayment()` → creates capture + local notification. Works for UPI-app notifications (GPay, PhonePe, Paytm, BHIM) and bank-SMS notifications from the messaging app. Onboarding explains the permission in plain words and what is NOT read (only notifications from a whitelist of finance/SMS apps).
- B2 Battery-optimization onboarding (OEMs kill background services; see 07).
- B3 Dedupe across sources.

**Tier C — only if time remains**
- C1 Udhaar ledger (voice: "Ramesh ko 500 udhaar diya") + reminder notification.
- C2 Budgets with 80% alert. C3 TTS confirmations (Timbre). C4 Weekly digest notification.

**Explicitly OUT for the 48 h build:** iOS, bank/Account Aggregator integration, cloud sync/accounts, family sharing, receipt OCR, hosting Evon.

## Key flows (exact copy so the builder doesn't improvise)
**Flow 1 — Detected payment.** Notification: title "₹450 paid to Zomato", body "What was it for? Tap and say it." → opens Capture(captureId). Header shows amount + payee. Mic auto-arms after a 600 ms delay (user taps to start; auto-start is OFF by default — never record without a tap). Prompt text per language setting:
- hi: "बोलिए — ये किसलिए था?"  te: "చెప్పండి — ఇది దేనికి?"  en: "Say what this was for"
After STT: show transcript (editable), then Confirm card: `[label] ₹amount · [Category chip ▾]` per item, buttons **Save** / **Edit** / **Skip**. If `follow_up_question` present, show it above the card with a second mic button.
**Flow 2 — Person payee** (`counterpartyIsPerson=true`): prompt "Who is this for / what for?" Offer quick chips: *Rent · Split bill · Lent (udhaar) · Family · Repaying*. Voice still works.
**Flow 3 — Credit received:** do not ask by default; show in a "Money in" list; optional note.
**Flow 4 — Cash:** Home mic FAB → "Say what you spent" → pipeline with `transaction={amount:null}`; amount must come from speech: if `items[].amount` null → ask "How much?" with numeric keypad.
**Flow 5 — Monthly report** opens on the 1st via notification "Your October report is ready", and is always reachable from the Report tab. Month picker.
**Edge cases:** empty transcript → "Couldn't hear that — try again or type"; duplicate payment → silently merged; ₹ amounts ≥ 1 lakh format Indian grouping (₹1,25,000); user sets split amounts that don't sum → block Save, show remaining; STT language mismatch (user speaks Telugu with Hindi setting) → use `indic-auto` on retry.

## Success metrics (for the demo & write-up)
Capture→note completion rate; median seconds from tap to saved (target < 10 s); % of payments auto-categorized after week 1; STT+parse accuracy on a 20-clip test set (Hindi/Telugu/English/mix, quiet + noisy) — record the real number, don't invent it.
