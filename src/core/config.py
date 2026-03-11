"""
Centralised configuration loaded from YAML files and environment variables.

YAML files hold non-secret, structural settings (models, scoring rules, paths).
Secrets (API keys, Twilio tokens) come exclusively from environment / .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
CONFIG_DIR = BASE_DIR / "config"


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ── Dataclass config objects ───────────────────────────────────────


@dataclass(frozen=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"

    file_enabled: bool = False
    file_path: str = "logs/agent.log"
    file_max_bytes: int = 5_242_880
    file_backup_count: int = 5

    json_enabled: bool = False
    json_path: str = "logs/agent.jsonl"
    json_max_bytes: int = 10_485_760
    json_backup_count: int = 3


@dataclass(frozen=True)
class PathsConfig:
    storage_dir: Path = field(default_factory=lambda: BASE_DIR / "storage")
    data_dir: Path = field(default_factory=lambda: BASE_DIR / "data")
    active_property: str = "property_1"

    @property
    def property_dir(self) -> Path:
        return self.data_dir / self.active_property

    @property
    def listing_file(self) -> Path:
        return self.property_dir / "listing.json"

    @property
    def media_dir(self) -> Path:
        return self.property_dir / "media"

    @property
    def property_storage_dir(self) -> Path:
        return self.storage_dir / self.active_property


@dataclass(frozen=True)
class LLMModelConfig:
    model: str = "gpt-4o"
    temperature: float = 0.4
    max_tokens: int = 300


@dataclass(frozen=True)
class LLMConfig:
    reply: LLMModelConfig = field(default_factory=LLMModelConfig)
    extraction: LLMModelConfig = field(default_factory=lambda: LLMModelConfig(
        model="gpt-4o-mini", temperature=0.1, max_tokens=300,
    ))
    fallback_message: str = "תודה על ההודעה! אחזור אליך בהקדם."


@dataclass(frozen=True)
class QualifyingField:
    name: str
    description: str
    required: bool = True
    priority: int = 99


@dataclass(frozen=True)
class ScoringConfig:
    points_per_field: int = 15
    visit_bonus: int = 10
    red_flag_penalty: int = 15
    max_score: int = 100


@dataclass(frozen=True)
class StatusRulesConfig:
    min_turns: int = 2
    qualified_max_missing: int = 1
    budget_floor_pct: float = 0.6

@dataclass(frozen=True)
class QualifyingConfig:
    fields: list[QualifyingField] = field(default_factory=list)
    fields_by_type: dict[str, list[QualifyingField]] = field(default_factory=dict)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    status_rules: StatusRulesConfig = field(default_factory=StatusRulesConfig)
    qualified_max_missing: int = 2

    def fields_for_type(self, property_type: str) -> list[QualifyingField]:
        """Return the field list for a property type, falling back to ``fields``."""
        return self.fields_by_type.get(property_type, self.fields)


@dataclass(frozen=True)
class NotificationConfig:
    enabled: bool = True


@dataclass(frozen=True)
class RateLimitConfig:
    max_messages: int = 10
    window_seconds: int = 300
    cooldown_message: str = "אתה שולח הודעות מהר מדי. נסה שוב בעוד מספר דקות."


@dataclass(frozen=True)
class SecurityConfig:
    validate_twilio_signature: bool = False


@dataclass(frozen=True)
class SecretsConfig:
    openai_api_key: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_number: str = ""
    media_base_url: str = ""
    owner_whatsapp_number: str = ""


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    logging: LoggingConfig
    paths: PathsConfig
    llm: LLMConfig
    qualifying: QualifyingConfig
    secrets: SecretsConfig
    notification: NotificationConfig = field(default_factory=NotificationConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


# ── Factory ────────────────────────────────────────────────────────


def load_config() -> AppConfig:
    """Build an AppConfig by merging all YAML files and env vars."""

    app_raw = _load_yaml("app.yaml")
    llm_raw = _load_yaml("llm.yaml")
    qual_raw = _load_yaml("qualifying.yaml")

    server = ServerConfig(**app_raw.get("server", {}))

    log_raw = app_raw.get("logging", {})
    log_level_env = os.getenv("LOG_LEVEL", "").upper()
    if log_level_env:
        log_raw["level"] = log_level_env

    file_path = log_raw.pop("file_path", "logs/agent.log")
    json_path = log_raw.pop("json_path", "logs/agent.jsonl")
    log_raw["file_path"] = str(BASE_DIR / file_path)
    log_raw["json_path"] = str(BASE_DIR / json_path)
    logging_cfg = LoggingConfig(**log_raw)

    paths_raw = app_raw.get("paths", {})
    paths = PathsConfig(
        storage_dir=BASE_DIR / paths_raw.get("storage_dir", "storage"),
        data_dir=BASE_DIR / paths_raw.get("data_dir", "data"),
        active_property=paths_raw.get("active_property", "property_1"),
    )

    reply_cfg = LLMModelConfig(**llm_raw.get("reply", {}))
    extract_cfg = LLMModelConfig(**llm_raw.get("extraction", {}))
    llm = LLMConfig(
        reply=reply_cfg,
        extraction=extract_cfg,
        fallback_message=llm_raw.get("fallback_message", LLMConfig.fallback_message),
    )

    raw_fields = qual_raw.get("fields", [])
    q_fields = [QualifyingField(**f) for f in raw_fields]

    raw_by_type = qual_raw.get("fields_by_type", {})
    fields_by_type: dict[str, list[QualifyingField]] = {}
    for ptype, flist in raw_by_type.items():
        fields_by_type[ptype] = [QualifyingField(**f) for f in flist]

    scoring = ScoringConfig(**qual_raw.get("scoring", {}))

    status_rules_raw = qual_raw.get("status_rules", {})
    status_rules = StatusRulesConfig(**status_rules_raw)

    status_trans = qual_raw.get("status_transitions", {})
    qualifying = QualifyingConfig(
        fields=q_fields,
        fields_by_type=fields_by_type,
        scoring=scoring,
        status_rules=status_rules,
        qualified_max_missing=status_rules.qualified_max_missing
            if status_rules_raw else status_trans.get("qualified_max_missing", 2),
    )

    secrets = SecretsConfig(
        openai_api_key=os.getenv("GPT", ""),
        twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
        twilio_whatsapp_number=os.getenv("TWILIO_WHATSAPP_NUMBER", ""),
        media_base_url=os.getenv("MEDIA_BASE_URL", ""),
        owner_whatsapp_number=os.getenv("OWNER_WHATSAPP_NUMBER", ""),
    )

    notification = NotificationConfig(**app_raw.get("notification", {}))
    rate_limit = RateLimitConfig(**app_raw.get("rate_limit", {}))
    security = SecurityConfig(**app_raw.get("security", {}))

    return AppConfig(
        server=server,
        logging=logging_cfg,
        paths=paths,
        llm=llm,
        qualifying=qualifying,
        secrets=secrets,
        notification=notification,
        rate_limit=rate_limit,
        security=security,
    )
