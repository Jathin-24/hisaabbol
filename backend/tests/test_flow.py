import io
from datetime import timedelta
from tests.conftest import make_user

H = "/api/v1"
ZOMATO = "Sent Rs.450.00 From HDFC Bank A/C *1234 To ZOMATO On 08/11/26 Ref 123456789012 Not You? Call 18002586161"
GPAY = "Google Pay | Paid ₹450 to Zomato"


def ingest(c, h, text, **kw):
    return c.post(f"{H}/captures/ingest", json={"raw_text": text, **kw}, headers=h).json()


def test_auth_required_and_isolation(client):
    assert client.get(f"{H}/settings").status_code == 401
    assert client.get(f"{H}/settings", headers={"Authorization": "Bearer nope"}).status_code == 401
    a, b = make_user(client, "a"), make_user(client, "b")
    ingest(client, a, ZOMATO)
    assert len(client.get(f"{H}/captures", headers=a).json()["items"]) == 1
    assert client.get(f"{H}/captures", headers=b).json()["items"] == []
    cid = client.get(f"{H}/captures", headers=a).json()["items"][0]["id"]
    assert client.post(f"{H}/captures/{cid}/skip", headers=b).status_code == 404


def test_timezone_fallback_when_timezone_data_is_unavailable(monkeypatch):
    from app import core

    def missing_timezone(_):
        raise RuntimeError("timezone data unavailable")

    monkeypatch.setattr(core, "ZoneInfo", missing_timezone)
    assert core.tz_of({"tz": "Asia/Kolkata"}).utcoffset(None) == timedelta(hours=5, minutes=30)


def test_registration_key(client, monkeypatch):
    monkeypatch.setenv("REGISTRATION_KEY", "k")
    assert client.post(f"{H}/auth/register", json={}).status_code == 403
    assert client.post(f"{H}/auth/register", json={}, headers={"X-Registration-Key": "k"}).status_code == 200


def test_ingest_prompt_dedupe_ignore(client, user):
    r = ingest(client, user, ZOMATO)
    assert r["action"] == "prompt" and r["capture"]["amount_paise"] == 45000 and "450" in r["prompt"]["title"]
    assert ingest(client, user, GPAY, received_at=r["capture"]["occurred_at"])["action"] == "duplicate"  # same payment, second source
    assert ingest(client, user, ZOMATO)["action"] == "duplicate"
    assert ingest(client, user, "123456 is your OTP for Rs 250.00. Do not share")["action"] == "ignored"
    assert len(client.get(f"{H}/captures", headers=user).json()["items"]) == 1


def test_ingest_parsed_from_js_parser_shape(client, user):
    body = {"parsed": {"direction": "debit", "amount": 300, "counterparty": "Swiggy", "counterpartyIsPerson": False,
                       "upiRef": "999999999999", "instrument": "upi", "occurredAt": "2026-11-08T10:00:00Z"}, "source": "notification"}
    r = client.post(f"{H}/captures/ingest", json=body, headers=user).json()
    assert r["action"] == "prompt" and r["capture"]["upi_ref"] == "999999999999"


def test_person_payee_gets_chips(client, user):
    r = ingest(client, user, "Sent Rs.2400.00 From HDFC Bank A/C *1234 To RAMESH KUMAR On 08/11/26 Ref 123456789013")
    assert r["capture"]["counterparty_is_person"] is True and "quick_chips" in r["prompt"]


def test_credit_auto_recorded_as_income(client, user):
    r = ingest(client, user, "Rs 5000.00 credited to a/c XX1234 on 08-11-26 by a/c linked to mobile 98XXXXX210 (UPI Ref No 123456789099)")
    assert r["action"] == "recorded_income" and r["transaction"]["items"][0]["category"] == "Income"


def test_small_payment_auto_saved_no_prompt(client, user):
    r = ingest(client, user, "Google Pay | Paid ₹20 to Ramu Tea Stall")
    assert r["action"] == "auto_saved" and r["transaction"]["items"][0]["category"] == "Food & Dining"


