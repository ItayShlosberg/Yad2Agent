"""
Application factory and entry point.

    uvicorn src.main:app --reload --port 8000
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from src.core.config import load_config
from src.core.logging import setup_logging
from src.services.listing import ListingLoader
from src.services.llm_service import LLMService
from src.services.orchestrator import ConversationOrchestrator
from src.services.prompts import PromptBuilder
from src.services.scorer import LeadScorer
from src.services.store import ConversationStore
from src.api.webhook import router, init_routes


def create_app() -> FastAPI:
    """Wire all dependencies and return a ready-to-serve FastAPI instance."""
    cfg = load_config()
    setup_logging(cfg.logging)

    listing = ListingLoader(cfg.paths.listing_file)
    store = ConversationStore(cfg.paths.storage_dir)
    prompts = PromptBuilder(listing, cfg.qualifying)
    llm = LLMService(cfg.secrets.openai_api_key, cfg.llm, prompts)
    scorer = LeadScorer(cfg.qualifying)
    orchestrator = ConversationOrchestrator(store, llm, scorer)

    init_routes(orchestrator)

    application = FastAPI(title="Yad2 WhatsApp Lead Agent", version="1.0.0")
    application.include_router(router)
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
    )
