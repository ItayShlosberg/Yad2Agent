"""
File-based persistence for conversations and lead state.

Layout:
  storage/
  └── 972546487753/              # phone number (digits only)
      ├── conversation.json      # ordered list of messages
      └── lead.json              # current Lead snapshot
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from src.models.lead import Lead
from src.models.message import Message

log = logging.getLogger(__name__)


class ConversationStore:
    """CRUD operations backed by per-phone JSON files."""

    def __init__(self, storage_dir: Path) -> None:
        self._root = storage_dir
        self._root.mkdir(parents=True, exist_ok=True)

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _phone_to_dirname(phone: str) -> str:
        return re.sub(r"\D", "", phone)

    def _lead_dir(self, phone: str) -> Path:
        d = self._root / self._phone_to_dirname(phone)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── Conversation ───────────────────────────────────────────────

    def load_conversation(self, phone: str) -> list[dict]:
        path = self._lead_dir(phone) / "conversation.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return []

    def append_message(self, phone: str, direction: str, body: str) -> None:
        convo = self.load_conversation(phone)
        msg = Message(direction=direction, body=body)
        convo.append(msg.model_dump())
        path = self._lead_dir(phone) / "conversation.json"
        path.write_text(json.dumps(convo, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── Lead state ─────────────────────────────────────────────────

    def load_lead(self, phone: str) -> Lead:
        path = self._lead_dir(phone) / "lead.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return Lead(**data)
        return Lead(phone=phone)

    def save_lead(self, lead: Lead) -> None:
        path = self._lead_dir(lead.phone) / "lead.json"
        path.write_text(
            lead.model_dump_json(indent=2, exclude_none=False),
            encoding="utf-8",
        )
        log.info("Lead saved | phone=%s  score=%s", lead.phone, lead.score)
