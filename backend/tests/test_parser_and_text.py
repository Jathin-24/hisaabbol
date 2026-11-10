import json, pathlib
from app.parser import parse_payment, looks_like_person
from app import textutil, rules

FX = json.loads((pathlib.Path(__file__).parent / "fixtures.json").read_text())
ALIAS = {"counterpartyIsPerson": "counterparty_is_person", "upiRef": "upi_ref", "accountLast4": "account_last4"}


def test_parser_fixtures():
    for f in FX:
        got = parse_payment(f["text"], received_at="2026-11-08T10:15:00Z")
        if f["expect"] is None:
            assert got is None, f["name"]
            continue
        assert got is not None, f["name"]
        for k, v in f["expect"].items():
            assert got[ALIAS.get(k, k)] == v, (f["name"], k, got)


def test_person_heuristic():
    assert looks_like_person("RAMESH KUMAR") and not looks_like_person("ZOMATO")


def test_fmt_and_words():
    assert textutil.fmt_inr(12500000) == "₹1,25,000"
    assert textutil.fmt_inr(25050) == "₹250.50"
    assert textutil.fmt_inr(99900) == "₹999"
    assert textutil.amount_words(25000) == "two hundred fifty rupees"
    assert textutil.amount_words(12525000) == "one lakh twenty-five thousand two hundred fifty rupees"
    assert textutil.amount_words(10050) == "one hundred rupees and fifty paise"


def test_amount_extraction():
    ex = textutil.extract_amounts
    assert ex("chai 20 rupees") == [2000]
    assert ex("₹1,250 groceries") == [125000]
    assert ex("do sau pachas rupaye petrol") == [25000]
    assert ex("paanch hazaar rent") == [500000]
    assert ex("2 samosa 40") == [4000]
    assert ex("5k rent") == [500000]
    assert ex("०५० बस") == [5000]
    assert ex("no numbers here") == []


def test_rules_split_and_udhaar():
    r = rules.understand_rules("500 food, 200 gift", 70000, "Zomato", False)
    assert [(i["category"], i["amount_paise"]) for i in r["items"]] == [("Food & Dining", 50000), ("Gifts & Donations", 20000)]
    assert rules.detect_udhaar("Ramesh ko 500 udhaar diya", "debit", None)[1] == {"person": "Ramesh", "direction": "i_lent"}
    assert rules.detect_udhaar("Ramesh se 500 udhaar liya", "credit", None)[1]["direction"] == "i_borrowed"
    assert rules.detect_udhaar("Neha ne 500 udhaar liya", "debit", None)[1] == {"person": "Neha", "direction": "i_lent"}
    assert rules.detect_udhaar("Neha ne wapas kiye 300", "credit", None)[1]["direction"] == "repaid_to_me"
    assert rules.detect_udhaar("lent 500 to Ramesh", "debit", None)[1]["person"] == "Ramesh"


def test_expense_labels_drop_payment_narration_and_amount():
    assert textutil.clean_expense_label("I paid 50 rupees for dinner") == "Dinner"
    assert textutil.clean_expense_label("spent ₹120 on chai") == "Chai"
    draft = rules.understand_rules("paid 50 dinner", None, None, None)
    assert draft["items"][0]["label"] == "Dinner"
    assert draft["items"][0]["amount_paise"] == 5000


def test_rules_unknown_asks_followup():
    r = rules.understand_rules("hmm something", 9000, None, None)
    assert r["follow_up_question"]
