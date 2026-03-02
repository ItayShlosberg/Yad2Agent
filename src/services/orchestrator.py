"""
Conversation orchestrator — the central workflow that ties all services together.

Each inbound message goes through:
  persist → load state → LLM reply → extract → score → persist → return reply
"""

from __future__ import annotations

import logging

from src.services.llm_service import LLMService
from src.services.scorer import LeadScorer
from src.services.store import ConversationStore

log = logging.getLogger(__name__)


class ConversationOrchestrator:
    """Coordinates the full message-handling pipeline."""

    def __init__(
        self,
        store: ConversationStore,
        llm: LLMService,
        scorer: LeadScorer,
    ) -> None:
        self._store = store
        self._llm = llm
        self._scorer = scorer

    def handle_message(self, sender: str, body: str) -> str:
        """
        Process a single inbound WhatsApp message and return the reply text.

        Steps:
        1. Persist the inbound message.
        2. Load conversation history and lead state.
        3. Ask the LLM for a reply and field extraction.
        4. Apply extracted fields, recompute score.
        5. Persist the outbound message and updated lead.
        6. Return the reply string.
        """
        log.info("Inbound  | from=%s  body=%s", sender, body)

        self._store.append_message(sender, "inbound", body)

        conversation = self._store.load_conversation(sender)
        lead = self._store.load_lead(sender)

        reply_text, extracted = self._llm.get_reply_and_extraction(conversation, lead)

        lead = self._scorer.apply_extraction(lead, extracted)
        self._store.save_lead(lead)

        self._store.append_message(sender, "outbound", reply_text)

        log.info("Outbound | to=%s  reply=%s", sender, reply_text)
        log.info(
            "Lead     | phone=%s  status=%s  score=%s  missing=%s",
            lead.phone, lead.status, lead.score,
            lead.missing_fields(self._scorer._qualifying),
        )

        if lead.status == "qualified":
            log.info(
                "QUALIFIED LEAD | phone=%s  score=%s  name=%s",
                lead.phone, lead.score, lead.name or "unknown",
            )

        return reply_text
