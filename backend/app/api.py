"""HTTP routes (all under /api/v1). Business logic lives in core.py."""
import time
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from . import auth, core, gnani, rules, textutil
from .config import cfg
from .db import get_db
from .errors import ApiError

router = APIRouter(prefix="/api/v1")
Udir = Literal["i_lent", "i_borrowed", "repaid_by_me", "repaid_to_me"]


# ----------------------------------------------------------------- models
class RegisterIn(BaseModel):
    name: Optional[str] = Field(None, max_length=60)


class ParsedIn(BaseModel):
    """Accepts the output of parser/paymentParser.js directly (camelCase) or snake_case."""
    model_config = ConfigDict(populate_by_name=True)
    direction: Literal["debit", "credit"]
    amount: Optional[float] = None
    amount_paise: Optional[int] = None
    counterparty: Optional[str] = None
    counterparty_is_person: Optional[bool] = Field(None, alias="counterpartyIsPerson")
    upi_ref: Optional[str] = Field(None, alias="upiRef")
    account_last4: Optional[str] = Field(None, alias="accountLast4")
    instrument: Optional[str] = None
    occurred_at: Optional[str] = Field(None, alias="occurredAt")
    dedupe_key: Optional[str] = Field(None, alias="dedupeKey")


class IngestIn(BaseModel):
    raw_text: Optional[str] = Field(None, max_length=1000, description="SMS/notification text. Parsed in memory, NEVER stored.")
    parsed: Optional[ParsedIn] = Field(None, description="Pre-parsed on the phone (max privacy). Takes precedence over raw_text.")
    source: Literal["sms", "notification", "manual_paste", "simulated"] = "notification"
    received_at: Optional[str] = None
    package: Optional[str] = None


class ItemIn(BaseModel):
    label: str = Field(..., max_length=60)
    amount_paise: int = Field(..., gt=0)
    category: str
    note: Optional[str] = Field(None, max_length=200)


class UdhaarHint(BaseModel):
    person: Optional[str] = None
    direction: Udir


class ConfirmIn(BaseModel):
    items: list[ItemIn]
    transcript: Optional[str] = Field(None, max_length=500)
    language: Optional[str] = None
    confidence: Optional[float] = None
    needs_review: bool = False
    remember_merchant: bool = True
    udhaar: Optional[UdhaarHint] = None


class TxnIn(ConfirmIn):
    direction: Literal["debit", "credit"] = "debit"
    amount_paise: int = Field(..., gt=0)
    counterparty: Optional[str] = Field(None, max_length=80)
    occurred_at: Optional[str] = None
    instrument: Optional[str] = None
    source: Literal["voice", "text", "manual"] = "voice"


class TxnPatch(BaseModel):
    items: Optional[list[ItemIn]] = None
    user_note: Optional[str] = Field(None, max_length=500)
    remember_merchant: bool = True


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    amount_paise: Optional[int] = Field(None, gt=0, description="Cash entries only")


class UdhaarIn(BaseModel):
    person: str
    direction: Literal["i_lent", "i_borrowed"]
    amount_paise: int = Field(..., gt=0)
    due_date: Optional[str] = None
    note: Optional[str] = Field(None, max_length=200)


class SettleIn(BaseModel):
    amount_paise: Optional[int] = Field(None, gt=0)


class BudgetIn(BaseModel):
    category: Optional[str] = Field(None, description="null = overall monthly budget")
    limit_paise: int = Field(..., gt=0)


class SettingsIn(BaseModel):
    language_hint: Optional[str] = None
    min_prompt_paise: Optional[int] = None
    max_prompts_per_day: Optional[int] = None
    tts_enabled: Optional[bool] = None
    tz: Optional[str] = None
    digest_time: Optional[str] = None
    ui_lang: Optional[str] = None


class TTSIn(BaseModel):
    text: Optional[str] = Field(None, max_length=300)
    transaction_id: Optional[int] = None


class MerchantIn(BaseModel):
    merchant: str = Field(..., max_length=80)
    category: str
    auto_apply: bool = True


class SimIn(BaseModel):
    preset: Optional[int] = None
    raw_text: Optional[str] = None


# ----------------------------------------------------------------- public
@router.get("/health", tags=["meta"])
def health():
    return {"ok": True, "gnani_configured": bool(cfg.gnani_key), "gnani_mock": cfg.gnani_mock, "stt_model": cfg.stt_model,
            "llm": "gemini" if cfg.llm_enabled else "rules", "demo_enabled": cfg.demo_enabled}


