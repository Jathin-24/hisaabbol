"""HisaabBol business logic: ingest -> prompt -> voice/text answer -> transaction -> learning -> udhaar -> budgets -> reports.
Pure functions over a sqlite3 connection. Money = integer paise. Timestamps = UTC ISO strings."""
import csv
import hashlib
import io
import json
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

from . import gnani, llm, parser, rules, textutil
from .errors import ApiError

SPEND_SQL_EXCL = "('Lent (udhaar)','Repaid','Income')"

DEFAULT_SETTINGS = {
    "language_hint": "hi-IN,en-IN", "min_prompt_paise": "5000", "max_prompts_per_day": "5", "tts_enabled": "1",
    "tz": "Asia/Kolkata", "digest_time": "21:00", "ui_lang": "en",
}

PROMPT_TEXT = {
    "en": ("₹{amt} paid to {who}", "What was it for? Tap and say it.", "Who is this for, and why?"),
    "hi": ("{who} को ₹{amt} दिए", "ये किसलिए था? टैप करके बोलिए।", "ये किसके लिए था?"),
    "te": ("{who} కు ₹{amt} చెల్లించారు", "ఇది దేనికి? ట్యాప్ చేసి చెప్పండి.", "ఇది ఎవరి కోసం?"),
}
PERSON_CHIPS = ["Rent & Home", "Family & Friends", "Lent (udhaar)", "Repaid", "Gifts & Donations"]


# ------------------------------------------------------------------ time & settings
def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(utc_now())


def get_settings(db, uid: str) -> dict:
    s = dict(DEFAULT_SETTINGS)
    for r in db.execute("SELECT key,value FROM settings WHERE user_id=?", (uid,)):
        s[r["key"]] = r["value"]
    return s


def settings_out(s: dict) -> dict:
    return {"language_hint": s["language_hint"], "min_prompt_paise": int(s["min_prompt_paise"]),
            "max_prompts_per_day": int(s["max_prompts_per_day"]), "tts_enabled": s["tts_enabled"] == "1",
            "tz": s["tz"], "digest_time": s["digest_time"], "ui_lang": s["ui_lang"]}


def update_settings(db, uid: str, patch: dict) -> dict:
    clean = {}
    for k, v in patch.items():
        if v is None:
            continue
        if k == "language_hint":
            clean[k] = gnani.validate_language_hint(v)
        elif k == "min_prompt_paise":
            if int(v) < 0: raise ApiError(422, "bad_setting", "min_prompt_paise must be >= 0")
            clean[k] = str(int(v))
        elif k == "max_prompts_per_day":
            if not 0 <= int(v) <= 50: raise ApiError(422, "bad_setting", "max_prompts_per_day must be 0..50")
            clean[k] = str(int(v))
        elif k == "tts_enabled":
            clean[k] = "1" if v else "0"
        elif k == "tz":
            try: ZoneInfo(v)
            except Exception: raise ApiError(422, "bad_setting", "Unknown timezone (use an IANA name like Asia/Kolkata)")
            clean[k] = v
        elif k == "digest_time":
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v): raise ApiError(422, "bad_setting", "digest_time must be HH:MM")
            clean[k] = v
        elif k == "ui_lang":
            clean[k] = str(v)[:5]
    for k, v in clean.items():
        db.execute("INSERT INTO settings(user_id,key,value) VALUES (?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value", (uid, k, v))
    db.commit()
    return settings_out(get_settings(db, uid))


def tz_of(s: dict) -> tzinfo:
    try:
        return ZoneInfo(s["tz"])
    except Exception:
        return timezone(timedelta(hours=5, minutes=30), "Asia/Kolkata")


def parse_when(value: str | None, tz) -> datetime:
    if not value:
        return utc_now()
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError(422, "bad_datetime", f"Not an ISO-8601 datetime: {value!r}")
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz)
    return d.astimezone(timezone.utc)


def month_bounds(month: str, tz) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise ApiError(422, "bad_month", "month must be YYYY-MM")
    y, m = int(month[:4]), int(month[5:])
    start = datetime(y, m, 1, tzinfo=tz)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=tz)
    return iso(start), iso(end)


def current_month(tz) -> str:
    return utc_now().astimezone(tz).strftime("%Y-%m")


