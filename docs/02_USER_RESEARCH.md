# 02 — User problems & competitors (what is known vs. what is assumed)

## Honest status of the evidence
`deep-research-report.md` lists strong-sounding statistics ("95% of apps English-only", "40% unreliable internet", "Reddit survey") **without verifiable citations**. Treat them as hypotheses. The design below is driven by the *mechanisms* behind each problem, and each row says how to validate it quickly. Do **not** quote those percentages in the submission unless you can link a source.

## Problem → design decision
| # | Problem (hypothesis) | Mechanism | Design response | Validate by |
|---|---|---|---|---|
| 1 | Trackers get abandoned: logging is a chore | effort > perceived reward | Auto-capture + 5-s voice answer; nothing to remember | Ask 5 people "last tracker you quit — why/when?" |
| 2 | Auto-import knows *who* not *why* | merchant ≠ intent (Zomato = lunch or gift) | Voice "what was it for" per payment | Show 5 people their own UPI history; ask what 3 random items were |
| 3 | Wrong auto-categories need fixing | generic merchant maps | Learn merchant→category from corrections; auto-apply after 3 confirmations | Count corrections in your own week of use |
| 4 | P2P UPI is opaque ("Ramesh ₹2,400") | rent? loan? split? | Person-payee chips + udhaar | Ask 5 people how many payments to people they can't recall |
| 5 | Cash spending invisible | no digital trace | Voice cash add, same pipeline | — |
| 6 | Same payment appears twice (bank SMS + app notification) | multi-source | dedupe key = UPI ref else amount+payee+10-min window | Fixture tests (already in parser/) |
| 7 | Notification fatigue → user mutes app | too many prompts | min amount, learned merchants silent, evening digest, max 5 prompts/day | Track mute rate in dogfooding |
| 8 | Distrust of apps reading SMS / bank logins | privacy fear | On-device parsing, no login, notification access limited to a whitelist, "delete all" button | Ask: "would you grant notification access? what would make you say no?" |
| 9 | Typing in regional languages is slow | keyboard friction | Speak in any of 10 languages incl. code-mix | Test 3 Telugu/Hindi speakers |
| 10 | Month-end report feels like a scolding | guilt framing | Neutral phrasing, one gentle insight, no red "overspent" | Show report to 3 people, watch reaction |
| 11 | Background capture is unreliable on Xiaomi/Oppo/Vivo etc. | aggressive battery killers | Onboarding step to exempt app from battery optimization; "Missed something? paste SMS" fallback | Test on at least one such phone if available |

## 20-minute validation plan (do tonight/tomorrow — 5 people is enough to be useful)
Ask each: (1) How do you track spending today? (2) Last time you tried an app, why did you stop? (3) Open your UPI app: pick 3 payments from last week — what was each *for*? Time how long recall takes. (4) Would you say it out loud in your language vs type? (5) Would you grant notification access? Write answers in `docs/validation_notes.md` and use 2–3 real quotes in the submission. **Real quotes from real people beat any statistic.**

## Competitors (from the report; verify listings before citing)
CashWise, VoiceSpend, Daily Voice Expense, Rolly: voice logging, but English-first and manual (user must open app and log). Money Manager, Monefy: text-only, offline. Indian aggregators (Walnut, ET Money etc. per report): auto-import but English/text, urban focus. **Gap HisaabBol targets:** auto-capture + *voice reason* + Indian languages + on-device privacy. State this as "we found no app combining these", not "no app exists".

## Platform risk to mention in the write-up
Google Play restricts SMS permissions; budget/money-management apps are a listed permitted use but require a permissions declaration and review. HisaabBol avoids that by default using notification access (not READ_SMS); for the hackathon an APK is sideloaded.
