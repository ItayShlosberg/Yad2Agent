"""Tests for conversation end-state logic with the new architecture.

StatusEngine determines qualification; orchestrator handles notification + closing.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.core.config import (
    QualifyingConfig, QualifyingField, ScoringConfig, StatusRulesConfig,
)
from src.models.extraction import ExtractedFields
from src.models.lead import Lead
from src.services.notifier import NotificationService
from src.services.orchestrator import ConversationOrchestrator, _STATIC_CLOSED, _STATIC_DISQUALIFIED
from src.services.scorer import LeadScorer
from src.services.status_engine import StatusEngine
from src.services.store import ConversationStore


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    d = tmp_path / "storage" / "test_property"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def store(storage_dir: Path) -> ConversationStore:
    return ConversationStore(storage_dir)


@pytest.fixture
def qualifying() -> QualifyingConfig:
    return QualifyingConfig(
        fields_by_type={
            "rent": [
                QualifyingField(name="intent", description="buy or rent", required=True, priority=1),
                QualifyingField(name="budget_range", description="budget", required=True, priority=2),
            ],
        },
        scoring=ScoringConfig(),
        status_rules=StatusRulesConfig(min_turns=2, qualified_max_missing=2),
    )


@pytest.fixture
def scorer(qualifying: QualifyingConfig) -> LeadScorer:
    return LeadScorer(qualifying)


@pytest.fixture
def status_engine(qualifying: QualifyingConfig) -> StatusEngine:
    return StatusEngine(qualifying=qualifying, property_type="rent", asking_price=3800)


def _make_orchestrator(
    store: ConversationStore,
    scorer: LeadScorer,
    status_engine: StatusEngine,
    qualifying: QualifyingConfig,
    reply_text: str = "Thank you!",
    extracted: ExtractedFields | None = None,
    notifier: NotificationService | None = None,
) -> ConversationOrchestrator:
    mock_llm = MagicMock()
    mock_llm.get_reply.return_value = reply_text
    mock_llm.get_extraction.return_value = extracted or ExtractedFields()

    return ConversationOrchestrator(
        store=store,
        llm=mock_llm,
        scorer=scorer,
        status_engine=status_engine,
        qualifying=qualifying,
        notifier=notifier,
        property_name="test_property",
    )


class TestClosedLeadGetsStaticReply:
    def test_closed_lead_no_llm_call(self, store, scorer, status_engine, qualifying):
        phone = "whatsapp:+972501111111"
        lead = Lead(phone=phone, status="closed", notified_at="2026-01-01T00:00:00Z", closed_at="2026-01-01T00:00:00Z")
        store.save_lead(lead)

        orch = _make_orchestrator(store, scorer, status_engine, qualifying)
        result = orch.handle_message(phone, "hello again")

        assert result.text == _STATIC_CLOSED
        orch._llm.get_reply.assert_not_called()


class TestDisqualifiedLeadGetsStaticReply:
    def test_disqualified_lead_no_llm_call(self, store, scorer, status_engine, qualifying):
        phone = "whatsapp:+972502222222"
        lead = Lead(phone=phone, status="disqualified")
        store.save_lead(lead)

        orch = _make_orchestrator(store, scorer, status_engine, qualifying)
        result = orch.handle_message(phone, "I changed my mind")

        assert result.text == _STATIC_DISQUALIFIED
        orch._llm.get_reply.assert_not_called()


class TestQualifiedLeadTriggersNotification:
    def test_notification_and_close(self, store, scorer, status_engine, qualifying):
        phone = "whatsapp:+972503333333"
        mock_notifier = MagicMock(spec=NotificationService)
        mock_notifier.notify_owner.return_value = True

        store.append_message(phone, "inbound", "Hi, is the apartment available?")
        store.append_message(phone, "outbound", "Yes it is!")

        extracted = ExtractedFields(intent="rent", budget_max=4000)
        orch = _make_orchestrator(
            store, scorer, status_engine, qualifying,
            extracted=extracted, notifier=mock_notifier,
        )

        result = orch.handle_message(phone, "I'd like to visit")

        mock_notifier.notify_owner.assert_called_once()
        lead = store.load_lead(phone)
        assert lead.status == "closed"
        assert lead.notified_at is not None
        assert lead.closed_at is not None
        assert "אעביר את הפרטים" in result.text


class TestQualifiedLeadNotNotifiedTwice:
    def test_already_notified_skips(self, store, scorer, status_engine, qualifying):
        phone = "whatsapp:+972504444444"
        lead = Lead(phone=phone, status="closed", notified_at="2026-01-01T00:00:00Z", closed_at="2026-01-01T00:00:00Z")
        store.save_lead(lead)

        mock_notifier = MagicMock(spec=NotificationService)
        orch = _make_orchestrator(store, scorer, status_engine, qualifying, notifier=mock_notifier)
        orch.handle_message(phone, "any follow-up")

        mock_notifier.notify_owner.assert_not_called()
