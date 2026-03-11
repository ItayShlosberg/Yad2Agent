"""
Thin FastAPI route handlers.

All business logic lives in the orchestrator; routes only parse HTTP
and format the TwiML response.
"""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Request, Response, status

from src.api.security import verify_twilio_signature
from src.services.orchestrator import ConversationOrchestrator

router = APIRouter()
log = logging.getLogger(__name__)

_orchestrator: ConversationOrchestrator | None = None
_status_callback_url: str = ""


def init_routes(orchestrator: ConversationOrchestrator, status_callback_url: str = "") -> None:
    """Called once at startup to inject the orchestrator dependency."""
    global _orchestrator, _status_callback_url
    _orchestrator = orchestrator
    _status_callback_url = status_callback_url


@router.get("/health")
async def health():
    return {"ok": True}


def _build_twiml(body: str, media_urls: list[str] | None = None) -> str:
    """Build TwiML response.

    WhatsApp allows at most one media attachment per message, so when we
    have multiple files we emit one <Message> per file (the first carries
    the text body, the rest are media-only).
    """
    safe_body = html.escape(body)
    cb_attr = ""
    if _status_callback_url:
        cb_attr = f' statusCallback="{html.escape(_status_callback_url)}"'

    if not media_urls:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            f"<Message{cb_attr}>{safe_body}</Message>"
            "</Response>"
        )

    parts: list[str] = []
    parts.append(
        f"<Message{cb_attr}>"
        f"<Body>{safe_body}</Body>"
        f"<Media>{html.escape(media_urls[0])}</Media>"
        f"</Message>"
    )
    for url in media_urls[1:]:
        parts.append(
            f"<Message{cb_attr}>"
            f"<Media>{html.escape(url)}</Media>"
            f"</Message>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>" + "".join(parts) + "</Response>"
    )


@router.post("/webhook", dependencies=[Depends(verify_twilio_signature)])
async def twilio_whatsapp_webhook(request: Request):
    form = await request.form()
    sender = form.get("From", "unknown")
    body = (form.get("Body") or "").strip()

    result = _orchestrator.handle_message(sender, body)

    twiml = _build_twiml(result.text, result.media_urls)
    return Response(content=twiml, media_type="text/xml", status_code=status.HTTP_200_OK)


@router.post("/webhook/status", dependencies=[Depends(verify_twilio_signature)])
async def twilio_status_callback(request: Request):
    """
    Twilio POSTs here when a message delivery status changes.

    Key fields: MessageSid, MessageStatus, To, ErrorCode, ErrorMessage.
    We log every callback; errors get logged at ERROR level so they
    show up in alerts / log monitoring.
    """
    form = await request.form()
    sid = form.get("MessageSid", "?")
    msg_status = form.get("MessageStatus", "?")
    to = form.get("To", "?")
    error_code = form.get("ErrorCode")
    error_msg = form.get("ErrorMessage", "")

    if error_code:
        log.error(
            "DELIVERY FAILED | sid=%s to=%s status=%s error_code=%s error=%s",
            sid, to, msg_status, error_code, error_msg,
            extra={"event": "delivery_failed", "phone": to,
                   "status": msg_status, "error_code": error_code},
        )
    elif msg_status in ("delivered", "read"):
        log.info(
            "Delivered | sid=%s to=%s status=%s",
            sid, to, msg_status,
            extra={"event": "delivered", "phone": to, "status": msg_status},
        )
    else:
        log.debug(
            "Status update | sid=%s to=%s status=%s",
            sid, to, msg_status,
            extra={"event": "status_update", "phone": to, "status": msg_status},
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
