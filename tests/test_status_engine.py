"""Exhaustive unit tests for the rule-based StatusEngine."""

import pytest

from src.core.config import QualifyingConfig, QualifyingField, ScoringConfig, StatusRulesConfig
from src.models.lead import Lead
from src.services.status_engine import StatusEngine


@pytest.fixture
def rent_qualifying() -> QualifyingConfig:
    return QualifyingConfig(
        fields_by_type={
            "rent": [
                QualifyingField(name="intent", description="buy or rent", required=True, priority=1),
                QualifyingField(name="budget_range", description="budget", required=True, priority=2),
                QualifyingField(name="timeframe", description="timeframe", required=True, priority=3),
                QualifyingField(name="wants_visit", description="visit", required=True, priority=4),
            ],
        },
        scoring=ScoringConfig(),
        status_rules=StatusRulesConfig(min_turns=2, qualified_max_missing=1, budget_floor_pct=0.6),
    )


@pytest.fixture
def buy_qualifying() -> QualifyingConfig:
    return QualifyingConfig(
        fields_by_type={
            "buy": [
                QualifyingField(name="intent", description="buy or rent", required=True, priority=1),
                QualifyingField(name="budget_range", description="budget", required=True, priority=2),
                QualifyingField(name="equity_amount", description="equity", required=True, priority=3),
                QualifyingField(name="timeframe", description="timeframe", required=True, priority=4),
                QualifyingField(name="wants_visit", description="visit", required=True, priority=5),
            ],
        },
        scoring=ScoringConfig(),
        status_rules=StatusRulesConfig(min_turns=2, qualified_max_missing=1, budget_floor_pct=0.6),
    )


def _rent_engine(cfg: QualifyingConfig, asking_price: float = 3800) -> StatusEngine:
    return StatusEngine(qualifying=cfg, property_type="rent", asking_price=asking_price)


def _buy_engine(cfg: QualifyingConfig, asking_price: float = 2500000) -> StatusEngine:
    return StatusEngine(qualifying=cfg, property_type="buy", asking_price=asking_price)


def _lead(**kwargs) -> Lead:
    defaults = {"phone": "whatsapp:+972500000001"}
    defaults.update(kwargs)
    return Lead(**defaults)


# ── Rent: qualification ──────────────────────────────────────────

class TestRentQualification:
    def test_qualifies_with_all_fields(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "rent"
        lead.criteria.budget_max = 4000
        lead.criteria.timeframe = "immediate"
        lead.criteria.wants_visit = True

        assert engine.evaluate(lead, inbound_count=3) == "qualified"

    def test_qualifies_with_one_missing(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "rent"
        lead.criteria.budget_max = 4000
        lead.criteria.timeframe = "immediate"
        # wants_visit missing — max_missing=1 so still qualifies

        assert engine.evaluate(lead, inbound_count=3) == "qualified"

    def test_does_not_qualify_with_two_missing(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "rent"
        lead.criteria.budget_max = 4000
        # timeframe + wants_visit missing = 2 > max_missing=1

        assert engine.evaluate(lead, inbound_count=3) == "collecting"

    def test_does_not_qualify_before_min_turns(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "rent"
        lead.criteria.budget_max = 4000
        lead.criteria.timeframe = "immediate"
        lead.criteria.wants_visit = True

        assert engine.evaluate(lead, inbound_count=1) == "collecting"


# ── Rent: disqualification ───────────────────────────────────────

class TestRentDisqualification:
    def test_opted_out(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.signals.opted_out = True

        assert engine.evaluate(lead, inbound_count=2) == "disqualified"

    def test_opted_out_blocked_before_min_turns(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.signals.opted_out = True

        assert engine.evaluate(lead, inbound_count=1) == "collecting"

    def test_intent_mismatch(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "buy"

        assert engine.evaluate(lead, inbound_count=2) == "disqualified"

    def test_budget_too_low(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying, asking_price=3800)
        lead = _lead()
        lead.criteria.budget_max = 2000  # 2000 < 3800 * 0.6 = 2280

        assert engine.evaluate(lead, inbound_count=2) == "disqualified"

    def test_budget_just_above_floor(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying, asking_price=3800)
        lead = _lead()
        lead.criteria.budget_max = 2300  # 2300 > 3800 * 0.6 = 2280

        assert engine.evaluate(lead, inbound_count=2) == "collecting"

    def test_no_disqualification_without_data(self, rent_qualifying):
        """Empty lead should stay collecting, not be disqualified."""
        engine = _rent_engine(rent_qualifying)
        lead = _lead()

        assert engine.evaluate(lead, inbound_count=3) == "collecting"


# ── Buy: qualification ───────────────────────────────────────────

class TestBuyQualification:
    def test_qualifies_with_all_fields(self, buy_qualifying):
        engine = _buy_engine(buy_qualifying)
        lead = _lead()
        lead.intent.type = "buy"
        lead.criteria.budget_max = 2500000
        lead.criteria.equity_amount = 800000
        lead.criteria.timeframe = "1-3 months"
        lead.criteria.wants_visit = True

        assert engine.evaluate(lead, inbound_count=3) == "qualified"

    def test_qualifies_missing_visit(self, buy_qualifying):
        engine = _buy_engine(buy_qualifying)
        lead = _lead()
        lead.intent.type = "buy"
        lead.criteria.budget_max = 2500000
        lead.criteria.equity_amount = 800000
        lead.criteria.timeframe = "1-3 months"

        assert engine.evaluate(lead, inbound_count=3) == "qualified"

    def test_does_not_qualify_missing_equity_and_visit(self, buy_qualifying):
        engine = _buy_engine(buy_qualifying)
        lead = _lead()
        lead.intent.type = "buy"
        lead.criteria.budget_max = 2500000
        lead.criteria.timeframe = "1-3 months"

        assert engine.evaluate(lead, inbound_count=3) == "collecting"


# ── Terminal states ──────────────────────────────────────────────

class TestTerminalStates:
    def test_already_closed(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead(status="closed")
        assert engine.evaluate(lead, inbound_count=5) == "closed"

    def test_already_qualified(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead(status="qualified")
        assert engine.evaluate(lead, inbound_count=5) == "qualified"

    def test_already_disqualified(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead(status="disqualified")
        assert engine.evaluate(lead, inbound_count=5) == "disqualified"


# ── Priority: disqualify before qualify ──────────────────────────

class TestDisqualifyBeforeQualify:
    def test_opted_out_even_with_all_fields(self, rent_qualifying):
        """If user opted out, don't qualify even if all fields are filled."""
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "rent"
        lead.criteria.budget_max = 4000
        lead.criteria.timeframe = "immediate"
        lead.criteria.wants_visit = True
        lead.signals.opted_out = True

        assert engine.evaluate(lead, inbound_count=3) == "disqualified"

    def test_intent_mismatch_even_with_all_fields(self, rent_qualifying):
        engine = _rent_engine(rent_qualifying)
        lead = _lead()
        lead.intent.type = "buy"
        lead.criteria.budget_max = 4000
        lead.criteria.timeframe = "immediate"
        lead.criteria.wants_visit = True

        assert engine.evaluate(lead, inbound_count=3) == "disqualified"