def prev_month(month: str) -> str:
    y, m = int(month[:4]), int(month[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def local_date(iso_s: str, tz) -> datetime:
    return datetime.fromisoformat(iso_s.replace("Z", "+00:00")).astimezone(tz)


# ------------------------------------------------------------------ serializers
def cap_out(r) -> dict:
    return {"id": r["id"], "direction": r["direction"], "amount_paise": r["amount_paise"], "amount_display": textutil.fmt_inr(r["amount_paise"]),
            "counterparty": r["counterparty"], "counterparty_is_person": None if r["counterparty_is_person"] is None else bool(r["counterparty_is_person"]),
            "instrument": r["instrument"], "account_last4": r["account_last4"], "upi_ref": r["upi_ref"], "source": r["source"], "occurred_at": r["occurred_at"],
            "status": r["status"], "prompted": bool(r["prompted"]), "transaction_id": r["transaction_id"]}


def tx_out(db, r) -> dict:
    items = [dict(id=i["id"], label=i["label"], amount_paise=i["amount_paise"], category=i["category"], note=i["note"])
             for i in db.execute("SELECT * FROM items WHERE transaction_id=? ORDER BY id", (r["id"],))]
    return {"id": r["id"], "capture_id": r["capture_id"], "direction": r["direction"], "amount_paise": r["amount_paise"],
            "amount_display": textutil.fmt_inr(r["amount_paise"]), "counterparty": r["counterparty"], "occurred_at": r["occurred_at"],
            "instrument": r["instrument"], "account_last4": r["account_last4"], "user_note": r["user_note"],
            "note_language": r["note_language"], "confidence": r["confidence"], "needs_review": bool(r["needs_review"]),
            "source": r["source"], "items": items}


def get_tx(db, uid, tid):
    r = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (tid, uid)).fetchone()
    if not r:
        raise ApiError(404, "not_found", "Transaction not found")
    return r


def get_capture(db, uid, cid):
    r = db.execute("SELECT * FROM captures WHERE id=? AND user_id=?", (cid, uid)).fetchone()
    if not r:
        raise ApiError(404, "not_found", "Capture not found")
    return r


# ------------------------------------------------------------------ merchant learning
def merchant_rules_map(db, uid) -> dict[str, str]:
    return {r["merchant_key"]: r["category"] for r in db.execute("SELECT merchant_key,category FROM merchant_rules WHERE user_id=?", (uid,))}


def learn_merchant(db, uid, counterparty, category):
    if not counterparty or category in ("Other", "Income", "Lent (udhaar)", "Repaid"):
        return
    key = counterparty.lower().strip()
    row = db.execute("SELECT * FROM merchant_rules WHERE user_id=? AND merchant_key=?", (uid, key)).fetchone()
    if not row:
        db.execute("INSERT INTO merchant_rules(user_id,merchant_key,category,times_confirmed,auto_apply) VALUES (?,?,?,1,0)", (uid, key, category))
    elif row["category"] == category:
        n = row["times_confirmed"] + 1
        db.execute("UPDATE merchant_rules SET times_confirmed=?, auto_apply=? WHERE user_id=? AND merchant_key=?", (n, 1 if n >= 3 else 0, uid, key))
    else:  # user changed their mind: restart the count with the new category
        db.execute("UPDATE merchant_rules SET category=?, times_confirmed=1, auto_apply=0 WHERE user_id=? AND merchant_key=?", (category, uid, key))


def keyterms(db, uid) -> list[str]:
    """Hints for Prisma v3.0 so merchant names / local words are transcribed correctly."""
    rows = db.execute("SELECT counterparty, COUNT(*) c FROM transactions WHERE user_id=? AND counterparty IS NOT NULL GROUP BY counterparty ORDER BY c DESC LIMIT 25", (uid,))
    terms = [r["counterparty"] for r in rows] + ["udhaar", "kirana", "Zomato", "Swiggy", "petrol", "recharge"]
    seen, out = set(), []
    for t in terms:
        if t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    return out[:40]


# ------------------------------------------------------------------ transactions
def _validate_items(items: list[dict], amount_paise: int) -> list[dict]:
    if not items:
        raise ApiError(422, "no_items", "At least one item is required")
    clean = []
    for it in items:
        cat = it.get("category")
        if cat not in rules.CATEGORIES:
            raise ApiError(422, "bad_category", f"Unknown category {cat!r}", allowed=rules.CATEGORIES)
        a = it.get("amount_paise")
        if not isinstance(a, int) or a <= 0:
            raise ApiError(422, "bad_amount", "Each item needs a positive integer amount_paise")
        clean.append({"label": (it.get("label") or "Item")[:60], "amount_paise": a, "category": cat, "note": it.get("note")})
    s = sum(i["amount_paise"] for i in clean)
    if s != amount_paise:
        raise ApiError(422, "items_sum_mismatch", f"Items add up to {textutil.fmt_inr(s)} but the payment is {textutil.fmt_inr(amount_paise)}",
                       remaining_paise=amount_paise - s)
    return clean


def create_transaction(db, user, *, capture_id=None, direction="debit", amount_paise=None, counterparty=None, occurred_at=None,
                       instrument=None, account_last4=None, items=None, transcript=None, language=None, confidence=None,
                       needs_review=False, source="voice", udhaar_hint=None, remember_merchant=True) -> dict:
    uid = user["id"]
    s = get_settings(db, uid)
    tz = tz_of(s)
    cap = None
    if capture_id is not None:
        cap = get_capture(db, uid, capture_id)
        if cap["status"] == "answered" and cap["transaction_id"]:
            raise ApiError(409, "already_answered", "This payment already has a note", transaction_id=cap["transaction_id"])
        direction, counterparty = cap["direction"], cap["counterparty"] if counterparty is None else counterparty
        amount_paise, occurred_at = cap["amount_paise"], cap["occurred_at"]
        instrument, account_last4 = cap["instrument"], cap["account_last4"]
    if not isinstance(amount_paise, int) or amount_paise <= 0:
        raise ApiError(422, "amount_required", "amount_paise is required for cash / manual entries")
    if direction not in ("debit", "credit"):
        raise ApiError(422, "bad_direction", "direction must be debit or credit")
    clean = _validate_items(items or [], amount_paise)
    when = iso(parse_when(occurred_at, tz))
    cur = db.execute(
        "INSERT INTO transactions(user_id,capture_id,direction,amount_paise,counterparty,occurred_at,instrument,account_last4,user_note,"
        "note_language,confidence,needs_review,source,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (uid, capture_id, direction, amount_paise, counterparty, when, instrument, account_last4, (transcript or None) and transcript[:500],
         language, confidence, 1 if needs_review else 0, source, now_iso()))
    tid = cur.lastrowid
    for it in clean:
        db.execute("INSERT INTO items(transaction_id,user_id,label,amount_paise,category,note) VALUES (?,?,?,?,?,?)",
                   (tid, uid, it["label"], it["amount_paise"], it["category"], it["note"]))
    if cap is not None:
        db.execute("UPDATE captures SET status='answered', transaction_id=? WHERE id=?", (tid, capture_id))
    cats = {i["category"] for i in clean}
    if remember_merchant and direction == "debit" and counterparty and len(cats) == 1:
        learn_merchant(db, uid, counterparty, next(iter(cats)))
    udhaar_updates = apply_udhaar(db, uid, tid, direction, counterparty, clean, udhaar_hint, tz)
    alerts = budget_alerts_for(db, uid, when, clean, direction, tz)
    db.commit()
    first = clean[0]
    spoken_lang = "hi" if s["language_hint"].startswith("hi") else "en"
    return {"transaction": tx_out(db, get_tx(db, uid, tid)), "alerts": alerts, "udhaar_updates": udhaar_updates,
            "speech_text": confirmation_text(spoken_lang, amount_paise,
                                             " and ".join(i["label"] for i in clean) if len(clean) > 1 else first["label"],
                                             direction)}


def confirmation_text(lang: str, amount_paise: int, purpose: str, direction: str = "debit") -> str:
    words = textutil.amount_words(amount_paise)
    purpose = purpose.strip()[:120] or "your expenses"
    if lang == "hi":
        return (f"Achha, {purpose} ke liye {words} ka kharcha note kar liya." if direction == "debit"
                else f"Achha, {purpose} se {words} aaye hain, note kar liya.")
    return (f"Nice, {words} for {purpose} is in your log." if direction == "debit"
            else f"Nice, {words} came in from {purpose}. I've added it to your log.")


def update_transaction(db, user, tid: int, items: list[dict] | None, user_note: str | None, remember_merchant: bool = True) -> dict:
    uid = user["id"]
    t = get_tx(db, uid, tid)
    if items is not None:
        clean = _validate_items(items, t["amount_paise"])
        db.execute("DELETE FROM items WHERE transaction_id=?", (tid,))
        for it in clean:
            db.execute("INSERT INTO items(transaction_id,user_id,label,amount_paise,category,note) VALUES (?,?,?,?,?,?)",
                       (tid, uid, it["label"], it["amount_paise"], it["category"], it["note"]))
        db.execute("UPDATE transactions SET needs_review=0 WHERE id=?", (tid,))
        cats = {i["category"] for i in clean}
        if remember_merchant and t["direction"] == "debit" and t["counterparty"] and len(cats) == 1:
            learn_merchant(db, uid, t["counterparty"], next(iter(cats)))
    if user_note is not None:
        db.execute("UPDATE transactions SET user_note=? WHERE id=?", (user_note[:500], tid))
    db.commit()
    return tx_out(db, get_tx(db, uid, tid))


