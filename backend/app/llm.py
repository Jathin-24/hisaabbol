"""Turns a spoken note into structured items, and phrases report insights. Providers: gemini | rules.
The LLM never does arithmetic that matters: amounts are validated/repaired in core.normalize_draft()."""
import json

import httpx

from . import rules
from .config import cfg
from .textutil import clean_expense_label

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a mock

UNDERSTAND_SYSTEM = """You turn a spoken note about ONE payment into JSON for an Indian expense tracker.
The user speaks Hindi, Telugu, Tamil, English or a mix. Return ONLY JSON:
{"items":[{"label":str,"amount_rupees":number|null,"category":str,"note":str|null}],
 "udhaar":{"person":str,"direction":"i_lent"|"i_borrowed"|"repaid_by_me"|"repaid_to_me"}|null,
 "confidence":0..1,"follow_up_question":str|null}
Rules: category MUST be one of the provided categories. Labels must name only the actual item or purpose: omit narration such as
"I paid", "spent", "I ate", and all spoken amounts/currency or time context such as "in the morning". For example,
"I ate Tiffin for 100 rupees in the morning" has label "Tiffin", not "Morning Tiffin" or "Ate Tiffin Morning".
If the user says only when they spent and gives no item/purpose, use label "Expense" and ask a short follow-up.
If the purpose is unclear, use label "Expense", low confidence, and a short follow-up question. If the user splits the payment
("500 food, 200 gift") return several items whose amounts sum to the payment. Never invent amounts: if a payment amount is given and there is one item, use it.
Hinglish: 'X ne udhaar liya' = X borrowed from me (i_lent); 'X se udhaar liya' = I borrowed (i_borrowed); 'X ko udhaar diya' = i_lent;
'X ne udhaar diya' = i_borrowed. Loans -> category 'Lent (udhaar)'; repayments -> 'Repaid'.
If unsure (confidence<0.5) add a SHORT follow_up_question in the user's language. Label = 2-5 words in English."""


async def _gemini_json(prompt: str, temperature: float, timeout: float = 8) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    async with httpx.AsyncClient(timeout=timeout, transport=_transport) as c:
        r = await c.post(url, params={"key": cfg.gemini_key},
                         json={"contents": [{"parts": [{"text": prompt}]}],
                               "generationConfig": {"responseMimeType": "application/json", "temperature": temperature,
                                                    "maxOutputTokens": 256}})
    r.raise_for_status()
    return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])


async def understand(transcript: str, amount_paise: int | None, counterparty: str | None, is_person: bool | None,
                     direction: str, merchant_rules: dict[str, str], language: str) -> dict:
    if cfg.llm_enabled:
        try:
            cats = rules.SPEND_CATEGORIES if direction == "debit" else rules.CATEGORIES
            prompt = (f"{UNDERSTAND_SYSTEM}\n\nCategories: {json.dumps(cats)}\nLearned merchant rules: {json.dumps(merchant_rules)}\n"
                      f"Payment: {json.dumps({'direction': direction, 'amount_rupees': (amount_paise / 100) if amount_paise else None, 'counterparty': counterparty, 'is_person': is_person})}\n"
                      f"User said: {transcript!r}\nUser language preference: {language}")
            out = await _gemini_json(prompt, 0.1, timeout=8)
            items = []
            for it in out.get("items", []):
                a = it.get("amount_rupees")
                label = clean_expense_label(str(it.get("label") or ""), counterparty or "Expense")
                items.append({"label": label[:60],
                              "amount_paise": int(round(float(a) * 100)) if a is not None else None,
                              "category": it.get("category") if it.get("category") in rules.CATEGORIES else "Other",
                              "note": it.get("note")})
            if items:
                u = out.get("udhaar")
                if not (isinstance(u, dict) and u.get("direction") in ("i_lent", "i_borrowed", "repaid_by_me", "repaid_to_me")):
                    u = None
                return {"items": items, "udhaar": u, "confidence": float(out.get("confidence", 0.6)),
                        "follow_up_question": out.get("follow_up_question"), "provider": "gemini"}
        except Exception as e:  # never block the user because an LLM failed
            res = rules.understand_rules(transcript, amount_paise, counterparty, is_person, direction)
            res["provider"] = f"rules(fallback:{type(e).__name__})"
            return res
    return rules.understand_rules(transcript, amount_paise, counterparty, is_person, direction)


async def phrase_insights(facts: list[str], summary_brief: dict, language: str) -> tuple[list[str], str]:
    fallback = facts[:3]
    if not cfg.llm_enabled or not facts:
        return fallback, "rules"
    try:
        prompt = ("Write exactly 3 short, neutral, non-judgmental insights (max 22 words each) for an Indian user's monthly spending, "
                  f"language code '{language}'. Use ONLY facts/numbers given. Never shame; never advise cutting essentials. "
                  f"Return JSON {{\"insights\":[...]}}.\nFacts: {json.dumps(facts)}\nSummary: {json.dumps(summary_brief)}")
        out = await _gemini_json(prompt, 0.3)
        ins = [str(x) for x in out["insights"]][:3]
        return (ins or fallback), "gemini"
    except Exception:
        return fallback, "rules(fallback)"
