# 08 — Screens (mobile, one-handed, large touch targets ≥48 dp, high contrast, works at 360×640)

> **Status note:** the backend now implements the server-side logic described here (see `05_BACKEND_API.md`). Anything below about on-device SQLite or a stateless proxy is superseded by `03_ARCHITECTURE.md`; the screen/flow descriptions still apply to any client.

Design language: calm, warm, not "banking-blue". Light + dark. One accent color. Rounded cards. Big numbers. Indian digit grouping everywhere.

1. **Onboarding (3 steps):** Language picker (Hindi+English, Telugu+English, Tamil+English, English…) → how it works (3 icons: pay → say → see) → permissions (mic; notification access in Tier B; battery exemption). Skippable; "Try demo payment" button.
2. **Home:** header "October · ₹18,420 spent"; banner "3 payments need a note" (tap → Pending); last 10 entries (label, category chip, ₹); floating mic FAB (cash add).
3. **Pending ("Needs a note"):** cards of detected payments (payee, amount, time). Swipe left = skip, tap = Capture. "Answer all" digest mode steps through them one by one.
4. **Capture:** top: ₹ amount + payee + time. Center: giant mic button (tap to start, tap to stop, 12 s cap with ring progress). Under: live "listening…" states (recording → uploading → understanding). Fallbacks: "Type instead" and "Skip". Warm-up state if backend is waking.
5. **Confirm:** transcript (editable), item rows (label, amount, category chip ▾ opens sheet of categories with search), "+ Split", "Save". Shows "I'll remember Zomato → Food & Dining" toggle.
6. **Review queue:** low-confidence items, 1-tap fix.
7. **Report (tab):** month picker; hero total + vs last month (neutral phrasing); donut by category (tap slice → list); daily bar chart; top 5 merchants; "3 things I noticed" insights; share-as-image button (PNG of the summary; no raw merchants if user toggles "hide names").
8. **Udhaar (Tier C):** two lists — "You will get" / "You have to give"; add by voice; settle button; reminder.
9. **Settings:** language, min prompt amount, digest time, TTS toggle, app lock, **Demo tools** (simulate payment, paste SMS, generate month of sample data), export CSV, **Delete all my data**, Diagnostics.

States every screen must handle: empty, loading, offline, error with retry. Accessibility: labels on all buttons, no color-only meaning, font scaling.

## Demo data
"Generate sample month" creates ~60 realistic entries (Hyderabad-agnostic: chai, auto, kirana, Zomato, recharge, rent, udhaar) so the Report looks real in the video. Mark clearly as demo; separate flag `is_demo` is NOT needed — keep it simple: Delete-all wipes it.