def delete_transaction(db, uid, tid: int):
    t = get_tx(db, uid, tid)
    db.execute("DELETE FROM udhaar WHERE transaction_id=? AND user_id=?", (tid, uid))  # settlements applied elsewhere are NOT reverted
    if t["capture_id"]:
        db.execute("UPDATE captures SET status='pending', transaction_id=NULL WHERE id=?", (t["capture_id"],))
    db.execute("DELETE FROM transactions WHERE id=?", (tid,))
    db.commit()


def list_transactions(db, uid, *, month=None, category=None, q=None, direction=None, needs_review=None, limit=50, offset=0) -> dict:
    s = get_settings(db, uid)
    where, args = ["t.user_id=?"], [uid]
    if month:
        a, b = month_bounds(month, tz_of(s))
        where += ["t.occurred_at>=?", "t.occurred_at<?"]; args += [a, b]
    if direction:
        where.append("t.direction=?"); args.append(direction)
    if needs_review is not None:
        where.append("t.needs_review=?"); args.append(1 if needs_review else 0)
    if category:
        where.append("EXISTS (SELECT 1 FROM items i WHERE i.transaction_id=t.id AND i.category=?)"); args.append(category)
    if q:
        like = f"%{q.lower()}%"
        where.append("(LOWER(COALESCE(t.counterparty,'')) LIKE ? OR LOWER(COALESCE(t.user_note,'')) LIKE ? OR EXISTS "
                     "(SELECT 1 FROM items i WHERE i.transaction_id=t.id AND LOWER(i.label) LIKE ?))")
        args += [like, like, like]
    w = " AND ".join(where)
    total = db.execute(f"SELECT COUNT(*) c FROM transactions t WHERE {w}", args).fetchone()["c"]
    rows = db.execute(f"SELECT t.* FROM transactions t WHERE {w} ORDER BY t.occurred_at DESC, t.id DESC LIMIT ? OFFSET ?",
                      args + [max(1, min(limit, 200)), max(0, offset)]).fetchall()
    return {"total": total, "items": [tx_out(db, r) for r in rows]}


# ------------------------------------------------------------------ drafts (voice/text -> structured)
def normalize_draft(res: dict, amount_paise: int | None, counterparty: str | None, rules_map: dict, direction: str,
                    transcript: str, language: str | None) -> dict:
    items = [dict(i) for i in res.get("items", [])] or [{"label": counterparty or "Expense", "amount_paise": None, "category": "Other", "note": None}]
    udh = res.get("udhaar")
    conf = float(res.get("confidence", 0.5))
    follow = res.get("follow_up_question")
    review = conf < 0.5
    rule_cat = rules_map.get((counterparty or "").lower())
    for it in items:
        if rule_cat and it["category"] == "Other" and len(items) == 1:
            it["category"] = rule_cat
        if direction == "credit" and it["category"] in ("Other", "Family & Friends"):
            it["category"] = "Income"
        if udh and len(items) == 1 and it["category"] not in ("Lent (udhaar)", "Repaid"):
            it["category"] = "Repaid" if udh["direction"].startswith("repaid") else "Lent (udhaar)"
    if amount_paise:
        if len(items) == 1:
            items[0]["amount_paise"] = amount_paise
        else:
            amts = [i.get("amount_paise") for i in items]
            ssum = sum(a or 0 for a in amts)
            if None in amts or ssum > amount_paise:
                first = items[0]
                items = [{"label": first["label"], "amount_paise": amount_paise, "category": first["category"], "note": None}]
                review = True
                follow = follow or "I couldn't split that — which category fits best?"
            elif ssum < amount_paise:
                items.append({"label": "Remaining", "amount_paise": amount_paise - ssum, "category": "Other", "note": None})
                review = True
    else:
        if any(i.get("amount_paise") is None for i in items):
            follow = "How much was it?"
    total = sum(i.get("amount_paise") or 0 for i in items) or None
    return {"transcript": transcript, "language": language, "amount_paise": amount_paise or total, "items": items, "udhaar": udh,
            "confidence": conf, "follow_up_question": follow, "needs_review": review, "provider": res.get("provider")}


async def build_draft(db, uid, transcript: str, language: str | None, *, amount_paise=None, counterparty=None,
                      is_person=None, direction="debit") -> dict:
    s = get_settings(db, uid)
    rmap = merchant_rules_map(db, uid)
    res = await llm.understand(transcript, amount_paise, counterparty, is_person, direction, rmap, s["language_hint"])
    return normalize_draft(res, amount_paise, counterparty, rmap, direction, transcript, language)


# ------------------------------------------------------------------ udhaar
def _person(db, uid, name: str) -> int:
    name = name.strip()[:60]
    db.execute("INSERT OR IGNORE INTO people(user_id,name) VALUES (?,?)", (uid, name))
    return db.execute("SELECT id FROM people WHERE user_id=? AND name=?", (uid, name)).fetchone()["id"]


def _settle_fifo(db, uid, person_id, record_dir, amount) -> int:
    left = amount
    for r in db.execute("SELECT * FROM udhaar WHERE user_id=? AND person_id=? AND direction=? AND status='open' ORDER BY created_at, id",
                        (uid, person_id, record_dir)).fetchall():
        if left <= 0:
            break
        take = min(left, r["amount_paise"] - r["settled_paise"])
        ns = r["settled_paise"] + take
        db.execute("UPDATE udhaar SET settled_paise=?, status=? WHERE id=?", (ns, "settled" if ns >= r["amount_paise"] else "open", r["id"]))
        left -= take
    return amount - left


def apply_udhaar(db, uid, tid, direction, counterparty, items, hint, tz) -> list[dict]:
    out = []
    for it in items:
        cat = it["category"]
        if cat not in ("Lent (udhaar)", "Repaid"):
            continue
        h = hint or {}
        person = (h.get("person") or counterparty or "").strip()
        if not person:
            continue
        d = h.get("direction")
        pid = _person(db, uid, person)
        if cat == "Lent (udhaar)":
            d = d if d in ("i_lent", "i_borrowed") else ("i_lent" if direction == "debit" else "i_borrowed")
            db.execute("INSERT INTO udhaar(user_id,person_id,direction,amount_paise,transaction_id,created_at) VALUES (?,?,?,?,?,?)",
                       (uid, pid, d, it["amount_paise"], tid, now_iso()))
            out.append({"type": "created", "person": person, "direction": d, "amount_paise": it["amount_paise"]})
        else:
            d = d if d in ("repaid_by_me", "repaid_to_me") else ("repaid_by_me" if direction == "debit" else "repaid_to_me")
            applied = _settle_fifo(db, uid, pid, "i_borrowed" if d == "repaid_by_me" else "i_lent", it["amount_paise"])
            out.append({"type": "settled", "person": person, "direction": d, "applied_paise": applied})
    return out


