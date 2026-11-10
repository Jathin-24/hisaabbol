"""Deterministic categorizer / understander — works with no LLM and is the fallback when the LLM fails."""
import re

from .textutil import clean_expense_label, extract_amounts

CATEGORIES = [
    "Food & Dining", "Groceries", "Transport", "Fuel", "Bills & Recharge", "Shopping", "Health", "Entertainment",
    "Education", "Rent & Home", "Personal Care", "Travel", "Gifts & Donations", "Lent (udhaar)", "Repaid",
    "Family & Friends", "Other", "Income",
]
SPEND_CATEGORIES = [c for c in CATEGORIES if c != "Income"]
NON_SPEND = {"Lent (udhaar)", "Repaid", "Income"}

KEYWORDS = {
    "Food & Dining": ["chai", "tea", "coffee", "biryani", "lunch", "dinner", "breakfast", "snack", "pizza", "burger", "restaurant",
                      "cafe", "khana", "nashta", "samosa", "zomato", "swiggy", "mess", "canteen", "juice", "ice cream", "tiffin",
                      "చాయ్", "భోజనం", "खाना", "नाश्ता", "चाय", "टिफिन"],
    "Groceries": ["sabzi", "sabji", "vegetables", "veggies", "fruits", "milk", "doodh", "kirana", "grocery", "atta", "rice", "dal",
                  "blinkit", "zepto", "bigbasket", "राशन", "सब्जी", "दूध", "కూరగాయలు", "పాలు"],
    "Transport": ["auto", "cab", "uber", "ola", "rapido", "metro", "bus", "train", "bike taxi", "ऑटो", "బస్"],
    "Fuel": ["petrol", "diesel", "fuel", "cng", "पेट्रोल", "డీజిల్", "పెట్రోల్"],
    "Bills & Recharge": ["recharge", "electricity", "bijli", "wifi", "broadband", "gas cylinder", "bill", "dth", "jio", "airtel",
                         "postpaid", "बिजली", "रिचार्ज"],
    "Shopping": ["shirt", "shoes", "clothes", "amazon", "flipkart", "myntra", "dress", "bag", "gadget", "earphones", "कपड़े"],
    "Health": ["medicine", "doctor", "pharmacy", "hospital", "tablet", "dawai", "medical", "दवाई", "మందులు"],
    "Entertainment": ["movie", "netflix", "spotify", "game", "concert", "bookmyshow", "cinema", "सिनेमा"],
    "Education": ["fees", "fee", "book", "course", "tuition", "exam", "stationery", "xerox", "print"],
    "Rent & Home": ["rent", "maintenance", "furniture", "repair", "plumber", "किराया"],
    "Personal Care": ["haircut", "salon", "barber", "soap", "shampoo"],
    "Travel": ["flight", "hotel", "trip", "irctc", "bus pass", "luggage"],
    "Gifts & Donations": ["gift", "donation", "temple", "birthday", "dakshina", "daan"],
}
_WORDISH = re.compile(r"[a-z]")


def _kw_hit(word: str, text: str) -> bool:
    if _WORDISH.match(word[0]):
        return re.search(rf"\b{re.escape(word)}\b", text) is not None
    return word in text


def categorize(text: str, counterparty: str | None = None, is_person: bool | None = None):
    t = (text or "").lower()
    best, hits = None, 0
    for cat, words in KEYWORDS.items():
        n = sum(1 for w in words if _kw_hit(w, t))
        if n > hits:
            best, hits = cat, n
    if best:
        return best, min(0.5 + 0.15 * hits, 0.9)
    cp = (counterparty or "").lower()
    if cp:
        for cat, words in KEYWORDS.items():
            if any(_kw_hit(w, cp) for w in words):
                return cat, 0.6
    if is_person:
        return "Family & Friends", 0.4
    return "Other", 0.2


