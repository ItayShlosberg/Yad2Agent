"""
Smoke test — sends a multi-turn conversation and validates responses.

Supports two modes:
  curl   — (default) sends HTTP POST directly to the local server. Fast,
           no Twilio quota consumed. Use for routine local development.
  twilio — sends messages via the Twilio REST API so they travel the full
           WhatsApp → Twilio → ngrok → server → Twilio → WhatsApp path.
           Checks delivery status. Consumes Twilio quota.

Usage:
    python tests/test_smoke.py              # curl mode (default)
    python tests/test_smoke.py --mode curl
    python tests/test_smoke.py --mode twilio --phone +972546487753
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

BASE_URL = "http://localhost:8000"
ACTIVE_PROPERTY = "property_1"
FALLBACK = "תודה על ההודעה! אחזור אליך בהקדם."

TURNS = [
    ("היי, הדירה עדיין למכירה?", "Turn 1 — opening question"),
    ("מה השטח? באיזה קומה? יש ממד?", "Turn 2 — property details barrage"),
    ("מה המחיר? יש חניה?", "Turn 3 — pricing + parking"),
    ("אני רוצה לקנות, תקציב עד 2.4 מיליון, הון עצמי 500 אלף, רוצה להיכנס תוך חודשיים", "Turn 4 — qualifying info"),
    ("כן, אשמח לביקור. השם שלי דני. תודה!", "Turn 5 — name + visit + wrap-up"),
]


# ── Curl mode ─────────────────────────────────────────────────────

def _curl_health() -> bool:
    r = subprocess.run(
        ["curl.exe", "-s", f"{BASE_URL}/health"],
        capture_output=True, encoding="utf-8", timeout=10,
    )
    return '"ok":true' in r.stdout


def _curl_send(phone: str, body: str) -> str:
    encoded_body = urllib.parse.quote(body, safe="")
    encoded_phone = urllib.parse.quote(phone, safe="")
    r = subprocess.run(
        [
            "curl.exe", "-s", "-X", "POST", f"{BASE_URL}/webhook",
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "-d", f"From={encoded_phone}&Body={encoded_body}",
        ],
        capture_output=True, encoding="utf-8", timeout=60,
    )
    return r.stdout


def _extract_reply(response: str) -> str | None:
    if "<Message" not in response:
        return None
    if "<Body>" in response:
        start = response.index("<Body>") + len("<Body>")
        end = response.index("</Body>")
    elif "<Message>" in response:
        start = response.index("<Message>") + len("<Message>")
        end = response.index("</Message>")
    else:
        tag_end = response.index(">", response.index("<Message"))
        start = tag_end + 1
        end = response.index("</Message>")
    return response[start:end]


# ── Twilio mode ───────────────────────────────────────────────────

class TwilioClient:
    """Minimal Twilio REST API client (no extra dependency)."""

    def __init__(self) -> None:
        self.sid = os.getenv("TWILIO_ACCOUNT_SID", "")
        self.token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = os.getenv("TWILIO_WHATSAPP_NUMBER", "")
        if not all([self.sid, self.token, self.from_number]):
            print("ERROR: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER must be set in .env")
            sys.exit(1)

    def _auth_header(self) -> str:
        cred = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        return f"Basic {cred}"

    def send_message(self, to: str, body: str) -> dict:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        data = urllib.parse.urlencode({"From": self.from_number, "To": to, "Body": body}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", self._auth_header())
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def get_message(self, message_sid: str) -> dict:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages/{message_sid}.json"
        req = urllib.request.Request(url)
        req.add_header("Authorization", self._auth_header())
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def get_recent_messages(self, to_phone: str, limit: int = 5) -> list[dict]:
        encoded = urllib.parse.quote(to_phone, safe="")
        url = (
            f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
            f"?To={encoded}&PageSize={limit}"
        )
        req = urllib.request.Request(url)
        req.add_header("Authorization", self._auth_header())
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read()).get("messages", [])

    def wait_for_delivery(self, message_sid: str, timeout: int = 30) -> dict:
        """Poll until the message reaches a terminal status."""
        terminal = {"delivered", "read", "failed", "undelivered"}
        deadline = time.time() + timeout
        msg = {}
        while time.time() < deadline:
            msg = self.get_message(message_sid)
            if msg.get("status") in terminal:
                return msg
            time.sleep(2)
        return msg


# ── Main ──────────────────────────────────────────────────────────

def run_curl(test_phone: str) -> int:
    phone_digits = test_phone.replace("whatsapp:", "").replace("+", "").replace("-", "")
    storage = ROOT / "storage" / ACTIVE_PROPERTY / phone_digits

    if storage.exists():
        shutil.rmtree(storage)
        print(f"Cleared {storage}")

    print("\nHealth check: ", end="")
    if not _curl_health():
        print("FAIL — server not responding")
        return 1
    print("OK\n")

    passed = 0
    for body, label in TURNS:
        print(f"  {label} ...", end=" ", flush=True)
        response = _curl_send(test_phone, body)
        reply = _extract_reply(response)

        if reply is None:
            print(f"FAIL — no <Message> in response")
            print(f"    Response: {response[:200]}")
            continue
        if FALLBACK in reply:
            print("FAIL — got fallback reply")
        else:
            print(f"OK  ({reply[:60]}...)")
            passed += 1
        time.sleep(1)

    lead_path = storage / "lead.json"
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
    return 0 if passed == len(TURNS) else 1


def run_twilio(to_phone: str) -> int:
    client = TwilioClient()

    print(f"\nTwilio mode — sending to {to_phone}")
    print(f"  (each turn: send message → wait for agent reply → check delivery)\n")

    passed = 0
    for body, label in TURNS:
        print(f"  {label} ...", flush=True)

        try:
            sent = client.send_message(to_phone, body)
        except Exception as e:
            print(f"    SEND FAIL: {e}")
            continue

        inbound_sid = sent.get("sid", "?")
        print(f"    Sent [{inbound_sid}] status={sent.get('status')}")

        print("    Waiting for agent reply ...", end=" ", flush=True)
        time.sleep(8)

        recent = client.get_recent_messages(to_phone, limit=3)
        agent_replies = [
            m for m in recent
            if m.get("direction") == "outbound-api" or m.get("from") == client.from_number
        ]

        if not agent_replies:
            print("FAIL — no outbound message found")
            continue

        latest = agent_replies[0]
        reply_status = latest.get("status", "?")
        error_code = latest.get("error_code")
        reply_body = latest.get("body", "")[:70]

        if error_code:
            print(f"DELIVERY FAIL — status={reply_status} error={error_code}")
            print(f"    Body: {reply_body}")
        elif reply_status in ("delivered", "read", "sent", "queued"):
            print(f"OK  status={reply_status}")
            print(f"    Body: {reply_body}...")
            passed += 1
        else:
            print(f"UNKNOWN — status={reply_status}")
            print(f"    Body: {reply_body}")

        time.sleep(2)

    print(f"\n  Result: {passed}/{len(TURNS)} turns passed")
    return 0 if passed == len(TURNS) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Yad2Agent smoke test")
    parser.add_argument(
        "--mode", choices=["curl", "twilio"], default="curl",
        help="curl = local HTTP (default, no quota used), twilio = real WhatsApp API",
    )
    parser.add_argument(
        "--phone", default=None,
        help="WhatsApp phone for curl (default: test number) or twilio (required) mode. Format: whatsapp:+972...",
    )
    args = parser.parse_args()

    if args.mode == "curl":
        phone = args.phone or "whatsapp:+972500000001"
        sys.exit(run_curl(phone))
    else:
        phone = args.phone
        if not phone:
            phone = os.getenv("MY_WHATSAPP_NUMBER", "")
        if not phone:
            print("ERROR: --phone is required for twilio mode (or set MY_WHATSAPP_NUMBER in .env)")
            sys.exit(1)
        sys.exit(run_twilio(phone))


if __name__ == "__main__":
    main()