def udhaar_row(r) -> dict:
    out = r["amount_paise"] - r["settled_paise"]
    return {"id": r["id"], "person": r["name"], "direction": r["direction"], "amount_paise": r["amount_paise"],
            "settled_paise": r["settled_paise"], "outstanding_paise": out, "outstanding_display": textutil.fmt_inr(out),
            "due_date": r["due_date"], "status": r["status"], "note": r["note"], "created_at": r["created_at"]}


def list_udhaar(db, uid, status="open") -> dict:
    q = "SELECT u.*, p.name FROM udhaar u JOIN people p ON p.id=u.person_id WHERE u.user_id=?"
    args = [uid]
    if status in ("open", "settled"):
        q += " AND u.status=?"; args.append(status)
    rows = [udhaar_row(r) for r in db.execute(q + " ORDER BY u.created_at DESC", args)]
    get = sum(r["outstanding_paise"] for r in rows if r["direction"] == "i_lent" and r["status"] == "open")
    give = sum(r["outstanding_paise"] for r in rows if r["direction"] == "i_borrowed" and r["status"] == "open")
    return {"you_will_get_paise": get, "you_have_to_give_paise": give, "you_will_get_display": textutil.fmt_inr(get),
            "you_have_to_give_display": textutil.fmt_inr(give), "items": rows}


def add_udhaar(db, uid, person, direction, amount_paise, due_date, note) -> dict:
    if direction not in ("i_lent", "i_borrowed"):
        raise ApiError(422, "bad_direction", "direction must be i_lent or i_borrowed")
    if not person or not person.strip():
        raise ApiError(422, "person_required", "person is required")
    if due_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due_date):
        raise ApiError(422, "bad_date", "due_date must be YYYY-MM-DD")
    pid = _person(db, uid, person)
    cur = db.execute("INSERT INTO udhaar(user_id,person_id,direction,amount_paise,due_date,note,created_at) VALUES (?,?,?,?,?,?,?)",
                     (uid, pid, direction, amount_paise, due_date, note, now_iso()))
    db.commit()
    return udhaar_row(db.execute("SELECT u.*, p.name FROM udhaar u JOIN people p ON p.id=u.person_id WHERE u.id=?", (cur.lastrowid,)).fetchone())


def settle_udhaar(db, uid, udhaar_id, amount_paise=None) -> dict:
    r = db.execute("SELECT * FROM udhaar WHERE id=? AND user_id=?", (udhaar_id, uid)).fetchone()
    if not r:
        raise ApiError(404, "not_found", "Udhaar record not found")
    outstanding = r["amount_paise"] - r["settled_paise"]
    amt = outstanding if amount_paise is None else amount_paise
    if amt <= 0 or amt > outstanding:
        raise ApiError(422, "bad_amount", f"Settle between 1 and {outstanding} paise", outstanding_paise=outstanding)
    ns = r["settled_paise"] + amt
    db.execute("UPDATE udhaar SET settled_paise=?, status=? WHERE id=?", (ns, "settled" if ns >= r["amount_paise"] else "open", udhaar_id))
    db.commit()
    return udhaar_row(db.execute("SELECT u.*, p.name FROM udhaar u JOIN people p ON p.id=u.person_id WHERE u.id=?", (udhaar_id,)).fetchone())


def udhaar_reminders(db, uid) -> list[dict]:
    today = utc_now().date()
    out = []
    for r in list_udhaar(db, uid, "open")["items"]:
        reason = None
        if r["due_date"]:
            dd = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
            if dd < today: reason = "overdue"
            elif dd <= today + timedelta(days=1): reason = "due_soon"
        elif (utc_now() - datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))).days >= 30:
            reason = "open_30_days"
        if reason:
            verb = "owes you" if r["direction"] == "i_lent" else "is owed by you"
            out.append({**r, "reason": reason, "message": f"{r['person']} {verb} {r['outstanding_display']}"})
    return out


def delete_udhaar(db, uid, udhaar_id):
    if not db.execute("DELETE FROM udhaar WHERE id=? AND user_id=?", (udhaar_id, uid)).rowcount:
        raise ApiError(404, "not_found", "Udhaar record not found")
    db.commit()


# ------------------------------------------------------------------ learned shops
def list_merchants(db, uid) -> list[dict]:
    return [{"merchant": r["merchant_key"], "category": r["category"], "times_confirmed": r["times_confirmed"], "auto_apply": bool(r["auto_apply"])}
            for r in db.execute("SELECT * FROM merchant_rules WHERE user_id=? ORDER BY times_confirmed DESC, merchant_key", (uid,))]


def set_merchant(db, uid, merchant: str, category: str, auto_apply: bool = True) -> dict:
    key = (merchant or "").strip().lower()
    if not key:
        raise ApiError(422, "merchant_required", "merchant is required")
    if category not in rules.SPEND_CATEGORIES or category in ("Lent (udhaar)", "Repaid"):
        raise ApiError(422, "bad_category", "Pick a spending category")
    db.execute("INSERT INTO merchant_rules(user_id,merchant_key,category,times_confirmed,auto_apply) VALUES (?,?,?,3,?) "
               "ON CONFLICT(user_id,merchant_key) DO UPDATE SET category=excluded.category, auto_apply=excluded.auto_apply, times_confirmed=MAX(times_confirmed,3)",
               (uid, key, category, 1 if auto_apply else 0))
    db.commit()
    return {"merchant": key, "category": category, "auto_apply": auto_apply}


def delete_merchant(db, uid, merchant: str):
    if not db.execute("DELETE FROM merchant_rules WHERE user_id=? AND merchant_key=?", (uid, (merchant or "").strip().lower())).rowcount:
        raise ApiError(404, "not_found", "No such learned shop")
    db.commit()


