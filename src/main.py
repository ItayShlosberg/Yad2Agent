"""
Application factory and entry point.

    uvicorn src.main:app --reload --reload-include "*.yaml" --port 8000
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.core.config import load_config
from src.core.logging import setup_logging
from src.services.listing import ListingLoader
from src.services.llm_service import LLMService
from src.services.notifier import NotificationService
from src.services.orchestrator import ConversationOrchestrator
from src.services.prompts import PromptBuilder
from src.services.rate_limiter import RateLimiter
from src.services.scorer import LeadScorer
from src.services.status_engine import StatusEngine
from src.services.store import ConversationStore
from src.api.webhook import router as webhook_router, init_routes
from src.api.leads import router as leads_router, init_leads
from src.api.security import init_security

log = logging.getLogger(__name__)


def _detect_property_type(listing: ListingLoader) -> str:
    """Infer 'rent' or 'buy' from the listing pricing section."""
    pricing = listing.data.get("pricing", {})
    if pricing.get("monthly_rent_ils"):
        return "rent"
    return "buy"


def _detect_asking_price(listing: ListingLoader, property_type: str) -> float | None:
    """Return the primary asking price for status-engine budget checks."""
    pricing = listing.data.get("pricing", {})
    if property_type == "rent":
        return pricing.get("monthly_rent_ils")
    return pricing.get("asking_price")


def create_app() -> FastAPI:
    """Wire all dependencies and return a ready-to-serve FastAPI instance."""
    cfg = load_config()
    setup_logging(cfg.logging)

    listing = ListingLoader(cfg.paths.property_dir)
    property_type = _detect_property_type(listing)
    asking_price = _detect_asking_price(listing, property_type)

    active_fields = cfg.qualifying.fields_for_type(property_type)
    if active_fields:
        log.info("Property type: %s — qualifying on %d fields", property_type, len(active_fields))
    else:
        log.warning("No qualifying fields configured for type '%s', falling back to defaults", property_type)

    store = ConversationStore(cfg.paths.property_storage_dir)
    prompts = PromptBuilder(listing, cfg.qualifying)
    llm = LLMService(cfg.secrets.openai_api_key, cfg.llm, prompts)
    scorer = LeadScorer(cfg.qualifying)
    media_base_url = cfg.secrets.media_base_url.rstrip("/")

    status_engine = StatusEngine(
        qualifying=cfg.qualifying,
        property_type=property_type,
        asking_price=asking_price,
    )

    notifier = NotificationService(
        account_sid=cfg.secrets.twilio_account_sid,
        auth_token=cfg.secrets.twilio_auth_token,
        from_number=cfg.secrets.twilio_whatsapp_number,
        owner_number=cfg.secrets.owner_whatsapp_number,
        enabled=cfg.notification.enabled,
    )

    rate_limiter = RateLimiter(cfg.rate_limit)

    orchestrator = ConversationOrchestrator(
        store=store,
        llm=llm,
        scorer=scorer,
        status_engine=status_engine,
        qualifying=cfg.qualifying,
        listing=listing,
        media_base_url=media_base_url,
        notifier=notifier,
        rate_limiter=rate_limiter,
        property_name=cfg.paths.active_property,
    )

    status_callback_url = ""
    if media_base_url:
        status_callback_url = f"{media_base_url}/webhook/status"
    init_routes(orchestrator, status_callback_url)
    init_leads(cfg.paths.storage_dir)
    init_security(
        auth_token=cfg.secrets.twilio_auth_token,
        enabled=cfg.security.validate_twilio_signature,
        public_base_url=media_base_url,
    )

    application = FastAPI(title="Yad2 WhatsApp Lead Agent", version="3.0.0")
    application.include_router(webhook_router)
    application.include_router(leads_router)

    if cfg.paths.media_dir.is_dir():
        application.mount("/media", StaticFiles(directory=cfg.paths.media_dir), name="media")
        log.info("Serving media from %s at /media", cfg.paths.media_dir)

    log.info(
        "Active property: %s (type=%s, price=%s, %d media files)",
        cfg.paths.active_property,
        property_type,
        asking_price,
        len(listing.media_files),
    )

    return application


app = create_app()


if __name__ == "__main__":
    from src.core.config import load_config as _lc
    _cfg = _lc()
    uvicorn.run(
        "src.main:app",
        host=_cfg.server.host,
        port=_cfg.server.port,
        reload=_cfg.server.reload,
        reload_includes=["*.yaml"] if _cfg.server.reload else [],
    )