_LEND = re.compile(r"\b(udhaar|udhar|lent|loan|borrow(?:ed)?|उधार|అప్పు)\b", re.I)
_REPAY = re.compile(r"\b(returned|repaid|wapas|paid back|lauta\w*|वापस|తిరిగి)\b", re.I)
_NAME = r"([A-Za-z\u0900-\u097F\u0C00-\u0C7F]{2,20})"


def detect_udhaar(text: str, direction: str, counterparty: str | None):
    """Returns (category|None, {'person','direction'}|None). Hinglish semantics:
    'X ne udhaar liya' = X borrowed (I lent) · 'X se udhaar liya' = I borrowed · 'X ko udhaar diya' = I lent ·
    'X ne udhaar diya' = X lent me."""
    t = text or ""
    low = t.lower()
    person = None
    d = None
    if _REPAY.search(low):
        m = re.search(rf"{_NAME}\s+ne\b.*\b(wapas|returned|repaid|lauta\w*|वापस)", t, re.I)
        if m:
            person, d = m.group(1), "repaid_to_me"
        else:
            m = re.search(rf"{_NAME}\s+(?:ko|ka|को)\b", t, re.I) or re.search(rf"(?:to|returned to)\s+{_NAME}", t, re.I)
            person = m.group(1) if m else None
            d = "repaid_by_me" if direction == "debit" else "repaid_to_me"
        return "Repaid", {"person": (person or counterparty), "direction": d}
    if _LEND.search(low):
        pats = [
            (rf"{_NAME}\s+ne\b.*(?:udhaar|udhar|उधार|loan).*\b(?:liya|liye|लिया)", "i_lent"),
            (rf"{_NAME}\s+se\b.*(?:udhaar|udhar|उधार|loan).*\b(?:liya|liye|लिया)", "i_borrowed"),
            (rf"{_NAME}\s+ko\b.*(?:udhaar|udhar|उधार|loan|diya|diye|दिया)", "i_lent"),
            (rf"{_NAME}\s+ne\b.*(?:udhaar|udhar|उधार|loan).*\b(?:diya|diye|दिया)", "i_borrowed"),
            (rf"\blent\b.*\bto\s+{_NAME}", "i_lent"),
            (rf"\bborrowed\b.*\bfrom\s+{_NAME}", "i_borrowed"),
            (rf"{_NAME}\s+gave me", "i_borrowed"),
        ]
        for pat, dr in pats:
            m = re.search(pat, t, re.I)
            if m:
                person, d = m.group(1), dr
                break
        if not d:
            d = "i_lent" if direction == "debit" else "i_borrowed"
        return "Lent (udhaar)", {"person": (person or counterparty), "direction": d}
    return None, None


def understand_rules(transcript: str, amount_paise: int | None, counterparty: str | None,
                     is_person: bool | None, direction: str = "debit") -> dict:
    text = (transcript or "").strip()
    udh_cat, udh = detect_udhaar(text, direction, counterparty)
    amounts = extract_amounts(text)
    segs = [s for s in re.split(r",|\+|\band\b|\baur\b|\bphir\b", text, flags=re.I) if s.strip()]
    with_amt = [(s, extract_amounts(s)) for s in segs]
    with_amt = [(s, a[-1]) for s, a in with_amt if a]
    items = []
    if amount_paise and len(with_amt) >= 2 and sum(a for _, a in with_amt) == amount_paise:
        for s, a in with_amt:
            cat, _ = categorize(s, counterparty, is_person)
            items.append({"label": clean_expense_label(s, counterparty or "Item"), "amount_paise": a, "category": cat, "note": None})
        conf = 0.7
    else:
        total = amount_paise or (amounts[-1] if amounts else None)
        cat, conf = (udh_cat, 0.75) if udh_cat else categorize(text, counterparty, is_person)
        items.append({"label": clean_expense_label(text, counterparty or "Expense"), "amount_paise": total, "category": cat, "note": None})
    follow = None
    if items[0]["amount_paise"] is None:
        follow = "How much was it?"
    elif conf < 0.5:
        follow = "Which category fits best?"
    return {"items": items, "udhaar": udh, "confidence": conf, "follow_up_question": follow, "provider": "rules"}