def export_json(db, uid) -> dict:
    txs = [tx_out(db, r) for r in db.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY occurred_at", (uid,))]
    return {"app": "HisaabBol", "version": 1, "exported_at": now_iso(), "settings": settings_out(get_settings(db, uid)), "transactions": txs,
            "udhaar": list_udhaar(db, uid, "all")["items"], "budgets": [{"category": None if b["category"] == "*" else b["category"], "limit_paise": b["limit_paise"]}
                                                                          for b in db.execute("SELECT * FROM budgets WHERE user_id=?", (uid,))],
            "learned_shops": list_merchants(db, uid)}


# ------------------------------------------------------------------ budgets
def set_budget(db, uid, category: str | None, limit_paise: int) -> dict:
    cat = category or "*"
    if cat != "*" and (cat not in rules.SPEND_CATEGORIES or cat in rules.NON_SPEND):
        raise ApiError(422, "bad_category", "Budgets apply to spending categories", allowed=[c for c in rules.SPEND_CATEGORIES if c not in rules.NON_SPEND])
    db.execute("INSERT INTO budgets(user_id,category,limit_paise) VALUES (?,?,?) ON CONFLICT(user_id,category) DO UPDATE SET limit_paise=excluded.limit_paise",
               (uid, cat, limit_paise))
    db.commit()
    return {"category": None if cat == "*" else cat, "limit_paise": limit_paise}


def delete_budget(db, uid, category: str | None):
    n = db.execute("DELETE FROM budgets WHERE user_id=? AND category=?", (uid, category or "*")).rowcount
    db.commit()
    if not n:
        raise ApiError(404, "not_found", "No such budget")


def month_spend(db, uid, month: str, tz) -> dict[str, int]:
    a, b = month_bounds(month, tz)
    rows = db.execute(f"SELECT i.category, SUM(i.amount_paise) s FROM items i JOIN transactions t ON t.id=i.transaction_id "
                      f"WHERE t.user_id=? AND t.direction='debit' AND t.occurred_at>=? AND t.occurred_at<? AND i.category NOT IN {SPEND_SQL_EXCL} "
                      f"GROUP BY i.category", (uid, a, b)).fetchall()
    return {r["category"]: r["s"] for r in rows}


def budget_status(db, uid, month: str | None = None) -> list[dict]:
    tz = tz_of(get_settings(db, uid))
    month = month or current_month(tz)
    spent = month_spend(db, uid, month, tz)
    total = sum(spent.values())
    out = []
    for b in db.execute("SELECT * FROM budgets WHERE user_id=? ORDER BY category", (uid,)):
        sp = total if b["category"] == "*" else spent.get(b["category"], 0)
        pct = round(sp * 100 / b["limit_paise"], 1)
        out.append({"category": None if b["category"] == "*" else b["category"], "limit_paise": b["limit_paise"], "spent_paise": sp,
                    "percent": pct, "state": "over" if pct >= 100 else "warning" if pct >= 80 else "ok", "month": month})
    return out


def budget_alerts_for(db, uid, when_iso: str, items, direction, tz) -> list[dict]:
    if direction != "debit":
        return []
    month = local_date(when_iso, tz).strftime("%Y-%m")
    touched = {i["category"] for i in items if i["category"] not in rules.NON_SPEND} | {"*"}
    alerts = []
    for b in budget_status(db, uid, month):
        key = b["category"] or "*"
        if key not in touched:
            continue
        for thr in (100, 80):
            if b["percent"] >= thr:
                cur = db.execute("INSERT OR IGNORE INTO budget_alerts(user_id,category,month,threshold) VALUES (?,?,?,?)", (uid, key, month, thr))
                if cur.rowcount:
                    who = b["category"] or "overall"
                    alerts.append({"category": b["category"], "threshold": thr, "percent": b["percent"],
                                   "message": f"You've used {b['percent']:.0f}% of your {who} budget for {month}"
                                              f" ({textutil.fmt_inr(b['spent_paise'])} of {textutil.fmt_inr(b['limit_paise'])})."})
                break
    return alerts


# ------------------------------------------------------------------ ingest (payment detected)
def _prompt_payload(s: dict, cap) -> dict:
    lang = s["ui_lang"] if s["ui_lang"] in PROMPT_TEXT else "en"
    title, body, person_body = PROMPT_TEXT[lang]
    who = cap["counterparty"] or "unknown"
    is_person = bool(cap["counterparty_is_person"])
    amt = textutil.fmt_inr(cap["amount_paise"]).lstrip("₹")
    out = {"title": title.format(amt=amt, who=who), "body": person_body if is_person else body, "capture_id": cap["id"],
           "open": f"/capture/{cap['id']}"}
    if is_person:
        out["quick_chips"] = PERSON_CHIPS
    return out


def ingest(db, user, *, raw_text=None, parsed=None, source="notification", received_at=None, package=None) -> dict:
    uid = user["id"]
    s = get_settings(db, uid)
    tz = tz_of(s)
    when = iso(parse_when(received_at, tz))
    if parsed is None:
        parsed = parser.parse_payment(raw_text or "", source=source, received_at=when)
        if parsed is None:
            return {"action": "ignored", "reason": "not_a_completed_payment", "capture": None, "transaction": None, "prompt": None}
    else:
        parsed = dict(parsed)
        if parsed.get("amount_paise") is None and parsed.get("amount") is not None:
            parsed["amount_paise"] = int(round(float(parsed["amount"]) * 100))
        if not parsed.get("amount_paise") or parsed["amount_paise"] <= 0:
            raise ApiError(422, "bad_amount", "parsed.amount_paise (or amount in rupees) must be positive")
        if parsed.get("direction") not in ("debit", "credit"):
            raise ApiError(422, "bad_direction", "parsed.direction must be debit or credit")
        parsed["occurred_at"] = when if not parsed.get("occurred_at") else iso(parse_when(parsed["occurred_at"], tz))
        cp = parsed.get("counterparty")
        if cp and parsed.get("counterparty_is_person") is None:
            parsed["counterparty_is_person"] = parser.looks_like_person(cp)
    occurred = parsed["occurred_at"] or when
    ref = parsed.get("upi_ref")
    dedupe = f"ref:{ref}" if ref else (parsed.get("dedupe_key") or f"amt:{parsed['amount_paise']}|cp:{(parsed.get('counterparty') or '').lower()}|min:{occurred[:16]}")

    # duplicate across sources (bank SMS + UPI-app notification): same direction & amount within 10 minutes, refs not conflicting
    t0 = datetime.fromisoformat(occurred.replace("Z", "+00:00"))
    lo, hi = iso(t0 - timedelta(minutes=10)), iso(t0 + timedelta(minutes=10))
    for e in db.execute("SELECT * FROM captures WHERE user_id=? AND direction=? AND amount_paise=? AND occurred_at BETWEEN ? AND ?",
                        (uid, parsed["direction"], parsed["amount_paise"], lo, hi)).fetchall():
        if e["upi_ref"] and ref and e["upi_ref"] != ref:
            continue
        sets, vals = [], []
        for col, key in (("counterparty", "counterparty"), ("upi_ref", "upi_ref"), ("account_last4", "account_last4")):
            if not e[col] and parsed.get(key):
                sets.append(f"{col}=?"); vals.append(parsed[key])
        if sets:
            db.execute(f"UPDATE captures SET {','.join(sets)} WHERE id=?", vals + [e["id"]])
            if e["transaction_id"] and parsed.get("counterparty") and not e["counterparty"]:
                db.execute("UPDATE transactions SET counterparty=? WHERE id=? AND counterparty IS NULL", (parsed["counterparty"], e["transaction_id"]))
            db.commit()
        return {"action": "duplicate", "capture": cap_out(db.execute("SELECT * FROM captures WHERE id=?", (e["id"],)).fetchone()),
                "transaction": None, "prompt": None}

    cur = db.execute(
        "INSERT OR IGNORE INTO captures(user_id,dedupe_key,direction,amount_paise,counterparty,counterparty_is_person,upi_ref,account_last4,"
        "instrument,source,occurred_at,status,prompted,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending',0,?)",
        (uid, dedupe, parsed["direction"], parsed["amount_paise"], parsed.get("counterparty"),
         None if parsed.get("counterparty_is_person") is None else int(bool(parsed["counterparty_is_person"])),
         ref, parsed.get("account_last4"), parsed.get("instrument"), source, occurred, now_iso()))
    if cur.rowcount == 0:
        r = db.execute("SELECT * FROM captures WHERE user_id=? AND dedupe_key=?", (uid, dedupe)).fetchone()
        return {"action": "duplicate", "capture": cap_out(r), "transaction": None, "prompt": None}
    cid = cur.lastrowid
    cap = db.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()

    def auto(category, label, conf, review, action):
        res = create_transaction(db, user, capture_id=cid, items=[{"label": label, "amount_paise": cap["amount_paise"], "category": category, "note": None}],
                                 confidence=conf, needs_review=review, source="auto", remember_merchant=False)
        db.execute("UPDATE captures SET status='auto_categorized' WHERE id=?", (cid,))
        db.commit()
        return {"action": action, "capture": cap_out(db.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()),
                "transaction": res["transaction"], "prompt": None, "alerts": res["alerts"]}

    label = cap["counterparty"] or "Payment"
    if cap["direction"] == "credit":
        return auto("Income", label, 0.5, False, "recorded_income")
    key = (cap["counterparty"] or "").lower().strip()
    rule = db.execute("SELECT * FROM merchant_rules WHERE user_id=? AND merchant_key=? AND auto_apply=1", (uid, key)).fetchone() if key else None
    if rule:
        return auto(rule["category"], label, 0.9, False, "auto_saved")
    if cap["amount_paise"] < int(s["min_prompt_paise"]):
        cat, conf = rules.categorize(label, cap["counterparty"], bool(cap["counterparty_is_person"]))
        return auto(cat, label, conf, conf < 0.5, "auto_saved")
    day_start = iso(utc_now().astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0))
    used = db.execute("SELECT COUNT(*) c FROM captures WHERE user_id=? AND prompted=1 AND created_at>=?", (uid, day_start)).fetchone()["c"]
    if used >= int(s["max_prompts_per_day"]):
        db.commit()
        return {"action": "digest", "capture": cap_out(cap), "transaction": None, "prompt": None}
    db.execute("UPDATE captures SET prompted=1 WHERE id=?", (cid,))
    db.commit()
    cap = db.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone()
    return {"action": "prompt", "capture": cap_out(cap), "transaction": None, "prompt": _prompt_payload(s, cap)}


