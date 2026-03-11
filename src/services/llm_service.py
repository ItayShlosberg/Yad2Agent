"""
OpenAI GPT wrapper.

Uses a two-call strategy:
  1. Reply call  — plain text conversation (GPT-4o).
  2. Extract call — pure data parsing from the user's message (GPT-4o-mini).

The extraction call sees ONLY the user's message and current lead state.
It does NOT see the agent's reply or make status judgments.
"""

from __future__ import annotations

import logging

from openai import OpenAI
from pydantic import ValidationError

from src.core.config import LLMConfig
from src.models.extraction import ExtractedFields
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

    def get_reply(
        self,
        conversation: list[dict],
        lead: Lead,
        next_field_hint: str = "",
    ) -> str:
        """Generate a conversational reply."""
        messages = self._prompts.build_messages(conversation, lead, next_field_hint)
        return self._call_reply(messages)

    def get_extraction(self, user_message: str, lead: Lead) -> ExtractedFields:
        """Extract structured fields from the latest user message."""
        if not user_message:
            return ExtractedFields()
        return self._call_extraction(user_message, lead)

    # ── Internals ──────────────────────────────────────────────────

    def _call_reply(self, messages: list[dict]) -> str:
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

    def _call_extraction(self, user_message: str, lead: Lead) -> ExtractedFields:
        cfg = self._cfg.extraction
        raw = "{}"
        try:
            context = f"Lead so far: {lead.filled_summary()}"
            response = self._client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": self._prompts.extraction_prompt()},
                    {"role": "user", "content": f"{context}\n\nUser message: {user_message}"},
                ],
                response_format={"type": "json_object"},
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )
            raw = response.choices[0].message.content or "{}"
            log.info("Extraction result: %s", raw[:300])
            return ExtractedFields.model_validate_json(raw)
        except ValidationError as exc:
            log.warning("Extraction validation failed — raw=%s err=%s", raw, exc)
            return ExtractedFields()
        except Exception as exc:
            log.error("Extraction call failed: %s", exc, exc_info=True)
            return ExtractedFields()
