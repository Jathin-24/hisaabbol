"""Money formatting, number words, and amount extraction from spoken/typed text (English + Hinglish)."""
import re

_DEV = str.maketrans("०१२३४५६७८९", "0123456789")

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def fmt_inr(paise: int) -> str:
    """Indian digit grouping: 12500000 -> ₹1,25,000 ; 25050 -> ₹250.50"""
    sign = "-" if paise < 0 else ""
    paise = abs(int(paise))
    rupees, p = divmod(paise, 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}₹{s}" + (f".{p:02d}" if p else "")


def _below_1000(n: int) -> str:
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n:
        out.append(_ONES[n] if n < 20 else _TENS[n // 10] + (("-" + _ONES[n % 10]) if n % 10 else ""))
    return " ".join(out)


def num_words_en(n: int) -> str:
    """Indian numbering in words: 125000 -> 'one lakh twenty-five thousand'."""
    if n == 0:
        return "zero"
    parts = []
    for div, name in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand")):
        if n >= div:
            parts.append(_below_1000(n // div) + " " + name)
            n %= div
    if n:
        parts.append(_below_1000(n))
    return " ".join(parts)


def amount_words(paise: int) -> str:
    r, p = divmod(int(paise), 100)
    s = f"{num_words_en(r)} rupees"
    if p:
        s += f" and {num_words_en(p)} paise"
    return s


_WORD_VAL = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4,
    "paanch": 5, "panch": 5, "five": 5, "chhe": 6, "chah": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8, "eight": 8,
    "nau": 9, "nine": 9, "das": 10, "ten": 10, "bees": 20, "twenty": 20, "tees": 30, "thirty": 30,
    "chalis": 40, "forty": 40, "pachas": 50, "fifty": 50, "saath": 60, "sixty": 60, "sattar": 70, "seventy": 70,
    "assi": 80, "eighty": 80, "nabbe": 90, "ninety": 90,
}
_MULT = {"sau": 100, "hundred": 100, "hazaar": 1000, "hazar": 1000, "thousand": 1000, "lakh": 100000, "lac": 100000}


def _words_to_number(tokens: list[str]) -> int | None:
    total, cur, seen = 0, 0, False
    for t in tokens:
        if t in _WORD_VAL:
            cur += _WORD_VAL[t]; seen = True
        elif t in _MULT:
            m = _MULT[t]; seen = True
            if m == 100:
                cur = (cur or 1) * 100
            else:
                total += (cur or 1) * m; cur = 0
        else:
            return None
    return (total + cur) if seen else None


_CUR = r"(?:rs\.?|inr|₹|rupees?|rupaye|rupay|रुपये|रुपए)"
_NUM_RE = re.compile(rf"(?:(?P<pre>{_CUR})\s*)?(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<suf>k|hazaar|hazar|thousand|lakh|lac)?\b\s*(?P<post>{_CUR})?",
                     re.I)


def extract_amounts(text: str) -> list[int]:
    """Returns amounts in paise found in text, in order. Prefers currency-marked numbers; else last bare number.
    Falls back to number words ('do sau pachas', 'two hundred fifty')."""
    t = (text or "").translate(_DEV)
    marked, bare = [], []
    for m in _NUM_RE.finditer(t):
        try:
            v = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        suf = (m.group("suf") or "").lower()
        v *= {"k": 1000, "hazaar": 1000, "hazar": 1000, "thousand": 1000, "lakh": 100000, "lac": 100000}.get(suf, 1)
        p = int(round(v * 100))
        if p <= 0:
            continue
        (marked if (m.group("pre") or m.group("post")) else bare).append(p)
    if marked:
        return marked
    if bare:
        return [bare[-1]]
    toks = re.findall(r"[a-z]+", t.lower())
    run, best = [], []
    for tok in toks + ["#"]:
        if tok in _WORD_VAL or tok in _MULT:
            run.append(tok)
        else:
            if run:
                n = _words_to_number(run)
                if n:
                    best.append(n * 100)
            run = []
    return best[-1:] if best else []


def strip_amounts(text: str) -> str:
    t = _NUM_RE.sub(" ", (text or "").translate(_DEV))
    t = re.sub(rf"\b{_CUR}\b", " ", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" ,.-")