def list_captures(db, uid, status="pending", limit=100) -> list[dict]:
    q, a = "SELECT * FROM captures WHERE user_id=?", [uid]
    if status != "all":
        q += " AND status=?"; a.append(status)
    return [cap_out(r) for r in db.execute(q + " ORDER BY occurred_at DESC LIMIT ?", a + [min(limit, 200)])]


def digest(db, uid) -> dict:
    s = get_settings(db, uid)
    pend = db.execute("SELECT * FROM captures WHERE user_id=? AND status='pending' AND direction='debit' ORDER BY amount_paise DESC", (uid,)).fetchall()
    return {"digest_time": s["digest_time"], "count": len(pend), "total_paise": sum(r["amount_paise"] for r in pend),
            "captures": [cap_out(r) for r in pend[:25]], "reminders": udhaar_reminders(db, uid)}


def skip_capture(db, uid, cid):
    c = get_capture(db, uid, cid)
    if c["status"] == "answered":
        raise ApiError(409, "already_answered", "Already answered")
    db.execute("UPDATE captures SET status='skipped' WHERE id=?", (cid,))
    db.commit()
    return cap_out(db.execute("SELECT * FROM captures WHERE id=?", (cid,)).fetchone())


# ------------------------------------------------------------------ reports
def _month_items(db, uid, month, tz):
    a, b = month_bounds(month, tz)
    return db.execute("SELECT i.label, i.amount_paise, i.category, t.id tid, t.direction, t.counterparty, t.occurred_at "
                      "FROM items i JOIN transactions t ON t.id=i.transaction_id WHERE t.user_id=? AND t.occurred_at>=? AND t.occurred_at<?",
                      (uid, a, b)).fetchall()


def _totals(rows):
    spend = [r for r in rows if r["direction"] == "debit" and r["category"] not in rules.NON_SPEND]
    return sum(r["amount_paise"] for r in spend), spend


def build_summary(db, uid, month: str) -> dict:
    s = get_settings(db, uid)
    tz = tz_of(s)
    rows = _month_items(db, uid, month, tz)
    total_spent, spend = _totals(rows)
    income = sum(r["amount_paise"] for r in rows if r["direction"] == "credit" and r["category"] == "Income")
    lent = sum(r["amount_paise"] for r in rows if r["category"] == "Lent (udhaar)" and r["direction"] == "debit")
    repaid = sum(r["amount_paise"] for r in rows if r["category"] == "Repaid" and r["direction"] == "debit")
    by_cat = defaultdict(lambda: [0, 0])
    merch = defaultdict(lambda: [0, 0])
    for r in spend:
        by_cat[r["category"]][0] += r["amount_paise"]; by_cat[r["category"]][1] += 1
        m = r["counterparty"] or r["label"]
        merch[m][0] += r["amount_paise"]; merch[m][1] += 1
    cats = [{"category": c, "amount_paise": v[0], "count": v[1], "percent": round(v[0] * 100 / total_spent, 1) if total_spent else 0}
            for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1][0])]
    top = [{"merchant": m, "amount_paise": v[0], "count": v[1]} for m, v in sorted(merch.items(), key=lambda kv: -kv[1][0])[:5]]
    y, mo = int(month[:4]), int(month[5:])
    days = (datetime(y + (mo == 12), 1 if mo == 12 else mo + 1, 1) - datetime(y, mo, 1)).days
    daily = {f"{month}-{d:02d}": 0 for d in range(1, days + 1)}
    today_local = utc_now().astimezone(tz).date()
    wk_days = {"weekday": set(), "weekend": set()}
    wk_sum = {"weekday": 0, "weekend": 0}
    for r in spend:
        daily[local_date(r["occurred_at"], tz).strftime("%Y-%m-%d")] += r["amount_paise"]
    for dstr, amt in daily.items():
        dt = datetime.strptime(dstr, "%Y-%m-%d")
        if month == current_month(tz) and dt.date() > today_local:
            continue  # future days of the current month don't count as zero-spend days
        key = "weekend" if dt.weekday() >= 5 else "weekday"
        wk_days[key].add(dstr)
        wk_sum[key] += amt
    prev_rows = _month_items(db, uid, prev_month(month), tz)
    prev_total, _ = _totals(prev_rows)
    delta_pct = round((total_spent - prev_total) * 100 / prev_total, 1) if prev_total else None
    biggest = max(spend, key=lambda r: r["amount_paise"], default=None)
    pending = db.execute("SELECT COUNT(*) c FROM captures WHERE user_id=? AND status='pending'", (uid,)).fetchone()["c"]
    review = db.execute("SELECT COUNT(*) c FROM transactions WHERE user_id=? AND needs_review=1", (uid,)).fetchone()["c"]
    ud = list_udhaar(db, uid, "open")
    elapsed = len([d for d in daily if not (month == current_month(tz) and datetime.strptime(d, "%Y-%m-%d").date() > utc_now().astimezone(tz).date())]) or 1
    summary = {
        "month": month, "total_spent_paise": total_spent, "total_spent_display": textutil.fmt_inr(total_spent),
        "total_income_paise": income, "udhaar_lent_paise": lent, "debt_repaid_paise": repaid,
        "transaction_count": len({r["tid"] for r in rows}), "avg_per_day_paise": total_spent // elapsed,
        "by_category": cats, "top_merchants": top,
        "daily": [{"date": d, "amount_paise": a} for d, a in daily.items()],
        "biggest_expense": ({"label": biggest["label"], "merchant": biggest["counterparty"], "amount_paise": biggest["amount_paise"],
                             "date": local_date(biggest["occurred_at"], tz).strftime("%Y-%m-%d")} if biggest else None),
        "vs_last_month": {"previous_month": prev_month(month), "previous_total_paise": prev_total, "delta_paise": total_spent - prev_total, "delta_pct": delta_pct},
        "weekday_weekend": {"weekday_total_paise": wk_sum["weekday"], "weekend_total_paise": wk_sum["weekend"],
                            "weekday_days": len(wk_days["weekday"]), "weekend_days": len(wk_days["weekend"])},
        "udhaar": {"you_will_get_paise": ud["you_will_get_paise"], "you_have_to_give_paise": ud["you_have_to_give_paise"]},
        "budgets": budget_status(db, uid, month), "pending_notes": pending, "needs_review": review,
    }
    summary["facts"] = make_facts(summary)
    return summary


