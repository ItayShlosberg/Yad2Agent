"""
Direct orchestrator tests — exercises LLM, extraction, StatusEngine,
and full pipeline WITHOUT any Twilio calls or HTTP server.

Use this for:
  - Prompt engineering iteration
  - Extraction accuracy validation
  - Status transition integration testing
  - Conversation flow regression

Usage:
    python tests/test_orchestrator_direct.py
    python tests/test_orchestrator_direct.py --scenario 1   # run only scenario 1
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config
from src.services.listing import ListingLoader
from src.services.llm_service import LLMService
from src.services.orchestrator import ConversationOrchestrator, OrchestratorReply
from src.services.prompts import PromptBuilder
from src.services.rate_limiter import RateLimiter
from src.services.scorer import LeadScorer
from src.services.status_engine import StatusEngine
from src.services.store import ConversationStore

PASS_COUNT = 0
FAIL_COUNT = 0
WARN_COUNT = 0


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


class DirectTestHarness:
    """Builds a real orchestrator with the live LLM but no Twilio."""

    def __init__(self):
        self._cfg = load_config()
        self._listing = ListingLoader(self._cfg.paths.property_dir)
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="yad2_test_"))

        pricing = self._listing.data.get("pricing", {})
        if pricing.get("monthly_rent_ils"):
            self._property_type = "rent"
            self._asking_price = pricing.get("monthly_rent_ils")
        else:
            self._property_type = "buy"
            self._asking_price = pricing.get("asking_price")

        prompts = PromptBuilder(self._listing, self._cfg.qualifying)
        self._llm = LLMService(self._cfg.secrets.openai_api_key, self._cfg.llm, prompts)
        self._scorer = LeadScorer(self._cfg.qualifying)
        self._status_engine = StatusEngine(
            qualifying=self._cfg.qualifying,
            property_type=self._property_type,
            asking_price=self._asking_price,
        )
        self._rate_limiter = RateLimiter(self._cfg.rate_limit)

    def new_orchestrator(self, phone_suffix: str) -> tuple[ConversationOrchestrator, str]:
        """Return a fresh orchestrator with isolated storage and a unique phone."""
        phone = f"whatsapp:+97250{phone_suffix}"
        store = ConversationStore(self._tmp_dir)
        orch = ConversationOrchestrator(
            store=store,
            llm=self._llm,
            scorer=self._scorer,
            status_engine=self._status_engine,
            qualifying=self._cfg.qualifying,
            listing=self._listing,
            media_base_url="",
            notifier=None,  # no Twilio
            rate_limiter=self._rate_limiter,
            property_name=self._cfg.paths.active_property,
        )
        return orch, phone

    def load_lead(self, phone: str) -> dict:
        store = ConversationStore(self._tmp_dir)
        lead = store.load_lead(phone)
        return json.loads(lead.model_dump_json())

    def cleanup(self):
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    @property
    def property_type(self) -> str:
        return self._property_type

    @property
    def asking_price(self) -> float | None:
        return self._asking_price


def converse(orch: ConversationOrchestrator, phone: str, messages: list[str]) -> list[OrchestratorReply]:
    """Send a sequence of messages and return all replies."""
    replies = []
    for i, msg in enumerate(messages):
        print(f"  [{i+1}] User: {msg}")
        reply = orch.handle_message(phone, msg)
        print(f"      Agent: {reply.text[:200]}")
        replies.append(reply)
    return replies


# ── Scenarios ─────────────────────────────────────────────────────────


def scenario_1_renter_qualifies(h: DirectTestHarness):
    """Full rent flow: intent + budget + timeframe + visit → qualified → closed."""
    print("\n=== 1: Renter full flow → qualify + close ===")
    orch, phone = h.new_orchestrator("0000001")
    converse(orch, phone, [
        "היי, ראיתי את הדירה ברחוב מטלון. עדיין פנויה?",
        "אני מחפש לשכור. התקציב שלי עד 4000 שקל",
        "רוצה להיכנס תוך חודש. אפשר לבוא לראות? קוראים לי דני",
    ])
    lead = h.load_lead(phone)
    print()
    _show(lead)
    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    verdict(lead.get("criteria", {}).get("budget_max") is not None, "budget extracted")
    verdict(lead.get("criteria", {}).get("wants_visit") is True, "wants_visit = True")
    verdict(lead.get("criteria", {}).get("timeframe") is not None, "timeframe extracted")
    verdict(lead.get("status") == "closed", f"status = {lead.get('status')}")
    verdict(lead.get("notified_at") is not None, "notified_at set (no actual Twilio call)")
    if lead.get("name"):
        verdict(True, f"name = {lead.get('name')}")
    else:
        warn("name not captured")


def scenario_2_closed_static(h: DirectTestHarness):
    """Closed lead gets static reply without LLM call."""
    print("\n=== 2: Closed lead → static reply ===")
    orch, phone = h.new_orchestrator("0000001")
    converse(orch, phone, [
        "היי, מחפש לשכור, תקציב 4000, להיכנס מיד, רוצה לבקר",
        "מעולה, קוראים לי דני",
    ])
    lead = h.load_lead(phone)
    if lead.get("status") != "closed":
        warn(f"lead not closed (status={lead.get('status')}) — testing static reply anyway")
    reply = orch.handle_message(phone, "יש לי שאלה נוספת")
    verdict("הועברו" in reply.text or "בעל הדירה" in reply.text, "static closed reply")


def scenario_3_not_interested(h: DirectTestHarness):
    """User explicitly opts out → disqualified."""
    print("\n=== 3: Not interested → disqualify ===")
    orch, phone = h.new_orchestrator("0000003")
    converse(orch, phone, [
        "היי, כמה עולה הדירה?",
        "יקר מדי בשבילי, לא מתאים. תודה",
    ])
    lead = h.load_lead(phone)
    _show(lead)
    verdict(
        lead.get("status") == "disqualified" or lead.get("signals", {}).get("opted_out") is True,
        "correctly disqualified or opted_out flagged",
    )


def scenario_4_disqualified_static(h: DirectTestHarness):
    """Disqualified lead gets static reply without LLM call."""
    print("\n=== 4: Disqualified lead → static reply ===")
    orch, phone = h.new_orchestrator("0000003")
    converse(orch, phone, [
        "היי, לא מתאים לי בכלל, תודה",
        "באמת לא מעניין",
    ])
    lead = h.load_lead(phone)
    if lead.get("status") != "disqualified":
        warn(f"lead not disqualified (status={lead.get('status')}) — testing static reply anyway")
        reply = orch.handle_message(phone, "אולי בכל זאת")
    else:
        reply = orch.handle_message(phone, "אולי בכל זאת")
    verdict("תרצה לחזור" in reply.text or "בעתיד" in reply.text or "ההתעניינות" in reply.text, "static disqualified reply")


def scenario_5_english_renter(h: DirectTestHarness):
    """English-speaking renter qualifies."""
    print("\n=== 5: English renter → qualify ===")
    orch, phone = h.new_orchestrator("0000005")
    converse(orch, phone, [
        "Hi, is the apartment on Matalon still available?",
        "I'm looking to rent. Budget up to 4000 NIS. Want to move ASAP.",
        "I'd love to visit. My name is Sarah.",
    ])
    lead = h.load_lead(phone)
    print()
    _show(lead)
    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    verdict(lead.get("criteria", {}).get("budget_max") is not None, "budget extracted")
    verdict(lead.get("status") == "closed", f"status = {lead.get('status')}")
    if lead.get("criteria", {}).get("wants_visit") is True:
        verdict(True, "wants_visit = True")
    else:
        warn("wants_visit not captured (may have qualified early)")
    if lead.get("name"):
        verdict(True, f"name = {lead.get('name')}")
    else:
        warn("name not captured (may have qualified early)")


def scenario_6_dense_message(h: DirectTestHarness):
    """Single dense message should extract max fields."""
    print("\n=== 6: Dense single message → max extraction ===")
    orch, phone = h.new_orchestrator("0000006")
    converse(orch, phone, [
        "היי, מחפש דירה לשכירות, תקציב 3500-4000, רוצה להיכנס מיד. אשמח לביקור. קוראים לי אבי.",
    ])
    lead = h.load_lead(phone)
    _show(lead)
    filled = sum(1 for v in [
        lead.get("intent", {}).get("type"),
        lead.get("criteria", {}).get("budget_max"),
        lead.get("criteria", {}).get("wants_visit"),
        lead.get("criteria", {}).get("timeframe"),
        lead.get("name"),
    ] if v is not None)
    print(f"  Fields filled: {filled}/5")
    verdict(filled >= 3, f"extracted {filled}/5 fields from one message")


def scenario_7_buy_mismatch(h: DirectTestHarness):
    """Buy intent on a rental property → disqualified."""
    print("\n=== 7: Buy intent on rental → intent mismatch ===")
    orch, phone = h.new_orchestrator("0000007")
    converse(orch, phone, [
        "אני רוצה לקנות את הדירה",
        "רק קנייה מעניינת אותי",
    ])
    lead = h.load_lead(phone)
    _show(lead)
    verdict(lead.get("status") == "disqualified", "disqualified on intent mismatch")


def scenario_8_property_qa(h: DirectTestHarness):
    """Property questions without qualifying info → stays collecting."""
    print("\n=== 8: Property Q&A → stays collecting ===")
    orch, phone = h.new_orchestrator("0000010")
    converse(orch, phone, [
        "כמה חדרים יש בדירה?",
        "יש מזגן?",
        "באיזה כתובת הדירה?",
    ])
    lead = h.load_lead(phone)
    verdict(lead.get("status") == "collecting", "still collecting (not prematurely disqualified)")


def scenario_9_gibberish(h: DirectTestHarness):
    """Random input doesn't crash the system."""
    print("\n=== 9: Gibberish → no crash ===")
    orch, phone = h.new_orchestrator("0000011")
    for m in ["asdf", "???", "lol"]:
        reply = orch.handle_message(phone, m)
        print(f"  {m} → {reply.text[:100]}")
    verdict(True, "no crash on gibberish")


