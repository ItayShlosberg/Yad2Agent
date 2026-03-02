"""
Manual smoke test — sends a multi-turn conversation via curl and validates responses.

Usage:
    1. Start the server:  uvicorn src.main:app --reload --port 8000
    2. Run this script:   python tests/test_smoke.py

The script clears test data, sends five messages, and checks that every
response is a valid TwiML reply (not the fallback message).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

BASE_URL = "http://localhost:8000"
TEST_PHONE = "whatsapp:+972500000001"
PHONE_DIR = "972500000001"
STORAGE_DIR = Path(__file__).resolve().parent.parent / "storage" / PHONE_DIR
FALLBACK = "תודה על ההודעה! אחזור אליך בהקדם."

TURNS = [
    ("היי, הדירה עדיין למכירה?", "Turn 1 — opening question"),
    ("מה השטח? באיזה קומה? יש ממד?", "Turn 2 — property details barrage"),
    ("מה המחיר? יש חניה?", "Turn 3 — pricing + parking"),
    ("אני רוצה לקנות, תקציב עד 2.4 מיליון, הון עצמי 500 אלף, רוצה להיכנס תוך חודשיים", "Turn 4 — qualifying info"),
    ("כן, אשמח לביקור. השם שלי דני. תודה!", "Turn 5 — name + visit + wrap-up"),
]


def send_message(body: str) -> str:
    """POST a message to the webhook and return the raw TwiML response."""
    encoded_body = urllib.parse.quote(body, safe="")
    encoded_phone = urllib.parse.quote(TEST_PHONE, safe="")
    result = subprocess.run(
        [
            "curl.exe", "-s", "-X", "POST", f"{BASE_URL}/webhook",
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "-d", f"From={encoded_phone}&Body={encoded_body}",
        ],
        capture_output=True, encoding="utf-8", timeout=60,
    )
    return result.stdout


def main() -> None:
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
        print(f"Cleared {STORAGE_DIR}")

    print(f"\nHealth check: ", end="")
    health = subprocess.run(
        ["curl.exe", "-s", f"{BASE_URL}/health"],
        capture_output=True, encoding="utf-8", timeout=10,
    )
    if '"ok":true' not in health.stdout:
        print(f"FAIL — server not responding ({health.stdout})")
        sys.exit(1)
    print("OK\n")

    passed = 0
    for body, label in TURNS:
        print(f"  {label} ...", end=" ", flush=True)
        response = send_message(body)

        if "<Message>" not in response:
            print(f"FAIL — no <Message> in response")
            print(f"    Response: {response[:200]}")
            continue

        reply_start = response.index("<Message>") + len("<Message>")
        reply_end = response.index("</Message>")
        reply = response[reply_start:reply_end]

        if FALLBACK in reply:
            print(f"FAIL — got fallback reply")
        else:
            print(f"OK  ({reply[:60]}...)")
            passed += 1

        time.sleep(1)

    lead_path = STORAGE_DIR / "lead.json"
    if lead_path.exists():
        lead = json.loads(lead_path.read_text(encoding="utf-8"))
        print(f"\n  Lead state:")
        print(f"    Name:   {lead.get('name', '—')}")
        print(f"    Status: {lead.get('status', '—')}")
        print(f"    Score:  {lead.get('score', '—')}")
        print(f"    Intent: {lead.get('intent', {}).get('type', '—')}")
        print(f"    Budget: {lead.get('criteria', {}).get('budget_max', '—')}")
        print(f"    Visit:  {lead.get('criteria', {}).get('wants_visit', '—')}")
    else:
        print("\n  No lead.json found!")

    print(f"\n  Result: {passed}/{len(TURNS)} turns passed")
    sys.exit(0 if passed == len(TURNS) else 1)


if __name__ == "__main__":
    main()
