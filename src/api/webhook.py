"""
Thin FastAPI route handlers.

All business logic lives in the orchestrator; routes only parse HTTP
and format the TwiML response.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Request, Response, status

from src.services.orchestrator import ConversationOrchestrator

router = APIRouter()

_orchestrator: ConversationOrchestrator | None = None


def init_routes(orchestrator: ConversationOrchestrator) -> None:
    """Called once at startup to inject the orchestrator dependency."""
    global _orchestrator
    _orchestrator = orchestrator


@router.get("/health")
async def health():
    return {"ok": True}


@router.post("/webhook")
async def twilio_whatsapp_webhook(request: Request):
    form = await request.form()
    sender = form.get("From", "unknown")
    body = (form.get("Body") or "").strip()

    reply_text = _orchestrator.handle_message(sender, body)

    safe_reply = html.escape(reply_text)
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Message>{safe_reply}</Message>"
        "</Response>"
    )
    return Response(content=twiml, media_type="text/xml", status_code=status.HTTP_200_OK)