def make_facts(sm: dict) -> list[str]:
    f, F = [], textutil.fmt_inr
    if sm["by_category"]:
        c = sm["by_category"][0]
        f.append(f"{c['category']} was your biggest category: {F(c['amount_paise'])}, {c['percent']:.0f}% of spending.")
    v = sm["vs_last_month"]
    if v["delta_pct"] is not None:
        pm = datetime.strptime(v["previous_month"], "%Y-%m").strftime("%B %Y")
        f.append(f"Spending is {abs(v['delta_pct']):.0f}% {'higher' if v['delta_pct'] > 0 else 'lower'} than {pm} ({F(abs(v['delta_paise']))} {'more' if v['delta_pct'] > 0 else 'less'}).")
    if sm["top_merchants"] and sm["top_merchants"][0]["count"] > 1:
        m = sm["top_merchants"][0]
        f.append(f"You paid {m['merchant']} {m['count']} times, {F(m['amount_paise'])} in total.")
    b = sm["biggest_expense"]
    if b:
        f.append(f"Your biggest single expense was {F(b['amount_paise'])} for {b['label']} on {b['date']}.")
    w = sm["weekday_weekend"]
    if w["weekday_days"] and w["weekend_days"] and (w["weekday_total_paise"] or w["weekend_total_paise"]):
        wd, we = w["weekday_total_paise"] // w["weekday_days"], w["weekend_total_paise"] // w["weekend_days"]
        f.append(f"Weekend days averaged {F(we)} versus {F(wd)} on weekdays.")
    if sm["udhaar"]["you_will_get_paise"]:
        f.append(f"{F(sm['udhaar']['you_will_get_paise'])} is still owed to you.")
    if sm["pending_notes"]:
        f.append(f"{sm['pending_notes']} payments still need a note, so this report may change.")
    return f


async def monthly_report(db, user, month: str | None, refresh: bool, language: str) -> dict:
    uid = user["id"]
    tz = tz_of(get_settings(db, uid))
    month = month or current_month(tz)
    sm = build_summary(db, uid, month)
    fp = hashlib.sha1(f"{sm['transaction_count']}|{sm['total_spent_paise']}|{sm['total_income_paise']}|{sm['pending_notes']}".encode()).hexdigest()
    row = db.execute("SELECT * FROM reports WHERE user_id=? AND month=? AND language=?", (uid, month, language)).fetchone()
    if row and row["fingerprint"] == fp and not refresh:
        sm["insights"], sm["insights_provider"] = json.loads(row["insights_json"]), row["provider"]
        return sm
    brief = {k: sm[k] for k in ("month", "total_spent_display", "transaction_count")}
    ins, prov = await llm.phrase_insights(sm["facts"], brief, language)
    db.execute("INSERT INTO reports(user_id,month,fingerprint,language,insights_json,provider,generated_at) VALUES (?,?,?,?,?,?,?) "
               "ON CONFLICT(user_id,month,language) DO UPDATE SET fingerprint=excluded.fingerprint, insights_json=excluded.insights_json, "
               "provider=excluded.provider, generated_at=excluded.generated_at", (uid, month, fp, language, json.dumps(ins, ensure_ascii=False), prov, now_iso()))
    db.commit()
    sm["insights"], sm["insights_provider"] = ins, prov
    return sm


def report_months(db, uid) -> list[str]:
    tz = tz_of(get_settings(db, uid))
    ms = {local_date(r["occurred_at"], tz).strftime("%Y-%m") for r in db.execute("SELECT occurred_at FROM transactions WHERE user_id=?", (uid,))}
    ms.add(current_month(tz))
    return sorted(ms, reverse=True)


# ------------------------------------------------------------------ export / privacy
def _csv_safe(v):
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def export_csv(db, uid, month: str | None) -> str:
    tz = tz_of(get_settings(db, uid))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date_local", "direction", "payment_amount_inr", "merchant", "item_label", "item_amount_inr", "category", "note", "instrument", "source"])
    q, a = "SELECT * FROM transactions WHERE user_id=?", [uid]
    if month:
        lo, hi = month_bounds(month, tz)
        q += " AND occurred_at>=? AND occurred_at<?"; a += [lo, hi]
    for t in db.execute(q + " ORDER BY occurred_at", a).fetchall():
        for it in db.execute("SELECT * FROM items WHERE transaction_id=?", (t["id"],)):
            w.writerow([_csv_safe(local_date(t["occurred_at"], tz).strftime("%Y-%m-%d %H:%M")), t["direction"], f"{t['amount_paise'] / 100:.2f}",
                        _csv_safe(t["counterparty"]), _csv_safe(it["label"]), f"{it['amount_paise'] / 100:.2f}", _csv_safe(it["category"]),
                        _csv_safe(t["user_note"]), t["instrument"] or "", t["source"]])
    return buf.getvalue()


