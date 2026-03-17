"""Tests for Twilio signature validation."""

import hmac
import hashlib
import base64
from urllib.parse import urlencode

import pytest
from fastapi import FastAPI, Depends, Request, Response
from fastapi.testclient import TestClient

from src.api.security import init_security, verify_twilio_signature

AUTH_TOKEN = "test_auth_token_12345"
BASE_URL = "https://example.com"


def _make_app() -> FastAPI:
    """Create a minimal FastAPI app with a protected route."""
    app = FastAPI()

    @app.post("/webhook", dependencies=[Depends(verify_twilio_signature)])
    async def webhook(request: Request):
        return {"ok": True}

    return app


def _compute_signature(url: str, params: dict[str, str], token: str) -> str:
    """Compute a Twilio-compatible request signature."""
    s = url
    for key in sorted(params.keys()):
        s += key + params[key]
    mac = hmac.new(token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1)
    return base64.b64encode(mac.digest()).decode("utf-8")


class TestSignatureValidationDisabled:
    def test_passes_without_signature(self):
        init_security(auth_token=AUTH_TOKEN, enabled=False, public_base_url=BASE_URL)
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post("/webhook", data={"From": "test", "Body": "hello"})
            assert resp.status_code == 200


class TestSignatureValidationEnabled:
    def setup_method(self):
        init_security(auth_token=AUTH_TOKEN, enabled=True, public_base_url=BASE_URL)

    def test_rejects_missing_signature(self):
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post("/webhook", data={"From": "test", "Body": "hello"})
            assert resp.status_code == 403

    def test_rejects_invalid_signature(self):
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/webhook",
                data={"From": "test", "Body": "hello"},
                headers={"X-Twilio-Signature": "invalid_signature"},
            )
            assert resp.status_code == 403

    def test_accepts_valid_signature(self):
        app = _make_app()
        params = {"From": "whatsapp:+1234", "Body": "hi"}
        url = f"{BASE_URL}/webhook"
        sig = _compute_signature(url, params, AUTH_TOKEN)

        with TestClient(app) as client:
            resp = client.post(
                "/webhook",
                data=params,
                headers={"X-Twilio-Signature": sig},
            )
            assert resp.status_code == 200
