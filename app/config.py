"""Application settings loaded from environment variables (.env supported)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: str | None = None
    graph_name: str = "shelfsense"
    query_timeout_ms: int = 3000
    demo_now: str = "2026-10-15T12:00:00"
    order_lookback_days: int = 21
    seed_on_startup: bool = True
    llm_provider: str = "none"
    llm_model: str = "claude-opus-5-5"
    llm_timeout_seconds: int = 20
    cors_origins: list[str] = field(default_factory=list)

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(os.getenv("ANTHROPIC_API_KEY"))
        return False


@lru_cache
def get_settings() -> Settings:
    origins = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return Settings(
        falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
        falkordb_port=_int(os.getenv("FALKORDB_PORT"), 6379),
        falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
        graph_name=os.getenv("FALKORDB_GRAPH", "shelfsense"),
        query_timeout_ms=_int(os.getenv("QUERY_TIMEOUT_MS"), 3000),
        demo_now=os.getenv("DEMO_NOW", "2026-10-15T12:00:00"),
        order_lookback_days=_int(os.getenv("ORDER_LOOKBACK_DAYS"), 21),
        seed_on_startup=_bool(os.getenv("SEED_ON_STARTUP"), True),
        llm_provider=os.getenv("LLM_PROVIDER", "none").strip().lower(),
        llm_model=os.getenv("LLM_MODEL", "claude-opus-5-5"),
        llm_timeout_seconds=_int(os.getenv("LLM_TIMEOUT_SECONDS"), 20),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
    )