def scenario_10_gradual_info(h: DirectTestHarness):
    """Info given across many turns — should eventually qualify."""
    print("\n=== 10: Gradual info over many turns → qualify ===")
    orch, phone = h.new_orchestrator("0000012")
    converse(orch, phone, [
        "היי, ראיתי את המודעה",
        "אני מחפש דירה לשכירות",
        "התקציב שלי הוא בערך 3800 שקל לחודש",
        "אני צריך להיכנס תוך חודשיים",
        "כן, אשמח מאוד לבוא לראות את הדירה",
    ])
    lead = h.load_lead(phone)
    print()
    _show(lead)
    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    verdict(lead.get("criteria", {}).get("budget_max") is not None, "budget extracted")
    verdict(lead.get("status") in ("qualified", "closed"), f"status = {lead.get('status')}")


def scenario_11_low_budget(h: DirectTestHarness):
    """Budget way below asking price → disqualified (budget_floor_pct)."""
    print("\n=== 11: Budget too low → disqualify ===")
    orch, phone = h.new_orchestrator("0000013")
    converse(orch, phone, [
        "היי, מחפש דירה לשכירות",
        "התקציב שלי הוא 1500 שקל מקסימום",
    ])
    lead = h.load_lead(phone)
    _show(lead)
    verdict(lead.get("status") == "disqualified", "disqualified on low budget")