_DATA_TABLES = ["budget_alerts", "reports", "idempotency", "api_log", "gnani_usage", "udhaar", "people", "merchant_rules", "budgets", "items", "transactions", "captures"]


def wipe_data(db, uid):
    for t in _DATA_TABLES:
        db.execute(f"DELETE FROM {t} WHERE user_id=?", (uid,))
    db.commit()


def delete_account(db, uid):
    wipe_data(db, uid)
    db.execute("DELETE FROM settings WHERE user_id=?", (uid,))
    db.execute("DELETE FROM users WHERE id=?", (uid,))
    db.commit()


# ------------------------------------------------------------------ idempotency, usage log, diagnostics
def idem_get(db, uid, key):
    if not key:
        return None
    r = db.execute("SELECT response_json FROM idempotency WHERE user_id=? AND key=?", (uid, key[:100])).fetchone()
    return json.loads(r["response_json"]) if r else None


def idem_put(db, uid, key, response: dict):
    if key:
        db.execute("INSERT OR IGNORE INTO idempotency(user_id,key,response_json,created_at) VALUES (?,?,?,?)", (uid, key[:100], json.dumps(response), now_iso()))
        db.commit()


def log_gnani(db, uid, kind, ok, latency_ms=None, audio_bytes=None, chars=None):
    db.execute("INSERT INTO gnani_usage(user_id,kind,ok,latency_ms,audio_bytes,chars,created_at) VALUES (?,?,?,?,?,?,?)",
               (uid, kind, 1 if ok else 0, latency_ms, audio_bytes, chars, now_iso()))
    db.commit()


def diagnostics(db, uid) -> dict:
    since = iso(utc_now() - timedelta(hours=24))
    usage = {r["kind"]: {"calls_total": r["n"], "ok_total": r["ok"], "avg_latency_ms": int(r["lat"] or 0)} for r in db.execute(
        "SELECT kind, COUNT(*) n, SUM(ok) ok, AVG(latency_ms) lat FROM gnani_usage WHERE user_id=? GROUP BY kind", (uid,))}
    last24 = {r["kind"]: r["n"] for r in db.execute("SELECT kind, COUNT(*) n FROM gnani_usage WHERE user_id=? AND created_at>=? GROUP BY kind", (uid, since))}
    calls = [dict(r) for r in db.execute("SELECT route, method, status, latency_ms, created_at FROM api_log WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))]
    return {"gnani_usage": usage, "gnani_calls_last_24h": last24, "recent_api_calls": calls}


# ------------------------------------------------------------------ demo helpers
SIM_PRESETS = [
    {"name": "Zomato via HDFC UPI", "text": "Sent Rs.450.00 From HDFC Bank A/C *1234 To ZOMATO On {d} Ref {ref} Not You? Call 18002586161"},
    {"name": "Tea stall via Axis", "text": "Debit INR 120.00 A/c no. XX1234 {d} 10:15:22 UPI/P2M/{ref}/RAMU TEA STALL SMS BLOCKUPI Cust ID to 18001035577 if not you - Axis Bank"},
    {"name": "Person payee (Ramesh)", "text": "Sent Rs.2400.00 From HDFC Bank A/C *1234 To RAMESH KUMAR On {d} Ref {ref}"},
    {"name": "GPay notification", "text": "Google Pay | Paid ₹250 to Big Bazaar Kirana"},
    {"name": "Credit card spend", "text": "Rs 1,250.00 spent on HDFC Bank Card x1234 at AMAZON on {d}:10:15:22. Not you? Call 18002586161"},
    {"name": "UPI credit received", "text": "Rs 5000.00 credited to a/c XX1234 on {d} by a/c linked to mobile 98XXXXX210 (UPI Ref No {ref})"},
    {"name": "OTP (should be ignored)", "text": "123456 is your OTP for transaction of Rs 250.00 at ZOMATO. Do not share."},
]


def render_preset(idx: int, tz) -> str:
    p = SIM_PRESETS[idx]
    return p["text"].format(d=utc_now().astimezone(tz).strftime("%d/%m/%y"), ref=str(random.randint(10**11, 10**12 - 1)))


_SEED = [  # label, category, merchant, min, max, weight
    ("Chai", "Food & Dining", "Ramu Tea Stall", 10, 40, 14), ("Lunch", "Food & Dining", "Zomato", 150, 450, 8),
    ("Groceries", "Groceries", "Big Bazaar Kirana", 200, 1400, 6), ("Vegetables", "Groceries", "Sabzi Mandi", 80, 300, 5),
    ("Auto", "Transport", "Rapido", 40, 220, 10), ("Petrol", "Fuel", "HP Petrol Pump", 200, 600, 3),
    ("Mobile recharge", "Bills & Recharge", "Jio", 239, 299, 1), ("Movie", "Entertainment", "BookMyShow", 200, 600, 2),
    ("Medicine", "Health", "Apollo Pharmacy", 60, 500, 2), ("Shirt", "Shopping", "Myntra", 500, 1800, 1),
    ("Rent share", "Rent & Home", "Ramesh Kumar", 4000, 4000, 1), ("Birthday gift", "Gifts & Donations", "Amazon", 300, 1200, 1),
]


def seed_month(db, user) -> dict:
    uid = user["id"]
    tz = tz_of(get_settings(db, uid))
    rnd = random.Random(42)
    made = 0
    now_local = utc_now().astimezone(tz)
    pool = [t for t in _SEED for _ in range(t[5])]
    for back in (0, 1):
        first = (now_local.replace(day=1) - timedelta(days=1)).replace(day=1) if back else now_local.replace(day=1)
        last_day = now_local.day if not back else (now_local.replace(day=1) - timedelta(days=1)).day
        n = 60 if not back else 48
        for _ in range(n):
            label, cat, merch, lo, hi, _w = rnd.choice(pool)
            day = rnd.randint(1, max(1, last_day))
            when = first.replace(day=day, hour=rnd.randint(8, 21), minute=rnd.randint(0, 59), second=0, microsecond=0)
            if when > now_local:
                when = now_local - timedelta(hours=1)
            amt = rnd.randint(lo, hi) * 100
            create_transaction(db, user, direction="debit", amount_paise=amt, counterparty=merch, occurred_at=iso(when),
                               items=[{"label": label, "amount_paise": amt, "category": cat, "note": None}], transcript=f"{label.lower()}",
                               source="demo", confidence=0.9, remember_merchant=False)
            made += 1
    add_udhaar(db, uid, "Ramesh", "i_lent", 50000, None, "demo")
    set_budget(db, uid, "Food & Dining", 400000)
    return {"transactions_created": made, "note": "Demo data. Use DELETE /api/v1/me/data to wipe."}
