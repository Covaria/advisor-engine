"""API configuration, read once from the environment.

Two rules are enforced here rather than left to deployment discipline:
- Live model calls need real sign-in. With dev auth the assistant is always the mock,
  whatever ADVISOR_LLM says, so an unauthenticated server can never spend API credits.
- Dev auth (a trusted `X-Dev-User` header) refuses to start on Render, so a
  misconfigured deploy fails loudly instead of letting anyone pick an identity.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..assistant._paths import DATA_DIR
from ..assistant.chat import llm_mode

DEFAULT_DAILY_TURN_LIMIT = 200


@dataclass(frozen=True)
class Settings:
    auth: str  # "supabase" | "dev"
    store_dir: Path
    supabase_url: str = ""
    supabase_jwt_secret: str = ""  # legacy HS256 secret; empty means verify via JWKS
    allowed_origins: list[str] = field(default_factory=list)
    daily_turn_limit: int = DEFAULT_DAILY_TURN_LIMIT

    @property
    def llm(self) -> str:
        """"mock" or "anthropic". Live only once sign-in is real (see module docstring)."""
        return llm_mode() if self.auth == "supabase" else "mock"


def load_settings() -> Settings:
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    auth = os.environ.get("ADVISOR_AUTH", "").strip().lower() or (
        "supabase" if supabase_url else "dev"
    )
    if auth not in ("supabase", "dev"):
        raise ValueError(f"ADVISOR_AUTH must be 'supabase' or 'dev', not {auth!r}.")
    if auth == "dev" and os.environ.get("RENDER"):
        raise RuntimeError("Dev auth is for local use only; set SUPABASE_URL on Render.")
    if auth == "supabase" and not supabase_url:
        raise RuntimeError("ADVISOR_AUTH=supabase needs SUPABASE_URL.")
    origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
    return Settings(
        auth=auth,
        store_dir=Path(os.environ.get("ADVISOR_API_STORE", DATA_DIR / "api")),
        supabase_url=supabase_url,
        supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET", ""),
        allowed_origins=origins or (["http://localhost:5173"] if auth == "dev" else []),
        daily_turn_limit=int(os.environ.get("ADVISOR_DAILY_TURN_LIMIT", DEFAULT_DAILY_TURN_LIMIT)),
    )
