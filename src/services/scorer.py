"""
Config-driven lead scoring and field application.

Scoring rules and status thresholds come from config/qualifying.yaml
so they can be tuned without touching code.
"""

from __future__ import annotations

import logging

from src.core.config import QualifyingConfig
from src.models.lead import Lead

log = logging.getLogger(__name__)

_FIELD_SETTERS: dict[str, callable] = {
    "intent": lambda lead, v: setattr(lead.intent, "type", v),
    "budget_min": lambda lead, v: setattr(lead.criteria, "budget_min", int(v)) if v else None,
    "budget_max": lambda lead, v: setattr(lead.criteria, "budget_max", int(v)) if v else None,
    "budget_currency": lambda lead, v: setattr(lead.criteria, "budget_currency", v),
    "has_mortgage_approval": lambda lead, v: setattr(lead.criteria, "has_mortgage_approval", bool(v)),
    "equity_amount": lambda lead, v: setattr(lead.criteria, "equity_amount", int(v)) if v else None,
    "timeframe": lambda lead, v: setattr(lead.criteria, "timeframe", v),
    "desired_entry_date": lambda lead, v: setattr(lead.criteria, "desired_entry_date", v),
    "wants_visit": lambda lead, v: setattr(lead.criteria, "wants_visit", bool(v)),
    "rooms_min": lambda lead, v: setattr(lead.context, "rooms_min", int(v)) if v else None,
    "rooms_max": lambda lead, v: setattr(lead.context, "rooms_max", int(v)) if v else None,
    "neighborhoods": lambda lead, v: setattr(lead.context, "neighborhoods", v if isinstance(v, list) else [v]),
    "must_haves": lambda lead, v: setattr(lead.context, "must_haves", v if isinstance(v, list) else [v]),
    "nice_to_haves": lambda lead, v: setattr(lead.context, "nice_to_haves", v if isinstance(v, list) else [v]),
    "name": lambda lead, v: setattr(lead, "name", v),
    "red_flags": lambda lead, v: setattr(lead.signals, "red_flags", v if isinstance(v, list) else [v]),
    "notes": lambda lead, v: setattr(lead.signals, "notes", v),
    "status": lambda lead, v: setattr(lead, "status", v) if v in ("qualified", "disqualified") else None,
}


class LeadScorer:
    """Applies extracted fields and computes a lead score."""

    def __init__(self, qualifying: QualifyingConfig) -> None:
        self._qualifying = qualifying

    def apply_extraction(self, lead: Lead, extracted: dict) -> Lead:
        """Merge extracted fields into the Lead and recompute score."""
        for key, value in extracted.items():
            if value is None:
                continue
            setter = _FIELD_SETTERS.get(key)
            if setter:
                try:
                    setter(lead, value)
                except (ValueError, TypeError) as exc:
                    log.warning("Could not apply field %s=%r: %s", key, value, exc)
            else:
                log.debug("Unknown extracted field: %s", key)

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
