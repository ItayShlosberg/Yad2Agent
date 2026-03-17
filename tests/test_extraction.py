"""Unit tests for the Pydantic ExtractedFields model."""

import pytest

from src.models.extraction import ExtractedFields


def test_empty_json():
    fields = ExtractedFields.model_validate_json("{}")
    assert fields.intent is None
    assert fields.budget_min is None
    assert fields.name is None
    assert fields.user_opted_out is None


def test_full_parse():
    raw = """
    {
        "intent": "buy",
        "budget_min": 2000000,
        "budget_max": 2500000,
        "budget_currency": "ILS",
        "has_mortgage_approval": true,
        "equity_amount": 800000,
        "timeframe": "1-3 months",
        "desired_entry_date": "2026-06-01",
        "wants_visit": true,
        "rooms_min": 3,
        "rooms_max": 5,
        "neighborhoods": ["Nofei Ben Shemen"],
        "must_haves": ["parking", "balcony"],
        "nice_to_haves": ["storage"],
        "name": "Danny",
        "red_flags": [],
        "notes": "Seems serious buyer",
        "user_opted_out": false
    }
    """
    fields = ExtractedFields.model_validate_json(raw)
    assert fields.intent == "buy"
    assert fields.budget_min == 2000000
    assert fields.budget_max == 2500000
    assert fields.wants_visit is True
    assert fields.user_opted_out is False
    assert fields.neighborhoods == ["Nofei Ben Shemen"]


def test_partial_parse():
    raw = '{"intent": "rent", "budget_max": 5000, "name": null}'
    fields = ExtractedFields.model_validate_json(raw)
    assert fields.intent == "rent"
    assert fields.budget_max == 5000
    assert fields.name is None
    assert fields.wants_visit is None


def test_all_null_fields():
    fields = ExtractedFields()
    data = fields.model_dump(exclude_none=True)
    assert data == {}


def test_invalid_intent_rejected():
    with pytest.raises(Exception):
        ExtractedFields.model_validate_json('{"intent": "invest"}')


def test_opted_out_true():
    fields = ExtractedFields.model_validate_json('{"user_opted_out": true}')
    assert fields.user_opted_out is True


def test_model_dump_excludes_none():
    fields = ExtractedFields(intent="buy", budget_max=2500000)
    data = fields.model_dump(exclude_none=True)
    assert "intent" in data
    assert "budget_max" in data
    assert "name" not in data
    assert "wants_visit" not in data
