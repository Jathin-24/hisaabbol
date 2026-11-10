"""Python port of parser/paymentParser.js (same fixtures). Extracts a payment from a bank SMS / UPI-app
notification. The raw text is processed in memory and discarded — never stored or logged."""
import re

_AMOUNT_RES = [
    re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)", re.I),
    re.compile(r"(?:debited|credited|spent|paid|sent|withdrawn)\s+(?:by|for|of)\s+([\d,]+(?:\.\d{1,2})?)", re.I),
]
_DEBIT = re.compile(r"\b(debited|debit|sent|spent|paid|payment of|withdrawn|purchase|purchased|transferred|trf to|txn of)\b", re.I)
_CREDIT = re.compile(r"\b(credited|credit|received|deposited|refund(?:ed)?)\b", re.I)
_REJECT = re.compile(
    r"\b(otp|one[- ]time|verification code|cashback|offer|offers|get up to|voucher|coupon|reward|apply now|pre-?approved|"
    r"credit limit|available limit|avl\.? ?(?:bal|limit)|statement|due (?:on|by|date)|min(?:imum)? due|emi (?:due|reminder)|"
    r"will be debited|has been requested|collect request|requested money|is requesting|failed|declined|reversed|"
    r"unsuccessful|insufficient)\b", re.I)
_CP = [
    re.compile(r"UPI/(?:P2M|P2A|P2P)/\d{6,}/(.+?)(?=\s+(?:SMS|If|Not|Call)\b|\s+-\s|$)", re.I),
    re.compile(r"\btrf to\s+(.+?)\s+(?:ref(?:no)?|upi)\b", re.I),
    re.compile(r"\bto\s+(?:VPA\s+)?([A-Za-z0-9&@._' -]{2,40}?)\s+(?:on|ref|upi|via|using)\b", re.I),
    re.compile(r";\s*([A-Za-z0-9&@._' -]{2,40}?)\s+credited\b", re.I),
    re.compile(r"\bat\s+([A-Za-z0-9&@._' -]{2,40}?)\s+on\b", re.I),
    re.compile(r"\b(?:paid|sent)\s+(?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d{1,2})?\s+to\s+([A-Za-z0-9&@._' -]{2,40})", re.I),
    re.compile(r"\bpaid to\s+([A-Za-z0-9&@._' -]{2,40})", re.I),
    re.compile(r"\bfrom\s+([A-Za-z0-9&@._' -]{2,40}?)\s+(?:on|ref|upi|via)\b", re.I),
    re.compile(r"\bby\s+([A-Za-z][A-Za-z0-9&@._' -]{2,40}?)\s+(?:\(|ref|upi)", re.I),
]
_BIZ = re.compile(
    r"\b(store|stores|mart|foods?|restaurant|cafe|hotel|bakery|pharmacy|medical|traders?|enterprises?|services?|pvt|ltd|llp|"
    r"mobility|retail|super|market|kirana|dairy|sweets|fuel|petrol|gas|bpcl|iocl|hpcl|irctc|zomato|swiggy|amazon|flipkart|"
    r"uber|ola|rapido|blinkit|zepto|bigbasket|jio|airtel|bsnl|paytm|phonepe|gpay|netflix|spotify|bookmyshow|tea|stall)\b", re.I)


def looks_like_person(name: str) -> bool:
    if re.fullmatch(r"\d{10}", name) or re.match(r"^\d{10}@", name):
        return True
    if _BIZ.search(name):
        return False
    words = name.strip().split()
    return 1 <= len(words) <= 3 and all(re.fullmatch(r"[A-Za-z.]+", w) for w in words)


def _clean(n):
    if not n:
        return None
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"[.,;:-]+$", "", n).strip()
    if re.match(r"^(a/c|acct|account|your|mobile|bank|xx|x\d)", n, re.I):
        return None
    if "@" in n:
        n = n.split("@")[0]
    return n if len(n) >= 2 else None


def _instrument(t, ref):
    if re.search(r"\bcard\b", t, re.I): return "card"
    if re.search(r"\bupi\b|vpa|@[a-z]{2,}", t, re.I): return "upi"
    if ref and re.search(r"\b(sent|trf|debited)\b", t, re.I): return "upi"
    if re.search(r"\batm\b|cash withdrawal", t, re.I): return "atm"
    return "bank"


def _normalize_text(value: str) -> str:
    if not value:
        return value
    value = value.replace("â‚¹", "₹").replace("Â₹", "₹").replace("\ufeff", "")
    return re.sub(r"\s+", " ", value).strip()


def parse_payment(text: str, source: str = "sms", received_at: str | None = None) -> dict | None:
    if not text or not isinstance(text, str):
        return None
    t = _normalize_text(text)
    has_d, has_c = bool(_DEBIT.search(t)), bool(_CREDIT.search(t))
    if not has_d and not has_c:
        return None
    if re.search(r"\b(otp|one[- ]time|verification code)\b", t, re.I) or _REJECT.search(t):
        return None
    amount = None
    for rx in _AMOUNT_RES:
        m = rx.search(t)
        if m:
            amount = round(float(m.group(1).replace(",", "")), 2)
            break
    if not amount or amount <= 0:
        return None
    dm, cm = _DEBIT.search(t), _CREDIT.search(t)
    direction = "debit" if has_d and (not has_c or dm.start() <= cm.start()) else "credit"
    if has_d and has_c and re.search(r"debited", t, re.I) and re.search(r";\s*[^;]+credited", t, re.I):
        direction = "debit"
    if re.search(r"\bpaid\b.*\bto\b", t, re.I) and not re.search(r"\breceived\b", t, re.I):
        direction = "debit"
    cp = None
    for rx in _CP:
        m = rx.search(t)
        if m:
            cp = _clean(m.group(1))
            if cp:
                break
    m = re.search(r"\b(\d{12})\b", t)
    ref = m.group(1) if m else None
    m = (re.search(r"(?:a/c|acct|account|card|ac)\.?\s*(?:no\.?)?\s*[xX*]*\s*(\d{3,4})\b", t, re.I)
         or re.search(r"[xX*]{2,}(\d{3,4})\b", t))
    acct = m.group(1) if m else None
    return {
        "direction": direction, "amount": amount, "amount_paise": int(round(amount * 100)), "counterparty": cp,
        "counterparty_is_person": looks_like_person(cp) if cp else None, "upi_ref": ref, "account_last4": acct,
        "instrument": _instrument(t, ref), "source": source, "occurred_at": received_at,
    }
