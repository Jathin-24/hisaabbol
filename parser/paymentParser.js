/**
 * HisaabBol payment parser — plain JS, zero dependencies, runs in Node and React Native (Hermes).
 * Input : text of a bank SMS or a UPI-app notification (title + body joined by " | ").
 * Output: null (not a payment) or a normalized transaction object.
 * PRIVACY: runs on-device only. Never send raw SMS/notification text to any server.
 */

const AMOUNT_RES = [
  /(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)/i, // Rs.250.00 / INR 250 / ₹250
  /(?:debited|credited|spent|paid|sent|withdrawn)\s+(?:by|for|of)\s+([\d,]+(?:\.\d{1,2})?)/i, // SBI: "debited by 250.0"
];

const DEBIT_WORDS = /\b(debited|debit|sent|spent|paid|payment of|withdrawn|purchase|purchased|transferred|trf to|txn of)\b/i;
const CREDIT_WORDS = /\b(credited|credit|received|deposited|refund(?:ed)?)\b/i;

// Messages that look financial but are NOT a completed payment.
const REJECT = /\b(otp|one[- ]time|verification code|cashback|offer|offers|get up to|voucher|coupon|reward|apply now|pre-?approved|credit limit|available limit|avl\.? ?(?:bal|limit)|statement|due (?:on|by|date)|min(?:imum)? due|emi (?:due|reminder)|will be debited|has been requested|collect request|requested money|is requesting|failed|declined|reversed|unsuccessful|insufficient)\b/i;

