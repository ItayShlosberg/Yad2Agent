"""
Conversation orchestrator — the central workflow that ties all services together.

Each inbound message goes through:
  persist → load state → LLM reply → extract → score → persist → return reply
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import quote

from src.services.listing import ListingLoader
from src.services.llm_service import LLMService
from src.services.scorer import LeadScorer
from src.services.store import ConversationStore

log = logging.getLogger(__name__)

SEND_MEDIA_MARKER = "[SEND_MEDIA]"


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
        listing: ListingLoader | None = None,
        media_base_url: str = "",
    ) -> None:
        self._store = store
        self._llm = llm
        self._scorer = scorer
        self._listing = listing
        self._media_base_url = media_base_url

    def _build_media_urls(self) -> list[str]:
        if not self._listing or not self._listing.has_media or not self._media_base_url:
            return []
        base = self._media_base_url.rstrip("/")
        return [
            f"{base}/media/{quote(f.name)}"
            for f in self._listing.media_files
        ]

    def handle_message(self, sender: str, body: str) -> OrchestratorReply:
        """
        Process a single inbound WhatsApp message.

        Returns an OrchestratorReply with the reply text and optional media URLs.
        """
        log.info(
            "Inbound  | from=%s  body=%s", sender, body,
            extra={"event": "inbound", "phone": sender, "direction": "inbound"},
        )

        self._store.append_message(sender, "inbound", body)

        conversation = self._store.load_conversation(sender)
        lead = self._store.load_lead(sender)

        reply_text, extracted = self._llm.get_reply_and_extraction(conversation, lead)

        lead = self._scorer.apply_extraction(lead, extracted)
        self._store.save_lead(lead)

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

        self._store.append_message(sender, "outbound", reply_text)

        log.info(
            "Outbound | to=%s  reply=%s", sender, reply_text,
            extra={"event": "outbound", "phone": sender, "direction": "outbound"},
        )

        missing = lead.missing_fields(self._scorer._qualifying)
        log.info(
            "Lead     | phone=%s  status=%s  score=%s  missing=%s",
            lead.phone, lead.status, lead.score, missing,
            extra={"event": "lead_update", "phone": lead.phone,
                   "status": lead.status, "score": lead.score},
        )

        if lead.status == "qualified":
            log.info(
                "QUALIFIED LEAD | phone=%s  score=%s  name=%s",
                lead.phone, lead.score, lead.name or "unknown",
                extra={"event": "lead_qualified", "phone": lead.phone, "score": lead.score},
            )

        return OrchestratorReply(text=reply_text, media_urls=media_urls)
