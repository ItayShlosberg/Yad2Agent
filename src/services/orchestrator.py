"""
Conversation orchestrator — the central workflow that ties all services together.

Pipeline per inbound message:
  persist → rate limit → status check → hint → reply LLM → extract LLM
  → merge fields → status engine → [notify] → persist → return reply

Closed/disqualified leads get a static reply without calling the LLM.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote

from src.core.config import QualifyingConfig
from src.services.listing import ListingLoader
from src.services.llm_service import LLMService
from src.services.notifier import NotificationService
from src.services.rate_limiter import RateLimiter
from src.services.scorer import LeadScorer
from src.services.status_engine import StatusEngine
from src.services.store import ConversationStore

log = logging.getLogger(__name__)

SEND_MEDIA_MARKER = "[SEND_MEDIA]"

_STATIC_CLOSED = (
    "הפרטים שלך כבר הועברו לבעל הדירה והוא ייצור איתך קשר בהקדם. "
    "אם יש לך שאלות נוספות, אל תהסס לשלוח הודעה."
)
_STATIC_DISQUALIFIED = (
    "תודה על ההתעניינות! אם בעתיד תרצה לחזור לנושא, אני כאן."
)


@dataclass
class OrchestratorReply:
    text: str
    media_urls: list[str] = field(default_factory=list)


class ConversationOrchestrator:
    """Coordinates the full message-handling pipeline."""

    def __init__(
        self,
        store: ConversationStore,
        llm: LLMService,
        scorer: LeadScorer,
        status_engine: StatusEngine,
        qualifying: QualifyingConfig,
        listing: ListingLoader | None = None,
        media_base_url: str = "",
        notifier: NotificationService | None = None,
        rate_limiter: RateLimiter | None = None,
        property_name: str = "",
    ) -> None:
        self._store = store
        self._llm = llm
        self._scorer = scorer
        self._status_engine = status_engine
        self._qualifying = qualifying
        self._listing = listing
        self._media_base_url = media_base_url
        self._notifier = notifier
        self._rate_limiter = rate_limiter
        self._property_name = property_name

    def _build_media_urls(self) -> list[str]:
        if not self._listing or not self._listing.has_media or not self._media_base_url:
            return []
        base = self._media_base_url.rstrip("/")
        return [
            f"{base}/media/{quote(f.name)}"
            for f in self._listing.media_files
        ]

    # ── Hint generation ───────────────────────────────────────────

    def _compute_hint(self, lead, inbound_count: int) -> str:
        """Return a directed hint for the reply LLM based on what's missing."""
        missing = lead.missing_fields(self._qualifying)

        if not missing:
            return (
                "[All key info collected] Summarize what you know about this lead "
                "(intent, budget, timeframe, visit interest). Offer to pass their "
                "details to the owner and wrap up warmly."
            )

        top = missing[0]
        field_name = top.split(" (")[0]
        field_desc = top.split("(")[1].rstrip(")") if "(" in top else field_name

        if inbound_count <= 1:
            return (
                f"[Next question hint] This is an early message. "
                f"Welcome the lead warmly. If natural, try to learn: {field_desc}. "
                f"Don't force it — answering their question comes first."
            )

        return (
            f"[Next question hint] Naturally work into the conversation: {field_desc}. "
            f"Don't ask directly — weave it in after addressing the user's message."
        )

    # ── Main pipeline ─────────────────────────────────────────────

    def handle_message(self, sender: str, body: str) -> OrchestratorReply:
        log.info(
            "Inbound  | from=%s  body=%s", sender, body,
            extra={"event": "inbound", "phone": sender, "direction": "inbound"},
        )

        self._store.append_message(sender, "inbound", body)
        lead = self._store.load_lead(sender)

        # Rate limit (applies to all leads, including closed)
        if self._rate_limiter and self._rate_limiter.is_limited(sender):
            cooldown = self._rate_limiter.cooldown_message
            log.info("Rate limited | phone=%s", sender, extra={"event": "rate_limited", "phone": sender})
            self._store.append_message(sender, "outbound", cooldown)
            return OrchestratorReply(text=cooldown)

        # Early exits for terminal states
        if lead.status == "closed":
            log.info("Lead already closed — static reply", extra={"event": "static_closed", "phone": sender})
            self._store.append_message(sender, "outbound", _STATIC_CLOSED)
            return OrchestratorReply(text=_STATIC_CLOSED)

        if lead.status == "disqualified":
            log.info("Lead disqualified — static reply", extra={"event": "static_disqualified", "phone": sender})
            self._store.append_message(sender, "outbound", _STATIC_DISQUALIFIED)
            return OrchestratorReply(text=_STATIC_DISQUALIFIED)

        # Active conversation
        conversation = self._store.load_conversation(sender)
        inbound_count = sum(1 for m in conversation if m.get("direction") == "inbound")

        # Step 1: Compute hint for reply LLM
        hint = self._compute_hint(lead, inbound_count)

        # Step 2: Reply LLM (with directed hint)
        reply_text = self._llm.get_reply(conversation, lead, next_field_hint=hint)

        # Step 3: Extraction LLM (pure data parsing from user message)
        extracted = self._llm.get_extraction(body, lead)

        # Step 4: Merge extracted fields into lead
        lead = self._scorer.apply_extraction(lead, extracted)

        # Step 5: Handle media
        media_urls: list[str] = []
        if SEND_MEDIA_MARKER in reply_text:
            reply_text = reply_text.replace(SEND_MEDIA_MARKER, "").strip()
            reply_text = re.sub(r"\n{3,}", "\n\n", reply_text)
            media_urls = self._build_media_urls()
            if media_urls:
                log.info(
                    "Attaching %d media files to reply", len(media_urls),
                    extra={"event": "media_attached", "phone": sender},
                )

        # Step 6: Rule-based status engine
        new_status = self._status_engine.evaluate(lead, inbound_count)

        if new_status != lead.status:
            old = lead.status
            lead.status = new_status
            log.info(
                "Status change | phone=%s  %s → %s",
                sender, old, new_status,
                extra={"event": "status_change", "phone": sender},
            )

        # Step 7: Qualification → notify + close
        if lead.status == "qualified" and lead.notified_at is None:
            now = datetime.now(timezone.utc).isoformat()
            if self._notifier:
                self._notifier.notify_owner(lead, self._property_name)
            lead.notified_at = now
            lead.closed_at = now
            lead.status = "closed"
            reply_text += "\n\nאעביר את הפרטים שלך לבעל הדירה והוא ייצור איתך קשר בהקדם."
            log.info(
                "QUALIFIED → CLOSED | phone=%s  score=%s  name=%s",
                lead.phone, lead.score, lead.name or "unknown",
                extra={"event": "lead_qualified_closed", "phone": lead.phone, "score": lead.score},
            )

        # Step 8: Persist and return
        self._store.save_lead(lead)
        self._store.append_message(sender, "outbound", reply_text)

        log.info(
            "Outbound | to=%s  reply=%s", sender, reply_text[:200],
            extra={"event": "outbound", "phone": sender, "direction": "outbound"},
        )

        missing = lead.missing_fields(self._qualifying)
        log.info(
            "Lead     | phone=%s  status=%s  score=%s  missing=%s",
            lead.phone, lead.status, lead.score, missing,
            extra={"event": "lead_update", "phone": lead.phone,
                   "status": lead.status, "score": lead.score},
        )

        return OrchestratorReply(text=reply_text, media_urls=media_urls)