def scenario_12_extraction_accuracy(h: DirectTestHarness):
    """Test extraction on tricky phrasing."""
    print("\n=== 12: Extraction accuracy — nuanced phrasing ===")
    orch, phone = h.new_orchestrator("0000014")
    converse(orch, phone, [
        "שלום, שמי יוסי כהן ואני מתעניין בדירה להשכרה. יש לי תקציב של כ-3500 עד 4000 שח. "
        "אני מתכנן לעבור בחודש הקרוב ואשמח מאוד לתאם ביקור.",
    ])
    lead = h.load_lead(phone)
    _show(lead)
    verdict(lead.get("name") is not None, f"name extracted: {lead.get('name')}")
    verdict(lead.get("intent", {}).get("type") == "rent", "intent = rent")
    b_max = lead.get("criteria", {}).get("budget_max")
    b_min = lead.get("criteria", {}).get("budget_min")
    verdict(b_max is not None, f"budget_max = {b_max}")
    if b_min is not None:
        verdict(True, f"budget_min = {b_min}")
    else:
        warn("budget_min not captured")
    verdict(lead.get("criteria", {}).get("timeframe") is not None, f"timeframe = {lead.get('criteria', {}).get('timeframe')}")
    verdict(lead.get("criteria", {}).get("wants_visit") is True, "wants_visit = True")


# ── Helpers ──────────────────────────────────────────────────────────


def _show(lead: dict):
    for key in ("status", "score", "name", "notified_at", "closed_at"):
        print(f"  {key}: {lead.get(key)}")
    print(f"  intent: {lead.get('intent', {}).get('type')}")
    for key in ("budget_min", "budget_max", "wants_visit", "timeframe", "equity_amount"):
        print(f"  {key}: {lead.get('criteria', {}).get(key)}")
    print(f"  opted_out: {lead.get('signals', {}).get('opted_out')}")


# ── Main ──────────────────────────────────────────────────────────────

SCENARIOS = {
    1: scenario_1_renter_qualifies,
    2: scenario_2_closed_static,
    3: scenario_3_not_interested,
    4: scenario_4_disqualified_static,
    5: scenario_5_english_renter,
    6: scenario_6_dense_message,
    7: scenario_7_buy_mismatch,
    8: scenario_8_property_qa,
    9: scenario_9_gibberish,
    10: scenario_10_gradual_info,
    11: scenario_11_low_budget,
    12: scenario_12_extraction_accuracy,
}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Direct orchestrator tests (no Twilio)")
    parser.add_argument("--scenario", "-s", type=int, nargs="*", help="Run specific scenario(s) by number")
    args = parser.parse_args()

    print("=" * 60)
    print("Direct Orchestrator Tests (no Twilio, no HTTP)")
    print("Uses real LLM, real config, temp storage")
    print("=" * 60)

    harness = DirectTestHarness()
    print(f"Property type: {harness.property_type}, asking price: {harness.asking_price}")

    to_run = args.scenario if args.scenario else sorted(SCENARIOS.keys())

    try:
        for num in to_run:
            if num in SCENARIOS:
                SCENARIOS[num](harness)
            else:
                print(f"\n  Unknown scenario {num}, skipping")
    finally:
        harness.cleanup()

    print("\n" + "=" * 60)
    print(f"RESULTS:  {PASS_COUNT} passed  |  {FAIL_COUNT} failed  |  {WARN_COUNT} warnings")
    print("=" * 60)
    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
