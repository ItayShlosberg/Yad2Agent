"""
Config-driven lead scoring and field application.

The scorer is a pure data merger: it takes extracted fields, applies them
to the Lead, and recomputes the numeric score.  It does NOT make status
decisions — that responsibility belongs to the StatusEngine.
"""

from __future__ import annotations

import logging

from src.core.config import QualifyingConfig
from src.models.extraction import ExtractedFields
from src.models.lead import Lead

log = logging.getLogger(__name__)

_FLAT_TO_LEAD: dict[str, tuple[str, str]] = {
    "intent": ("intent", "type"),
    "budget_min": ("criteria", "budget_min"),
    "budget_max": ("criteria", "budget_max"),
    "budget_currency": ("criteria", "budget_currency"),
    "has_mortgage_approval": ("criteria", "has_mortgage_approval"),
    "equity_amount": ("criteria", "equity_amount"),
    "timeframe": ("criteria", "timeframe"),
    "desired_entry_date": ("criteria", "desired_entry_date"),
    "wants_visit": ("criteria", "wants_visit"),
    "rooms_min": ("context", "rooms_min"),
    "rooms_max": ("context", "rooms_max"),
    "neighborhoods": ("context", "neighborhoods"),
    "must_haves": ("context", "must_haves"),
    "nice_to_haves": ("context", "nice_to_haves"),
    "red_flags": ("signals", "red_flags"),
    "notes": ("signals", "notes"),
}


class LeadScorer:
    """Applies extracted fields and computes a lead score."""

    def __init__(self, qualifying: QualifyingConfig) -> None:
        self._qualifying = qualifying

    def apply_extraction(self, lead: Lead, extracted: ExtractedFields) -> Lead:
        """Merge extracted fields into the Lead and recompute score."""
        data = extracted.model_dump(exclude_none=True)

        if "name" in data:
            lead.name = data.pop("name")

        if "user_opted_out" in data:
            lead.signals.opted_out = data.pop("user_opted_out")

        for field_name, value in data.items():
            mapping = _FLAT_TO_LEAD.get(field_name)
            if not mapping:
                log.debug("Unknown extracted field: %s", field_name)
                continue
            sub_model_name, attr = mapping
            try:
                sub = getattr(lead, sub_model_name)
                setattr(sub, attr, value)
            except (ValueError, TypeError, AttributeError) as exc:
                log.warning("Could not apply field %s=%r: %s", field_name, value, exc)

        lead.score = self._compute_score(lead)
        return lead

    def _compute_score(self, lead: Lead) -> int:
        s = self._qualifying.scoring
        total_required = len([f for f in self._qualifying.fields if f.required])
        filled = total_required - len(lead.missing_fields(self._qualifying))
        red_flag_penalty = len(lead.signals.red_flags) * s.red_flag_penalty
        visit_bonus = s.visit_bonus if lead.criteria.wants_visit else 0
        raw = filled * s.points_per_field + visit_bonus - red_flag_penalty
        return max(0, min(s.max_score, raw))