const COUNTERPARTY_RES = [
  /UPI\/(?:P2M|P2A|P2P)\/\d{6,}\/(.+?)(?=\s+(?:SMS|If|Not|Call)\b|\s+-\s|$)/i, // Axis: UPI/P2M/ref/NAME
  /\btrf to\s+(.+?)\s+(?:ref(?:no)?|upi)\b/i, // SBI
  /\bto\s+(?:VPA\s+)?([A-Za-z0-9&@._' -]{2,40}?)\s+(?:on|ref|upi|via|using)\b/i, // HDFC/Kotak: "To ZOMATO On"
  /;\s*([A-Za-z0-9&@._' -]{2,40}?)\s+credited\b/i, // ICICI: "; ZOMATO credited"
  /\bat\s+([A-Za-z0-9&@._' -]{2,40}?)\s+on\b/i, // card: "at AMAZON on"
  /\b(?:paid|sent)\s+(?:₹|rs\.?|inr)?\s*[\d,]+(?:\.\d{1,2})?\s+to\s+([A-Za-z0-9&@._' -]{2,40})/i, // notif: "Paid ₹250 to Zomato"
  /\bpaid to\s+([A-Za-z0-9&@._' -]{2,40})/i,
  /\bfrom\s+([A-Za-z0-9&@._' -]{2,40}?)\s+(?:on|ref|upi|via)\b/i, // credits
  /\bby\s+([A-Za-z][A-Za-z0-9&@._' -]{2,40}?)\s+(?:\(|ref|upi)/i,
];

function toAmount(s) {
  return Math.round(parseFloat(s.replace(/,/g, '')) * 100) / 100;
}

function cleanName(n) {
  if (!n) return null;
  n = n.replace(/\s+/g, ' ').replace(/[.,;:-]+$/g, '').trim();
  if (/^(a\/c|acct|account|your|mobile|bank|xx|x\d)/i.test(n)) return null;
  if (n.includes('@')) n = n.split('@')[0]; // zomato@icici -> zomato
  return n.length >= 2 ? n : null;
}

function detectInstrument(t, ref) {
  if (/\bcard\b/i.test(t)) return 'card';
  if (/\bupi\b|vpa|@[a-z]{2,}/i.test(t)) return 'upi';
  if (ref && /\b(sent|trf|debited)\b/i.test(t)) return 'upi'; // 12-digit RRN on a transfer: UPI in practice (IMPS also uses RRN)
  if (/\batm\b|cash withdrawal/i.test(t)) return 'atm';
  return 'bank';
}

// Heuristic: UPI payee names for people tend to be 1-3 alphabetic words with no business keyword,
// or phone-number VPAs. Used only to decide prompt wording ("who is this for?" vs "what did you buy?").
const BIZ = /\b(store|stores|mart|foods?|restaurant|cafe|hotel|bakery|pharmacy|medical|traders?|enterprises?|services?|pvt|ltd|llp|mobility|retail|super|market|kirana|dairy|sweets|fuel|petrol|gas|bpcl|iocl|hpcl|irctc|zomato|swiggy|amazon|flipkart|uber|ola|rapido|blinkit|zepto|bigbasket|jio|airtel|bsnl|paytm|phonepe|gpay|netflix|spotify|bookmyshow|tea|stall)\b/i;
function looksLikePerson(name) {
  if (/^\d{10}$/.test(name) || /^\d{10}@/.test(name)) return true;
  if (BIZ.test(name)) return false;
  const words = name.trim().split(/\s+/);
  return words.length >= 1 && words.length <= 3 && words.every((w) => /^[A-Za-z.]+$/.test(w));
}

function parsePayment(text, opts = {}) {
  if (!text || typeof text !== 'string') return null;
  const t = text.replace(/\s+/g, ' ').trim();
  const hasDebit = DEBIT_WORDS.test(t);
  const hasCredit = CREDIT_WORDS.test(t);
  if (!hasDebit && !hasCredit) return null;
  if (/\b(otp|one[- ]time|verification code)\b/i.test(t)) return null;
  if (REJECT.test(t)) return null;

  let amount = null;
  for (const re of AMOUNT_RES) {
    const m = t.match(re);
    if (m) {
      amount = toAmount(m[1]);
      break;
    }
  }
  if (!amount || amount <= 0) return null;

  // Direction: whichever keyword appears first wins; special cases below.
  const di = t.search(DEBIT_WORDS);
  const ci = t.search(CREDIT_WORDS);
  let direction = hasDebit && (!hasCredit || di <= ci) ? 'debit' : 'credit';
  if (hasDebit && hasCredit && /debited/i.test(t) && /;\s*[^;]+credited/i.test(t)) direction = 'debit'; // ICICI
  if (/\bpaid\b.*\bto\b/i.test(t) && !/\breceived\b/i.test(t)) direction = 'debit'; // "Paid ₹250 to X"

  let counterparty = null;
  for (const re of COUNTERPARTY_RES) {
    const m = t.match(re);
    if (m) {
      counterparty = cleanName(m[1]);
      if (counterparty) break;
    }
  }

  const ref = (t.match(/\b(\d{12})\b/) || [])[1] || null;
  const acct =
    (t.match(/(?:a\/c|acct|account|card|ac)\.?\s*(?:no\.?)?\s*[xX*]*\s*(\d{3,4})\b/i) ||
      t.match(/[xX*]{2,}(\d{3,4})\b/) ||
      [])[1] || null;

  const at = opts.receivedAt || new Date().toISOString();
  return {
    direction,
    amount,
    currency: 'INR',
    counterparty,
    counterpartyIsPerson: counterparty ? looksLikePerson(counterparty) : null,
    upiRef: ref,
    accountLast4: acct,
    instrument: detectInstrument(t, ref),
    source: opts.source || 'sms',
    occurredAt: at,
    dedupeKey: ref
      ? `ref:${ref}`
      : `amt:${amount}|cp:${(counterparty || '').toLowerCase()}|min:${String(at).slice(0, 16)}`,
  };
}

/** Merge duplicates from several sources (bank SMS + UPI-app notification for the same payment). */
function isDuplicate(a, b, windowMs = 10 * 60 * 1000) {
  if (a.upiRef && b.upiRef) return a.upiRef === b.upiRef;
  if (a.amount !== b.amount || a.direction !== b.direction) return false;
  return Math.abs(new Date(a.occurredAt) - new Date(b.occurredAt)) <= windowMs;
}

module.exports = { parsePayment, isDuplicate, looksLikePerson };
