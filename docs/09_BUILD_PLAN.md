# 09 — Plan to the 10 Nov deadline (confirm the exact cut-off time on the programme page)
The backend is built and tested. What remains is using it for real and submitting.

| When | Do | Gate |
|---|---|---|
| Today | Get Gnani key; run the 2 curls in 06; run backend locally with the real key; open `/`; record a Hindi/Telugu clip (laptop `localhost`, or deploy first for phone/https) | real transcript appears; note credit balance before/after |
| Today | Deploy (Render/Fly/Railway; Dockerfile included). Set `GNANI_API_KEY`, `REGISTRATION_KEY`; optionally `LLM_PROVIDER=gemini` + key + model | `/api/v1/health` shows `gnani_configured:true` |
| Today/Mon | Add 15–20 of **your own** real payment SMS/notifications to both `fixtures.json` files; fix the parser until green | both test suites green |
| Mon | Use it yourself for a day (paste real SMS into the box); interview 5 people (see 02) | real quotes + numbers for the write-up |
| **Mon evening** | Record the 60-s demo (see 10) and **publish the LinkedIn/X posts** — engagement only counts up to the cutoff | posts public, both hashtags, Gnani tagged |
| Tue morning | Submit everything (checklist in 10); re-check each field | submitted with buffer |
| Mon night (only if time) | Build the APK (`docs/11_ANDROID_APP.md`) and run the device checklist | a real payment notification creates a prompt |