def test_prompt_cap_goes_to_digest(client, user):
    client.put(f"{H}/settings", json={"max_prompts_per_day": 2}, headers=user)
    acts = [ingest(client, user, f"Sent Rs.{500 + i}.00 From HDFC Bank A/C *1234 To SHOP{chr(65 + i)}MART On 08/11/26 Ref 1000000000{i:02d}")["action"] for i in range(4)]
    assert acts == ["prompt", "prompt", "digest", "digest"]
    d = client.get(f"{H}/captures/digest", headers=user).json()
    assert d["count"] == 4 and d["captures"][0]["amount_paise"] >= d["captures"][-1]["amount_paise"]


def test_voice_loop_end_to_end(client, user, mock_gnani):
    cap = ingest(client, user, ZOMATO)["capture"]
    v = client.post(f"{H}/captures/{cap['id']}/voice", files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")},
                    data={"mock_transcript": "biryani for team lunch"}, headers=user).json()
    assert v["transcript"] == "biryani for team lunch" and v["stt_provider"] == "mock"
    d = v["draft"]
    assert d["items"][0]["category"] == "Food & Dining" and d["items"][0]["amount_paise"] == 45000
    c = client.post(f"{H}/captures/{cap['id']}/confirm", json={"items": d["items"], "transcript": v["transcript"]}, headers=user).json()
    assert c["transaction"]["amount_paise"] == 45000 and "four hundred fifty rupees" in c["speech_text"]
    assert client.get(f"{H}/captures", headers=user).json()["items"] == []
    again = client.post(f"{H}/captures/{cap['id']}/confirm", json={"items": d["items"]}, headers=user)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_answered"