@router.get("/categories", tags=["meta"])
def categories():
    return {"spend": [c for c in rules.CATEGORIES if c not in rules.NON_SPEND], "special": ["Lent (udhaar)", "Repaid", "Income"],
            "all": rules.CATEGORIES}


@router.post("/auth/register", tags=["auth"])
def register(body: RegisterIn, x_registration_key: Optional[str] = Header(None), db=Depends(get_db)):
    if cfg.registration_key and x_registration_key != cfg.registration_key:
        raise ApiError(403, "registration_closed", "A valid X-Registration-Key header is required.")
    uid, token = auth.create_user(db, body.name)
    return {"user_id": uid, "token": token, "note": "Store this token on the device; it is shown only once."}


# ----------------------------------------------------------------- account
@router.get("/me", tags=["account"])
def me(user=Depends(auth.current_user), db=Depends(get_db)):
    return {**user, "settings": core.settings_out(core.get_settings(db, user["id"]))}


@router.get("/settings", tags=["account"])
def get_settings(user=Depends(auth.current_user), db=Depends(get_db)):
    return core.settings_out(core.get_settings(db, user["id"]))


@router.put("/settings", tags=["account"])
def put_settings(body: SettingsIn, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.update_settings(db, user["id"], body.model_dump(exclude_none=True))


@router.delete("/me/data", tags=["account"])
def delete_my_data(user=Depends(auth.current_user), db=Depends(get_db)):
    core.wipe_data(db, user["id"])
    return {"deleted": True}


@router.delete("/me", tags=["account"])
def delete_me(user=Depends(auth.current_user), db=Depends(get_db)):
    core.delete_account(db, user["id"])
    return {"deleted": True}


@router.get("/diagnostics", tags=["account"])
def diagnostics(user=Depends(auth.current_user), db=Depends(get_db)):
    """Gnani call counts + latencies (use to measure how fast credits are being spent) and your last 20 API calls."""
    return core.diagnostics(db, user["id"])


# ----------------------------------------------------------------- captures (detected payments)
@router.post("/captures/ingest", tags=["captures"])
def ingest(body: IngestIn, user=Depends(auth.current_user), db=Depends(get_db)):
    """A payment notification/SMS arrived. Dedupes, auto-saves small/learned merchants, otherwise returns a prompt to show."""
    if not body.raw_text and not body.parsed:
        raise ApiError(422, "nothing_to_ingest", "Send raw_text or parsed")
    parsed = body.parsed.model_dump(exclude_none=True) if body.parsed else None
    return core.ingest(db, user, raw_text=None if parsed else body.raw_text, parsed=parsed, source=body.source,
                       received_at=body.received_at, package=body.package)


@router.get("/captures", tags=["captures"])
def list_captures(status: Literal["pending", "answered", "skipped", "auto_categorized", "all"] = "pending",
                  user=Depends(auth.current_user), db=Depends(get_db)):
    return {"items": core.list_captures(db, user["id"], status)}


@router.get("/captures/digest", tags=["captures"])
def digest(user=Depends(auth.current_user), db=Depends(get_db)):
    """Evening digest: pending payments (largest first) + udhaar reminders."""
    return core.digest(db, user["id"])


@router.get("/captures/{cid}", tags=["captures"])
def get_capture(cid: int, user=Depends(auth.current_user), db=Depends(get_db)):
    """One detected payment (used when the user taps a prompt notification)."""
    return core.cap_out(core.get_capture(db, user["id"], cid))


@router.post("/captures/{cid}/skip", tags=["captures"])
def skip(cid: int, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.skip_capture(db, user["id"], cid)


async def _transcribe(db, user, audio: UploadFile, language_hint, mock_transcript) -> dict:
    data = await audio.read()
    if not data:
        raise ApiError(400, "empty_audio", "The audio clip was empty.")
    if len(data) > cfg.max_audio_bytes:
        raise ApiError(413, "audio_too_large", f"Max {cfg.max_audio_bytes} bytes (clips are limited to 30 s).")
    hint = language_hint or core.get_settings(db, user["id"])["language_hint"]
    t0 = time.time()
    try:
        res = await gnani.stt(data, audio.filename, audio.content_type, hint, keyterms=core.keyterms(db, user["id"]),
                              mock_transcript=mock_transcript)
        core.log_gnani(db, user["id"], "stt", True, int((time.time() - t0) * 1000), len(data))
        return res
    except ApiError:
        core.log_gnani(db, user["id"], "stt", False, int((time.time() - t0) * 1000), len(data))
        raise


async def _voice_response(db, user, stt_res, **ctx):
    t = stt_res["transcript"]
    base = {"transcript": t, "language": stt_res.get("language"), "stt_provider": stt_res.get("provider"),
            "stt_latency_s": stt_res.get("latency_s"), "empty": not t}
    if not t:
        return {**base, "draft": None, "message": "Couldn't hear that — try again or type it."}
    return {**base, "draft": await core.build_draft(db, user["id"], t, stt_res.get("language"), **ctx)}


@router.post("/captures/{cid}/voice", tags=["voice"])
async def capture_voice(cid: int, audio: UploadFile = File(...), language_hint: Optional[str] = Form(None),
                        mock_transcript: Optional[str] = Form(None), user=Depends(auth.gnani_user), db=Depends(get_db)):
    """Audio (<=30 s) -> Gnani Prisma transcript -> structured DRAFT. Nothing is saved until /confirm."""
    cap = core.get_capture(db, user["id"], cid)
    if cap["status"] == "answered":
        raise ApiError(409, "already_answered", "This payment already has a note", transaction_id=cap["transaction_id"])
    stt_res = await _transcribe(db, user, audio, language_hint, mock_transcript)
    return await _voice_response(db, user, stt_res, amount_paise=cap["amount_paise"], counterparty=cap["counterparty"],
                                 is_person=None if cap["counterparty_is_person"] is None else bool(cap["counterparty_is_person"]),
                                 direction=cap["direction"])


@router.post("/captures/{cid}/note", tags=["voice"])
async def capture_note(cid: int, body: NoteIn, user=Depends(auth.current_user), db=Depends(get_db)):
    """Typed fallback (STT failed / user prefers typing). Same draft format as /voice."""
    cap = core.get_capture(db, user["id"], cid)
    if cap["status"] == "answered":
        raise ApiError(409, "already_answered", "This payment already has a note", transaction_id=cap["transaction_id"])
    d = await core.build_draft(db, user["id"], body.text, None, amount_paise=cap["amount_paise"], counterparty=cap["counterparty"],
                               is_person=None if cap["counterparty_is_person"] is None else bool(cap["counterparty_is_person"]),
                               direction=cap["direction"])
    return {"transcript": body.text, "empty": False, "draft": d}


@router.post("/captures/{cid}/confirm", tags=["captures"])
def capture_confirm(cid: int, body: ConfirmIn, idempotency_key: Optional[str] = Header(None),
                    user=Depends(auth.current_user), db=Depends(get_db)):
    """Save the (possibly edited) draft. Learns the merchant, updates udhaar, returns budget alerts + text to speak."""
    prev = core.idem_get(db, user["id"], idempotency_key)
    if prev:
        return prev
    res = core.create_transaction(db, user, capture_id=cid, items=[i.model_dump() for i in body.items], transcript=body.transcript,
                                  language=body.language, confidence=body.confidence, needs_review=body.needs_review,
                                  source="voice", udhaar_hint=body.udhaar.model_dump() if body.udhaar else None,
                                  remember_merchant=body.remember_merchant)
    core.idem_put(db, user["id"], idempotency_key, res)
    return res


# ----------------------------------------------------------------- cash / manual entries
@router.post("/cash/voice", tags=["voice"])
async def cash_voice(audio: UploadFile = File(...), language_hint: Optional[str] = Form(None),
                     mock_transcript: Optional[str] = Form(None), user=Depends(auth.gnani_user), db=Depends(get_db)):
    """'chai bees rupaye' -> draft with the amount taken from speech. If draft.amount_paise is null, ask 'How much?'."""
    stt_res = await _transcribe(db, user, audio, language_hint, mock_transcript)
    return await _voice_response(db, user, stt_res, direction="debit")


@router.post("/cash/note", tags=["voice"])
async def cash_note(body: NoteIn, user=Depends(auth.current_user), db=Depends(get_db)):
    d = await core.build_draft(db, user["id"], body.text, None, amount_paise=body.amount_paise, direction="debit")
    return {"transcript": body.text, "empty": False, "draft": d}


@router.post("/transactions", tags=["transactions"])
def create_tx(body: TxnIn, idempotency_key: Optional[str] = Header(None), user=Depends(auth.current_user), db=Depends(get_db)):
    """Create an entry directly (cash, manual, or credit). For detected payments use /captures/{id}/confirm."""
    prev = core.idem_get(db, user["id"], idempotency_key)
    if prev:
        return prev
    res = core.create_transaction(db, user, direction=body.direction, amount_paise=body.amount_paise, counterparty=body.counterparty,
                                  occurred_at=body.occurred_at, instrument=body.instrument or "cash", items=[i.model_dump() for i in body.items],
                                  transcript=body.transcript, language=body.language, confidence=body.confidence,
                                  needs_review=body.needs_review, source=body.source,
                                  udhaar_hint=body.udhaar.model_dump() if body.udhaar else None, remember_merchant=body.remember_merchant)
    core.idem_put(db, user["id"], idempotency_key, res)
    return res


@router.get("/transactions", tags=["transactions"])
def list_tx(month: Optional[str] = None, category: Optional[str] = None, q: Optional[str] = None,
            direction: Optional[Literal["debit", "credit"]] = None, needs_review: Optional[bool] = None,
            limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), user=Depends(auth.current_user), db=Depends(get_db)):
    return core.list_transactions(db, user["id"], month=month, category=category, q=q, direction=direction,
                                  needs_review=needs_review, limit=limit, offset=offset)


@router.get("/review", tags=["transactions"])
def review_queue(user=Depends(auth.current_user), db=Depends(get_db)):
    """Low-confidence / auto-categorized entries waiting for a 1-tap fix."""
    return core.list_transactions(db, user["id"], needs_review=True, limit=100)


@router.get("/transactions/{tid}", tags=["transactions"])
def get_tx(tid: int, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.tx_out(db, core.get_tx(db, user["id"], tid))


@router.patch("/transactions/{tid}", tags=["transactions"])
def patch_tx(tid: int, body: TxnPatch, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.update_transaction(db, user, tid, [i.model_dump() for i in body.items] if body.items is not None else None,
                                   body.user_note, body.remember_merchant)


@router.delete("/transactions/{tid}", tags=["transactions"])
def del_tx(tid: int, user=Depends(auth.current_user), db=Depends(get_db)):
    core.delete_transaction(db, user["id"], tid)
    return {"deleted": True}


# ----------------------------------------------------------------- udhaar
@router.get("/udhaar", tags=["udhaar"])
def udhaar(status: Literal["open", "settled", "all"] = "open", user=Depends(auth.current_user), db=Depends(get_db)):
    return core.list_udhaar(db, user["id"], status)


@router.post("/udhaar", tags=["udhaar"])
def udhaar_add(body: UdhaarIn, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.add_udhaar(db, user["id"], body.person, body.direction, body.amount_paise, body.due_date, body.note)


@router.post("/udhaar/{uid_}/settle", tags=["udhaar"])
def udhaar_settle(uid_: int, body: SettleIn, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.settle_udhaar(db, user["id"], uid_, body.amount_paise)


@router.delete("/udhaar/{uid_}", tags=["udhaar"])
def udhaar_delete(uid_: int, user=Depends(auth.current_user), db=Depends(get_db)):
    core.delete_udhaar(db, user["id"], uid_)
    return {"deleted": True}


@router.get("/udhaar/reminders", tags=["udhaar"])
def udhaar_reminders(user=Depends(auth.current_user), db=Depends(get_db)):
    return {"items": core.udhaar_reminders(db, user["id"])}


# ----------------------------------------------------------------- learned shops
@router.get("/merchants", tags=["learning"])
def merchants(user=Depends(auth.current_user), db=Depends(get_db)):
    """Shops the app has learned. auto_apply=true means payments there are categorised without asking."""
    return {"items": core.list_merchants(db, user["id"])}


@router.put("/merchants", tags=["learning"])
def merchant_put(body: MerchantIn, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.set_merchant(db, user["id"], body.merchant, body.category, body.auto_apply)


@router.delete("/merchants", tags=["learning"])
def merchant_del(merchant: str, user=Depends(auth.current_user), db=Depends(get_db)):
    core.delete_merchant(db, user["id"], merchant)
    return {"deleted": True}


# ----------------------------------------------------------------- budgets
@router.get("/budgets", tags=["budgets"])
def budgets(month: Optional[str] = None, user=Depends(auth.current_user), db=Depends(get_db)):
    return {"items": core.budget_status(db, user["id"], month)}


@router.put("/budgets", tags=["budgets"])
def budget_put(body: BudgetIn, user=Depends(auth.current_user), db=Depends(get_db)):
    return core.set_budget(db, user["id"], body.category, body.limit_paise)


@router.delete("/budgets", tags=["budgets"])
def budget_del(category: Optional[str] = None, user=Depends(auth.current_user), db=Depends(get_db)):
    core.delete_budget(db, user["id"], category)
    return {"deleted": True}


# ----------------------------------------------------------------- reports / export
@router.get("/reports/monthly", tags=["reports"])
async def monthly(month: Optional[str] = None, refresh: bool = False, language: str = "en",
                  user=Depends(auth.current_user), db=Depends(get_db)):
    """Totals, category split, top merchants, daily bars, month-over-month, budgets, udhaar, 3 neutral insights."""
    return await core.monthly_report(db, user, month, refresh, language[:5])


@router.get("/reports/months", tags=["reports"])
def months(user=Depends(auth.current_user), db=Depends(get_db)):
    return {"months": core.report_months(db, user["id"])}


@router.get("/export/csv", tags=["reports"])
def export(month: Optional[str] = None, user=Depends(auth.current_user), db=Depends(get_db)):
    return Response(core.export_csv(db, user["id"], month), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="hisaabbol-{month or "all"}.csv"'})


@router.get("/export/json", tags=["reports"])
def export_json(user=Depends(auth.current_user), db=Depends(get_db)):
    """Full backup of your data (transactions, udhaar, budgets, learned shops, settings)."""
    return Response(__import__("json").dumps(core.export_json(db, user["id"]), ensure_ascii=False, indent=1), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="hisaabbol-backup.json"'})


# ----------------------------------------------------------------- text-to-speech
@router.post("/tts", tags=["voice"])
async def tts(body: TTSIn, user=Depends(auth.gnani_user), db=Depends(get_db)):
    """Gnani Timbre. Pass text, or a transaction_id to speak its confirmation. Amounts are sent as words."""
    s = core.get_settings(db, user["id"])
    if s["tts_enabled"] != "1":
        raise ApiError(409, "tts_disabled", "Voice replies are turned off in settings.")
    text = body.text
    if body.transaction_id:
        t = core.tx_out(db, core.get_tx(db, user["id"], body.transaction_id))
        purpose = " and ".join(i["label"] for i in t["items"]) if len(t["items"]) > 1 else t["items"][0]["label"]
        text = core.confirmation_text("hi" if s["language_hint"].startswith("hi") else "en",
                                      t["amount_paise"], purpose, t["direction"],
                                      core.udhaar_for_transaction(db, user["id"], body.transaction_id))
    if not text:
        raise ApiError(422, "text_required", "Send text or transaction_id")
    lang = "hi-en" if s["language_hint"].startswith("hi") else "en-IN"
    t0 = time.time()
    try:
        audio, ctype = await gnani.tts(text, lang)
        core.log_gnani(db, user["id"], "tts", True, int((time.time() - t0) * 1000), chars=len(text))
    except ApiError:
        core.log_gnani(db, user["id"], "tts", False, int((time.time() - t0) * 1000), chars=len(text))
        raise
    return Response(audio, media_type=ctype)


# ----------------------------------------------------------------- demo tools
def _demo_on():
    if not cfg.demo_enabled:
        raise ApiError(404, "not_found", "Demo tools are disabled (DEMO_ENABLED=false).")


@router.get("/demo/presets", tags=["demo"])
def presets(user=Depends(auth.current_user)):
    _demo_on()
    return {"items": [{"id": i, "name": p["name"]} for i, p in enumerate(core.SIM_PRESETS)]}


@router.post("/demo/simulate", tags=["demo"])
def simulate(body: SimIn, user=Depends(auth.current_user), db=Depends(get_db)):
    """Feeds a realistic bank SMS / UPI notification through the exact same ingest pipeline as a real one."""
    _demo_on()
    tz = core.tz_of(core.get_settings(db, user["id"]))
    if body.raw_text:
        text = body.raw_text
    elif body.preset is not None and 0 <= body.preset < len(core.SIM_PRESETS):
        text = core.render_preset(body.preset, tz)
    else:
        raise ApiError(422, "bad_request", "Send preset (index) or raw_text")
    return core.ingest(db, user, raw_text=text, source="simulated")


@router.post("/demo/seed-month", tags=["demo"])
def seed(user=Depends(auth.current_user), db=Depends(get_db)):
    _demo_on()
    return core.seed_month(db, user)
