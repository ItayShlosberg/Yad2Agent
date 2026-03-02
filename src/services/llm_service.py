"""
OpenAI GPT wrapper.

Uses a two-call strategy:
  1. Reply call  — plain text (avoids Hebrew JSON encoding bugs).
  2. Extract call — structured JSON (English-only, fast, cheap model).
"""

from __future__ import annotations

import json
import logging

from openai import OpenAI

from src.core.config import LLMConfig
from src.models.lead import Lead
from src.services.prompts import PromptBuilder

log = logging.getLogger(__name__)


class LLMService:
    """Stateless service wrapping OpenAI chat completions."""

    def __init__(self, api_key: str, llm_config: LLMConfig, prompt_builder: PromptBuilder) -> None:
        self._client = OpenAI(api_key=api_key)
        self._cfg = llm_config
        self._prompts = prompt_builder

    # ── Public API ─────────────────────────────────────────────────

    def get_reply_and_extraction(
        self,
        conversation: list[dict],
        lead: Lead,
    ) -> tuple[str, dict]:
        """Return (reply_text, extracted_fields_dict)."""
        messages = self._prompts.build_messages(conversation, lead)

        reply = self._get_reply(messages)

        latest_user_msg = ""
        for msg in reversed(conversation):
            if msg["direction"] == "inbound":
                latest_user_msg = msg["body"]
                break

        extracted = self._extract_fields(latest_user_msg, lead) if latest_user_msg else {}
        return reply, extracted

    # ── Internals ──────────────────────────────────────────────────

    def _get_reply(self, messages: list[dict]) -> str:
        cfg = self._cfg.reply
        try:
            response = self._client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            reply = (response.choices[0].message.content or "").strip()
            log.info("GPT reply: %s", reply[:300])
            if not reply or len(reply) < 2:
                return self._cfg.fallback_message
            return reply
        except Exception as exc:
            log.error("GPT reply call failed: %s", exc)
            return self._cfg.fallback_message

    def _extract_fields(self, user_message: str, lead: Lead) -> dict:
        cfg = self._cfg.extraction
        try:
            context = f"Lead so far: {lead.filled_summary()}\nMissing: {', '.join(lead.missing_fields(self._prompts._qualifying))}"
            response = self._client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": self._prompts.extraction_prompt()},
                    {"role": "user", "content": f"{context}\n\nLatest message: {user_message}"},
                ],
                response_format={"type": "json_object"},
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            raw = response.choices[0].message.content or "{}"
            log.info("Extraction result: %s", raw[:300])
            return json.loads(raw)
        except Exception as exc:
            log.error("Extraction call failed: %s", exc)
            return {}
