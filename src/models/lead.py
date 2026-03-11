"""
Lead data model — structured representation of a potential buyer / renter.

The Lead is incrementally populated through conversation.  Fields that the
agent actively asks about are driven by config/qualifying.yaml; passive fields
(like mortgage approval) are still stored if the lead volunteers them.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from src.core.config import QualifyingConfig


class Intent(BaseModel):
    type: Optional[str] = None  # "buy" | "rent"
    confidence: Optional[float] = None


class Criteria(BaseModel):
    budget_currency: Optional[str] = None
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    has_mortgage_approval: Optional[bool] = None
    equity_amount: Optional[int] = None
    timeframe: Optional[str] = None
    desired_entry_date: Optional[str] = None
    wants_visit: Optional[bool] = None


class Context(BaseModel):
    rooms_min: Optional[int] = None
    rooms_max: Optional[int] = None
    neighborhoods: List[str] = Field(default_factory=list)
    must_haves: List[str] = Field(default_factory=list)
    nice_to_haves: List[str] = Field(default_factory=list)


class Signals(BaseModel):
    red_flags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    opted_out: Optional[bool] = None


class Lead(BaseModel):
    phone: str
    name: Optional[str] = None
    status: str = "collecting"
    intent: Intent = Field(default_factory=Intent)
    criteria: Criteria = Field(default_factory=Criteria)
    context: Context = Field(default_factory=Context)
    signals: Signals = Field(default_factory=Signals)
    score: Optional[int] = None
    notified_at: Optional[str] = None
    closed_at: Optional[str] = None

    # ── Introspection helpers (config-driven) ──────────────────────

    def filled_summary(self) -> str:
        """Human-readable summary of collected data so far."""
        parts: list[str] = []
        if self.name:
            parts.append(f"Name: {self.name}")
        if self.intent.type:
            parts.append(f"Intent: {self.intent.type}")
        if self.criteria.budget_min or self.criteria.budget_max:
            lo = self.criteria.budget_min or "?"
            hi = self.criteria.budget_max or "?"
            cur = self.criteria.budget_currency or "ILS"
            parts.append(f"Budget: {lo}-{hi} {cur}")
        if self.criteria.has_mortgage_approval is not None:
            parts.append(f"Mortgage approved: {self.criteria.has_mortgage_approval}")
        if self.criteria.equity_amount:
            parts.append(f"Equity: {self.criteria.equity_amount}")
        if self.criteria.timeframe:
            parts.append(f"Timeframe: {self.criteria.timeframe}")
        if self.criteria.desired_entry_date:
            parts.append(f"Entry date: {self.criteria.desired_entry_date}")
        if self.criteria.wants_visit is not None:
            parts.append(f"Wants visit: {self.criteria.wants_visit}")
        if self.context.rooms_min or self.context.rooms_max:
            parts.append(f"Rooms: {self.context.rooms_min or '?'}-{self.context.rooms_max or '?'}")
        if self.context.neighborhoods:
            parts.append(f"Neighborhoods: {', '.join(self.context.neighborhoods)}")
        if self.signals.red_flags:
            parts.append(f"Red flags: {', '.join(self.signals.red_flags)}")
        if self.score is not None:
            parts.append(f"Score: {self.score}")
        return "\n".join(parts) if parts else "No data collected yet."

    def missing_fields(self, qualifying: QualifyingConfig) -> list[str]:
        """Return required qualifying fields that are still empty."""
        checkers: dict[str, bool] = {
            "intent": bool(self.intent.type),
            "budget_range": bool(self.criteria.budget_min or self.criteria.budget_max),
            "timeframe": bool(self.criteria.timeframe),
            "wants_visit": self.criteria.wants_visit is not None,
            "equity_amount": bool(self.criteria.equity_amount),
        }
        missing: list[str] = []
        for f in sorted(qualifying.fields, key=lambda x: x.priority):
            if f.required and not checkers.get(f.name, False):
                missing.append(f"{f.name} ({f.description})")
        return missing
