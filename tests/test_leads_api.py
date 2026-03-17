"""Tests for the GET /leads endpoint."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from src.api.leads import router as leads_router, init_leads


@pytest.fixture
def storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory with sample data."""
    # property_1 / phone_A — qualified lead
    p1a = tmp_path / "property_1" / "972501234567"
    p1a.mkdir(parents=True)
    (p1a / "lead.json").write_text(json.dumps({
        "phone": "whatsapp:+972501234567",
        "name": "Alice",
        "status": "qualified",
        "score": 85,
        "intent": {"type": "buy"},
        "criteria": {"budget_max": 2500000, "wants_visit": True},
        "notified_at": "2026-03-01T10:00:00Z",
        "closed_at": "2026-03-01T10:00:00Z",
    }), encoding="utf-8")
    (p1a / "conversation.json").write_text(json.dumps([
        {"direction": "inbound", "body": "Hi", "timestamp": "2026-03-01T09:00:00Z"},
        {"direction": "outbound", "body": "Hello!", "timestamp": "2026-03-01T09:00:05Z"},
        {"direction": "inbound", "body": "Budget 2.5M", "timestamp": "2026-03-01T09:05:00Z"},
    ]), encoding="utf-8")

    # property_2 / phone_B — collecting lead
    p2b = tmp_path / "property_2" / "972509876543"
    p2b.mkdir(parents=True)
    (p2b / "lead.json").write_text(json.dumps({
        "phone": "whatsapp:+972509876543",
        "name": "Bob",
        "status": "collecting",
        "score": 30,
        "intent": {"type": "rent"},
        "criteria": {"budget_max": 4000},
    }), encoding="utf-8")
    (p2b / "conversation.json").write_text(json.dumps([
        {"direction": "inbound", "body": "Hello", "timestamp": "2026-03-02T14:00:00Z"},
    ]), encoding="utf-8")

    return tmp_path


@pytest.fixture
def client(storage_dir: Path) -> TestClient:
    app = FastAPI()
    init_leads(storage_dir)
    app.include_router(leads_router)
    return TestClient(app)


def test_list_all_leads(client: TestClient):
    resp = client.get("/leads")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["property"] == "property_2"
    assert data[1]["property"] == "property_1"


def test_filter_by_status(client: TestClient):
    resp = client.get("/leads?status=qualified")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Alice"
    assert data[0]["status"] == "qualified"


def test_filter_by_property(client: TestClient):
    resp = client.get("/leads?property=property_2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Bob"


def test_filter_combined(client: TestClient):
    resp = client.get("/leads?status=collecting&property=property_1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 0


def test_empty_storage():
    app = FastAPI()
    with tempfile.TemporaryDirectory() as tmp:
        init_leads(Path(tmp))
        app.include_router(leads_router)
        with TestClient(app) as c:
            resp = c.get("/leads")
            assert resp.status_code == 200
            assert resp.json() == []


def test_lead_fields_present(client: TestClient):
    resp = client.get("/leads?status=qualified")
    data = resp.json()
    lead = data[0]
    assert "phone" in lead
    assert "property" in lead
    assert "name" in lead
    assert "status" in lead
    assert "score" in lead
    assert "intent" in lead
    assert "budget_max" in lead
    assert "messages" in lead
    assert "first_message" in lead
    assert "last_message" in lead
    assert "notified_at" in lead
    assert "closed_at" in lead
    assert lead["messages"] == 3
