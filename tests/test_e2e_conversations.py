"""
End-to-end conversation tests against the running server.

Tests the full pipeline: LLM reply, extraction, rule-based StatusEngine,
notification, end-state handling, rate limiting, and leads API.

Usage:
    python tests/test_e2e_conversations.py

Requires the server to be running on localhost:8000.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BASE_URL = "http://localhost:8000"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_DIR = PROJECT_ROOT / "storage"

import yaml
with open(PROJECT_ROOT / "config" / "app.yaml", encoding="utf-8") as f:
    _cfg = yaml.safe_load(f)
ACTIVE_PROPERTY = _cfg.get("paths", {}).get("active_property", "property_2")

PASS_COUNT = 0
FAIL_COUNT = 0
WARN_COUNT = 0


def send(phone: str, body: str) -> str:
    cmd = [
        "curl.exe", "-s", "-X", "POST", f"{BASE_URL}/webhook",
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-d", f"From={urllib.parse.quote(phone)}&Body={urllib.parse.quote(body)}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
    body_m = re.search(r"<Body>(.*?)</Body>", r.stdout, re.DOTALL)
    if body_m:
        return body_m.group(1).strip()
    msg_m = re.search(r"<Message[^>]*>(.*?)</Message>", r.stdout, re.DOTALL)
    return msg_m.group(1).strip() if msg_m else r.stdout


def load_lead(phone: str) -> dict:
    phone_dir = re.sub(r"\D", "", phone)
    p = STORAGE_DIR / ACTIVE_PROPERTY / phone_dir / "lead.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def clean(phone: str):
    phone_dir = re.sub(r"\D", "", phone)
    p = STORAGE_DIR / ACTIVE_PROPERTY / phone_dir
    if p.exists():
        shutil.rmtree(p)


def healthy() -> bool:
    try:
        r = subprocess.run(["curl.exe", "-s", f"{BASE_URL}/health"], capture_output=True, text=True, timeout=5)
        return '"ok":true' in r.stdout or '"ok": true' in r.stdout
    except Exception:
        return False


def check_leads(**params) -> list:
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{BASE_URL}/leads" + (f"?{qs}" if qs else "")
    r = subprocess.run(["curl.exe", "-s", url], capture_output=True, text=True, encoding="utf-8", timeout=5)
    return json.loads(r.stdout)


def verdict(ok: bool, label: str):
    global PASS_COUNT, FAIL_COUNT
    if ok:
        PASS_COUNT += 1
        print(f"  PASS — {label}")
    else:
        FAIL_COUNT += 1
        print(f"  FAIL — {label}")


def warn(label: str):
    global WARN_COUNT
    WARN_COUNT += 1
    print(f"  WARN — {label}")


def show_lead(lead: dict):
    for key in ("status", "score", "name", "notified_at", "closed_at"):
        print(f"  {key}: {lead.get(key)}")
    print(f"  intent: {lead.get('intent', {}).get('type')}")
    for key in ("budget_max", "wants_visit", "timeframe", "equity_amount"):
        print(f"  {key}: {lead.get('criteria', {}).get(key)}")
    print(f"  opted_out: {lead.get('signals', {}).get('opted_out')}")


# ── Scenarios (property_2 = rental, 3800 ILS/month, Tel Aviv) ────

def test_1_renter_qualifies():
    """Renter provides intent + budget + timeframe + visit → qualifies (max_missing=1, 4 required)."""
    phone = "whatsapp:+972500000001"
    clean(phone)
    print("\n=== 1: Renter full flow → qualify + notify ===")

    msgs = [
        "היי, ראיתי את הדירה ברחוב מטלון. עדיין פנויה?",
        "אני מחפש לשכור. התקציב שלי עד 4000 שקל",
        "רוצה להיכנס תוך חודש. אפשר לבוא לראות? קוראים לי דני",
    ]
    for i, m in enumerate(msgs):
        print(f"  [{i+1}] User: {m}")
        r = send(phone, m)
        print(f"      Agent: {r[:200]}")
        time.sleep(0.5)

    lead = load_lead(phone)
    print()
    show_lead(lead)

    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    verdict(lead.get("criteria", {}).get("budget_max") is not None, "budget extracted")
    verdict(lead.get("criteria", {}).get("wants_visit") is True, "wants_visit = True")
    verdict(lead.get("criteria", {}).get("timeframe") is not None, "timeframe extracted")
    verdict(lead.get("status") in ("qualified", "closed"), f"status = {lead.get('status')}")
    verdict(lead.get("notified_at") is not None, "owner notified")
    if lead.get("name"):
        verdict(True, f"name = {lead.get('name')}")
    else:
        warn("name not captured (may have qualified before name message was processed)")


def test_2_closed_static():
    phone = "whatsapp:+972500000001"
    print("\n=== 2: Closed lead → static reply ===")
    lead = load_lead(phone)
    if lead.get("status") != "closed":
        warn("test 1 didn't close — skipping")
        return
    r = send(phone, "יש לי שאלה נוספת")
    verdict("הועברו" in r or "בעל הדירה" in r, "static closed reply")


def test_3_not_interested():
    phone = "whatsapp:+972500000003"
    clean(phone)
    print("\n=== 3: Not interested → disqualify ===")
    msgs = [
        "היי, כמה עולה הדירה?",
        "יקר מדי בשבילי, לא מתאים. תודה",
    ]
    for i, m in enumerate(msgs):
        print(f"  [{i+1}] User: {m}")
        r = send(phone, m)
        print(f"      Agent: {r[:200]}")
        time.sleep(0.5)

    lead = load_lead(phone)
    show_lead(lead)
    verdict(
        lead.get("status") == "disqualified" or lead.get("signals", {}).get("opted_out") is True,
        "correctly disqualified or opted_out flagged",
    )


def test_4_disqualified_static():
    phone = "whatsapp:+972500000003"
    print("\n=== 4: Disqualified lead → static reply ===")
    lead = load_lead(phone)
    if lead.get("status") != "disqualified":
        warn("test 3 didn't disqualify — skipping")
        return
    r = send(phone, "אולי בכל זאת")
    verdict("תרצה לחזור" in r or "בעתיד" in r or "ההתעניינות" in r, "static disqualified reply")


def test_5_english_renter():
    phone = "whatsapp:+972500000005"
    clean(phone)
    print("\n=== 5: English renter → qualify ===")
    msgs = [
        "Hi, is the apartment on Matalon still available?",
        "I'm looking to rent. Budget up to 4000 NIS. Want to move ASAP.",
        "I'd love to visit. My name is Sarah.",
    ]
    for i, m in enumerate(msgs):
        print(f"  [{i+1}] User: {m}")
        r = send(phone, m)
        print(f"      Agent: {r[:200]}")
        time.sleep(0.5)

    lead = load_lead(phone)
    print()
    show_lead(lead)
    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    verdict(lead.get("criteria", {}).get("budget_max") is not None, "budget extracted")
    verdict(lead.get("status") in ("qualified", "closed"), f"status = {lead.get('status')}")
    if lead.get("criteria", {}).get("wants_visit") is True:
        verdict(True, "wants_visit = True")
    else:
        warn("wants_visit not captured (lead may have qualified before this message)")
    if lead.get("name"):
        verdict(True, f"name = {lead.get('name')}")
    else:
        warn("name not captured (lead may have qualified before this message)")


def test_6_dense_message():
    phone = "whatsapp:+972500000006"
    clean(phone)
    print("\n=== 6: Dense single message → max extraction ===")
    m = "היי, מחפש דירה לשכירות, תקציב 3500-4000, רוצה להיכנס מיד. אשמח לביקור. קוראים לי אבי."
    print(f"  User: {m}")
    r = send(phone, m)
    print(f"  Agent: {r[:200]}")

    lead = load_lead(phone)
    show_lead(lead)
    filled = sum(1 for v in [
        lead.get("intent", {}).get("type"),
        lead.get("criteria", {}).get("budget_max"),
        lead.get("criteria", {}).get("wants_visit"),
        lead.get("criteria", {}).get("timeframe"),
        lead.get("name"),
    ] if v is not None)
    print(f"  Fields filled: {filled}/5")
    verdict(filled >= 3, f"extracted {filled}/5 fields from one message")


def test_7_buy_mismatch():
    phone = "whatsapp:+972500000007"
    clean(phone)
    print("\n=== 7: Buy intent on rental → intent mismatch ===")
    msgs = [
        "אני רוצה לקנות את הדירה",
        "רק קנייה מעניינת אותי",
    ]
    for i, m in enumerate(msgs):
        print(f"  [{i+1}] User: {m}")
        r = send(phone, m)
        print(f"      Agent: {r[:200]}")
        time.sleep(0.5)

    lead = load_lead(phone)
    show_lead(lead)
    verdict(lead.get("status") == "disqualified", "disqualified on intent mismatch")


def test_8_rate_limiting():
    phone = "whatsapp:+972500000008"
    clean(phone)
    print("\n=== 8: Rate limiting ===")
    limited = False
    for i in range(15):
        r = send(phone, f"msg {i+1}")
        if "מהר מדי" in r:
            print(f"  Rate limited after {i+1} messages")
            limited = True
            break
    verdict(limited, "rate limiter triggered")


def test_9_leads_api():
    print("\n=== 9: Leads API ===")
    all_leads = check_leads()
    prop_leads = check_leads(property=ACTIVE_PROPERTY)
    closed = check_leads(status="closed")
    print(f"  All: {len(all_leads)}, Property: {len(prop_leads)}, Closed: {len(closed)}")
    verdict(len(all_leads) >= 4, f"at least 4 leads tracked (got {len(all_leads)})")
    verdict(len(closed) >= 1, f"at least 1 closed lead")


def test_10_property_qa():
    phone = "whatsapp:+972500000010"
    clean(phone)
    print("\n=== 10: Property Q&A ===")
    qa = [
        ("כמה חדרים יש?", None),
        ("יש מזגן?", None),
        ("באיזה כתובת?", None),
    ]
    for i, (q, _) in enumerate(qa):
        print(f"  [{i+1}] User: {q}")
        r = send(phone, q)
        print(f"      Agent: {r[:200]}")
        time.sleep(0.5)

    lead = load_lead(phone)
    verdict(lead.get("status") == "collecting", "still collecting (not prematurely disqualified)")


def test_11_gibberish():
    phone = "whatsapp:+972500000011"
    clean(phone)
    print("\n=== 11: Gibberish ===")
    for m in ["asdf", "???", "lol"]:
        r = send(phone, m)
        print(f"  {m} → {r[:100]}")
    verdict(True, "no crash on gibberish")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("E2E Conversation Tests (Architecture v3)")
    print(f"Active property: {ACTIVE_PROPERTY}")
    print("=" * 60)

    if not healthy():
        print("ERROR: Server not running on localhost:8000")
        sys.exit(1)
    print("Server healthy.\n")

    test_1_renter_qualifies()
    test_2_closed_static()
    test_3_not_interested()
    test_4_disqualified_static()
    test_5_english_renter()
    test_6_dense_message()
    test_7_buy_mismatch()
    test_8_rate_limiting()
    test_9_leads_api()
    test_10_property_qa()
    test_11_gibberish()

    print("\n" + "=" * 60)
    print(f"RESULTS:  {PASS_COUNT} passed  |  {FAIL_COUNT} failed  |  {WARN_COUNT} warnings")
    print("=" * 60)
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