def test_voice_empty_transcript_and_typed_fallback(client, user, mock_gnani):
    cap = ingest(client, user, ZOMATO)["capture"]
    v = client.post(f"{H}/captures/{cap['id']}/voice", files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")}, data={"mock_transcript": "__empty__"}, headers=user).json()
    assert v["empty"] is True and v["draft"] is None
    n = client.post(f"{H}/captures/{cap['id']}/note", json={"text": "lunch with team"}, headers=user).json()
    assert n["draft"]["items"][0]["category"] == "Food & Dining"


def test_stt_failure_codes(client, user, monkeypatch):
    cap = ingest(client, user, ZOMATO)["capture"]
    files = {"audio": ("a.wav", b"RIFFxxxx", "audio/wav")}
    r = client.post(f"{H}/captures/{cap['id']}/voice", files=files, headers=user)
    assert r.status_code == 503 and r.json()["error"]["code"] == "gnani_not_configured"  # client should fall back to /note
    assert client.post(f"{H}/captures/{cap['id']}/voice", files={"audio": ("a.wav", b"", "audio/wav")}, headers=user).status_code == 400


def test_split_confirm_validates_sum(client, user):
    cap = ingest(client, user, ZOMATO)["capture"]
    bad = client.post(f"{H}/captures/{cap['id']}/confirm", headers=user, json={"items": [
        {"label": "a", "amount_paise": 30000, "category": "Food & Dining"}, {"label": "b", "amount_paise": 10000, "category": "Gifts & Donations"}]})
    assert bad.status_code == 422 and bad.json()["error"]["remaining_paise"] == 5000
    badcat = client.post(f"{H}/captures/{cap['id']}/confirm", headers=user, json={"items": [{"label": "a", "amount_paise": 45000, "category": "Nope"}]})
    assert badcat.json()["error"]["code"] == "bad_category"
    ok = client.post(f"{H}/captures/{cap['id']}/confirm", headers=user, json={"items": [
        {"label": "a", "amount_paise": 30000, "category": "Food & Dining"}, {"label": "b", "amount_paise": 15000, "category": "Gifts & Donations"}]})
    assert ok.status_code == 200 and len(ok.json()["transaction"]["items"]) == 2


def test_merchant_learning_then_auto_apply(client, user):
    for i in range(3):
        r = ingest(client, user, f"Sent Rs.{300 + i}.00 From HDFC Bank A/C *1234 To ZOMATO On 08/11/26 Ref 20000000000{i}")
        assert r["action"] == "prompt"
        client.post(f"{H}/captures/{r['capture']['id']}/confirm", headers=user,
                    json={"items": [{"label": "food", "amount_paise": r["capture"]["amount_paise"], "category": "Food & Dining"}]})
    r = ingest(client, user, "Sent Rs.700.00 From HDFC Bank A/C *1234 To ZOMATO On 08/11/26 Ref 200000000009")
    assert r["action"] == "auto_saved" and r["transaction"]["items"][0]["category"] == "Food & Dining"
    # correcting the category resets learning
    t = r["transaction"]
    client.patch(f"{H}/transactions/{t['id']}", headers=user, json={"items": [{"label": "gift", "amount_paise": 70000, "category": "Gifts & Donations"}]})
    r2 = ingest(client, user, "Sent Rs.710.00 From HDFC Bank A/C *1234 To ZOMATO On 08/11/26 Ref 200000000010")
    assert r2["action"] == "prompt"


def test_cash_voice_amount_from_speech(client, user, mock_gnani):
    v = client.post(f"{H}/cash/voice", files={"audio": ("a.wav", b"RIFFxxxx", "audio/wav")}, data={"mock_transcript": "chai 20 rupees"}, headers=user).json()
    d = v["draft"]
    assert d["amount_paise"] == 2000 and d["items"][0]["category"] == "Food & Dining"
    c = client.post(f"{H}/transactions", headers=user, json={"amount_paise": d["amount_paise"], "items": d["items"], "source": "voice"}).json()
    assert c["transaction"]["instrument"] == "cash"
    n = client.post(f"{H}/cash/note", json={"text": "something odd"}, headers=user).json()["draft"]
    assert n["amount_paise"] is None and n["follow_up_question"] == "How much was it?"


def test_idempotency_prevents_double_save(client, user):
    body = {"amount_paise": 5000, "items": [{"label": "chai", "amount_paise": 5000, "category": "Food & Dining"}]}
    h = {**user, "Idempotency-Key": "abc-1"}
    a = client.post(f"{H}/transactions", json=body, headers=h).json()
    b = client.post(f"{H}/transactions", json=body, headers=h).json()
    assert a["transaction"]["id"] == b["transaction"]["id"]
    assert client.get(f"{H}/transactions", headers=user).json()["total"] == 1


def test_transaction_crud_search(client, user):
    mk = lambda amt, label, cat, cp: client.post(f"{H}/transactions", headers=user, json={"amount_paise": amt, "counterparty": cp, "items": [{"label": label, "amount_paise": amt, "category": cat}]}).json()["transaction"]
    t1 = mk(10000, "Petrol", "Fuel", "HP Pump"); mk(5000, "Chai", "Food & Dining", "Ramu")
    assert client.get(f"{H}/transactions?category=Fuel", headers=user).json()["total"] == 1
    assert client.get(f"{H}/transactions?q=ramu", headers=user).json()["total"] == 1
    assert client.get(f"{H}/transactions/{t1['id']}", headers=user).json()["counterparty"] == "HP Pump"
    assert client.delete(f"{H}/transactions/{t1['id']}", headers=user).status_code == 200
    assert client.get(f"{H}/transactions/{t1['id']}", headers=user).status_code == 404
    assert client.get(f"{H}/transactions?month=2026-13", headers=user).status_code == 422


def test_udhaar_lend_repay_and_reminders(client, user):
    client.post(f"{H}/transactions", headers=user, json={"amount_paise": 50000, "counterparty": "Ramesh", "items": [{"label": "udhaar", "amount_paise": 50000, "category": "Lent (udhaar)"}],
                                                          "udhaar": {"person": "Ramesh", "direction": "i_lent"}})
    u = client.get(f"{H}/udhaar", headers=user).json()
    assert u["you_will_get_paise"] == 50000 and u["items"][0]["person"] == "Ramesh"
    client.post(f"{H}/transactions", headers=user, json={"direction": "credit", "amount_paise": 20000, "counterparty": "Ramesh",
                                                          "items": [{"label": "returned", "amount_paise": 20000, "category": "Repaid"}], "udhaar": {"person": "Ramesh", "direction": "repaid_to_me"}})
    assert client.get(f"{H}/udhaar", headers=user).json()["you_will_get_paise"] == 30000
    rid = u["items"][0]["id"]
    assert client.post(f"{H}/udhaar/{rid}/settle", json={"amount_paise": 99999999}, headers=user).status_code == 422
    assert client.post(f"{H}/udhaar/{rid}/settle", json={}, headers=user).json()["status"] == "settled"
    client.post(f"{H}/udhaar", headers=user, json={"person": "Neha", "direction": "i_borrowed", "amount_paise": 10000, "due_date": "2020-01-01"})
    rem = client.get(f"{H}/udhaar/reminders", headers=user).json()["items"]
    assert rem and rem[0]["reason"] == "overdue" and "Neha" in rem[0]["message"]


def test_budget_alerts_fire_once(client, user):
    client.put(f"{H}/budgets", json={"category": "Food & Dining", "limit_paise": 100000}, headers=user)
    assert client.put(f"{H}/budgets", json={"category": "Lent (udhaar)", "limit_paise": 1}, headers=user).status_code == 422
    mk = lambda amt: client.post(f"{H}/transactions", headers=user, json={"amount_paise": amt, "items": [{"label": "f", "amount_paise": amt, "category": "Food & Dining"}]}).json()
    assert mk(50000)["alerts"] == []
    a = mk(35000)["alerts"]
    assert len(a) == 1 and a[0]["threshold"] == 80
    assert mk(1000)["alerts"] == []                      # already alerted at 80
    a = mk(20000)["alerts"]
    assert a and a[0]["threshold"] == 100
    st = client.get(f"{H}/budgets", headers=user).json()["items"][0]
    assert st["state"] == "over"
    assert client.delete(f"{H}/budgets?category=Food%20%26%20Dining", headers=user).status_code == 200


def test_report_numbers_and_cache(client, user):
    assert client.post(f"{H}/demo/seed-month", headers=user).json()["transactions_created"] == 108
    sm = client.get(f"{H}/reports/monthly", headers=user).json()
    assert sm["total_spent_paise"] > 0 and sum(c["amount_paise"] for c in sm["by_category"]) == sm["total_spent_paise"]
    assert sum(d["amount_paise"] for d in sm["daily"]) == sm["total_spent_paise"]
    assert len(sm["insights"]) == 3 and sm["vs_last_month"]["delta_pct"] is not None and len(sm["top_merchants"]) == 5
    assert sm["insights_provider"] == "rules"
    assert client.get(f"{H}/reports/monthly?month=2020-01", headers=user).json()["total_spent_paise"] == 0
    assert client.get(f"{H}/reports/months", headers=user).json()["months"][0] == sm["month"]


def test_report_excludes_udhaar_from_spend(client, user):
    client.post(f"{H}/transactions", headers=user, json={"amount_paise": 50000, "counterparty": "Ramesh", "items": [{"label": "u", "amount_paise": 50000, "category": "Lent (udhaar)"}], "udhaar": {"person": "Ramesh", "direction": "i_lent"}})
    client.post(f"{H}/transactions", headers=user, json={"amount_paise": 1000, "items": [{"label": "c", "amount_paise": 1000, "category": "Food & Dining"}]})
    sm = client.get(f"{H}/reports/monthly", headers=user).json()
    assert sm["total_spent_paise"] == 1000 and sm["udhaar_lent_paise"] == 50000 and sm["udhaar"]["you_will_get_paise"] == 50000


def test_csv_export_and_formula_injection(client, user):
    client.post(f"{H}/transactions", headers=user, json={"amount_paise": 1000, "counterparty": "=HYPERLINK(1)", "items": [{"label": "+cmd", "amount_paise": 1000, "category": "Other"}]})
    csv = client.get(f"{H}/export/csv", headers=user)
    assert csv.headers["content-type"].startswith("text/csv") and "'=HYPERLINK(1)" in csv.text and "'+cmd" in csv.text


def test_settings_validation(client, user):
    assert client.put(f"{H}/settings", json={"language_hint": "xx-YY"}, headers=user).status_code == 422
    assert client.put(f"{H}/settings", json={"tz": "Mars/Base"}, headers=user).status_code == 422
    s = client.put(f"{H}/settings", json={"language_hint": "te-IN,en-IN", "min_prompt_paise": 10000}, headers=user).json()
    assert s["language_hint"] == "te-IN,en-IN" and s["min_prompt_paise"] == 10000


def test_simulate_presets_and_demo_gate(client, user, monkeypatch):
    acts = [client.post(f"{H}/demo/simulate", json={"preset": i}, headers=user).json()["action"] for i in range(7)]
    assert acts[0] == "prompt" and acts[-1] == "ignored" and "recorded_income" in acts
    monkeypatch.setenv("DEMO_ENABLED", "false")
    assert client.post(f"{H}/demo/simulate", json={"preset": 0}, headers=user).status_code == 404


def test_wipe_and_delete_account(client, user):
    client.post(f"{H}/demo/seed-month", headers=user)
    assert client.delete(f"{H}/me/data", headers=user).json()["deleted"]
    assert client.get(f"{H}/transactions", headers=user).json()["total"] == 0
    assert client.get(f"{H}/udhaar", headers=user).json()["items"] == []
    assert client.delete(f"{H}/me", headers=user).status_code == 200
    assert client.get(f"{H}/me", headers=user).status_code == 401


def test_rate_limit(client, user, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
    codes = [client.get(f"{H}/settings", headers=user).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and codes[3] == 429


def test_validation_error_shape_and_health(client, user):
    r = client.post(f"{H}/transactions", json={"amount_paise": -5, "items": []}, headers=user)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.get(f"{H}/health").json()["ok"] is True


def test_get_single_capture_and_isolation(client, user):
    cap = ingest(client, user, ZOMATO)["capture"]
    assert client.get(f"{H}/captures/{cap['id']}", headers=user).json()["counterparty"] == "ZOMATO"
    other = make_user(client, "other")
    assert client.get(f"{H}/captures/{cap['id']}", headers=other).status_code == 404


def test_static_shell_served(client):
    for path, ct in (("/", "text/html"), ("/sw.js", "javascript"), ("/manifest.webmanifest", "json"), ("/static/js/app.js", "javascript"), ("/static/css/app.css", "css")):
        r = client.get(path)
        assert r.status_code == 200 and ct in r.headers["content-type"], path


def test_undo_returns_payment_to_pending(client, user):
    cap = ingest(client, user, ZOMATO)["capture"]
    tid = client.post(f"{H}/captures/{cap['id']}/confirm", headers=user, json={"items": [{"label": "x", "amount_paise": 45000, "category": "Food & Dining"}]}).json()["transaction"]["id"]
    assert client.get(f"{H}/captures", headers=user).json()["items"] == []
    client.delete(f"{H}/transactions/{tid}", headers=user)
    pend = client.get(f"{H}/captures", headers=user).json()["items"]
    assert len(pend) == 1 and pend[0]["id"] == cap["id"]          # can be answered again


def test_learned_shops_manage(client, user):
    r = client.put(f"{H}/merchants", json={"merchant": "Ramu Tea Stall", "category": "Food & Dining"}, headers=user).json()
    assert r["merchant"] == "ramu tea stall"
    assert client.get(f"{H}/merchants", headers=user).json()["items"][0]["auto_apply"] is True
    # a payment there is now saved silently
    r = ingest(client, user, "Google Pay | Paid ₹900 to Ramu Tea Stall")
    assert r["action"] == "auto_saved" and r["transaction"]["items"][0]["category"] == "Food & Dining"
    assert client.put(f"{H}/merchants", json={"merchant": "x", "category": "Repaid"}, headers=user).status_code == 422
    assert client.delete(f"{H}/merchants?merchant=Ramu%20Tea%20Stall", headers=user).status_code == 200
    assert client.delete(f"{H}/merchants?merchant=nobody", headers=user).status_code == 404
    assert ingest(client, user, "Google Pay | Paid ₹901 to Ramu Tea Stall")["action"] == "prompt"


def test_udhaar_delete_and_json_backup(client, user):
    u = client.post(f"{H}/udhaar", headers=user, json={"person": "Neha", "direction": "i_lent", "amount_paise": 10000}).json()
    client.post(f"{H}/transactions", headers=user, json={"amount_paise": 1000, "items": [{"label": "c", "amount_paise": 1000, "category": "Food & Dining"}]})
    b = client.get(f"{H}/export/json", headers=user)
    assert b.headers["content-type"].startswith("application/json")
    j = b.json(); assert j["app"] == "HisaabBol" and len(j["transactions"]) == 1 and j["udhaar"][0]["person"] == "Neha" and "settings" in j
    assert client.delete(f"{H}/udhaar/{u['id']}", headers=user).status_code == 200
    assert client.delete(f"{H}/udhaar/{u['id']}", headers=user).status_code == 404
    other = make_user(client, "o")
    assert client.delete(f"{H}/udhaar/{u['id']}", headers=other).status_code == 404
