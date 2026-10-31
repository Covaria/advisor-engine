"""HTTP API over the engine and the assistant: `uvicorn advisor_engine.api.main:app`.

Same guarantees as the Streamlit demo, now per signed-in adviser and per firm:
- Every figure comes from `execute_tool` / `run_turn`; routes only move engine output
  around and never compute.
- Model replies go through `run_turn`, so the number check, retry and withholding apply.
  The browser never talks to the model.
- Every turn and approval is audited with the adviser and firm that made it.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .. import __version__
from ..assistant.chat import run_turn
from ..assistant.mock_client import MockClient
from ..assistant.numcheck import verify
from ..assistant.tools import execute_tool
from ..holdings import validate_holdings
from .auth import User, current_user
from .settings import Settings, load_settings
from .store import LocalStore
from .supabase_store import SupabaseStorage, SupabaseStore

DRAFT_REQUEST = "Please write a client-ready explanation of this portfolio's risk, for my review."
TOOL_LABELS = {"get_risk_profile": "Risk profile"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(default="", max_length=500)
    tone: str = Field(default="", max_length=100)


class TurnIn(BaseModel):
    message: str = Field(default="", max_length=4000)
    draft: bool = False  # ask for a client-ready draft instead of answering `message`


class ApproveIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


def _tool_view(call: dict) -> dict:
    """A tool call as the browser sees it: engine output, but not server file paths."""
    try:
        output = json.loads(call["output"])
    except ValueError:
        output = call["output"]
    return {"name": call["name"], "label": TOOL_LABELS.get(call["name"], call["name"]),
            "is_error": call["is_error"], "holdings_sha256": call.get("holdings_sha256"),
            "output": output}


@dataclass
class Ctx:
    """The signed-in adviser and a store session that acts as them."""
    adv: dict
    db: object


def make_store(settings: Settings):
    if settings.store == "supabase":
        return SupabaseStore(settings.supabase_db_url,
                             SupabaseStorage(settings.supabase_url, settings.supabase_secret_key),
                             cache_dir=settings.store_dir / "cache")
    return LocalStore(settings.store_dir)


def create_app(settings: Settings | None = None, store=None) -> FastAPI:
    settings = settings or load_settings()
    store = store or make_store(settings)
    app = FastAPI(title="Advisor Engine API", version=__version__)
    app.state.settings = settings
    app.state.store = store
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["Authorization", "Content-Type", "X-Dev-User"],
    )

    def ctx(user: User = Depends(current_user)) -> Ctx:
        db = store.as_user(user.id, user.email)
        return Ctx(db.get_or_create_adviser(user.id, user.email), db)

    def own_client(c: Ctx, client_id: str) -> dict:
        client = c.db.get_client(c.adv["firm_id"], client_id)
        if client is None:
            raise HTTPException(404, "Client not found.")
        return client

    def own_portfolio(c: Ctx, portfolio_id: str) -> dict:
        p = c.db.get_portfolio(c.adv["firm_id"], portfolio_id)
        if p is None:
            raise HTTPException(404, "Portfolio not found.")
        return p

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "engine_version": __version__}

    @app.get("/me")
    def me(c: Ctx = Depends(ctx)) -> dict:
        return {"adviser": c.adv, "firm": c.db.get_firm(c.adv["firm_id"]), "auth": settings.auth,
                "llm": settings.llm, "daily_turn_limit": settings.daily_turn_limit,
                "engine_version": __version__}

    # --- clients and portfolios ------------------------------------------------------

    @app.get("/clients")
    def list_clients(c: Ctx = Depends(ctx)) -> list[dict]:
        return c.db.list_clients(c.adv["firm_id"])

    @app.post("/clients", status_code=201)
    def create_client(body: ClientIn, c: Ctx = Depends(ctx)) -> dict:
        return c.db.create_client(c.adv["firm_id"], c.adv["id"], body.model_dump())

    @app.get("/clients/{client_id}")
    def get_client(client_id: str, c: Ctx = Depends(ctx)) -> dict:
        return {**own_client(c, client_id),
                "portfolios": c.db.list_portfolios(c.adv["firm_id"], client_id)}

    @app.post("/clients/{client_id}/portfolios", status_code=201)
    async def upload_portfolio(client_id: str, file: UploadFile = File(...),
                               c: Ctx = Depends(ctx)) -> dict:
        own_client(c, client_id)
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Holdings file is larger than 2 MB.")
        name = re.sub(r"[^\w.-]", "_", file.filename or "holdings.csv")
        if not name.lower().endswith(".csv"):
            raise HTTPException(422, "The file must be a .csv.")
        try:
            validate_holdings(pd.read_csv(io.BytesIO(data)))
        except Exception as e:  # any load failure means the file is not usable
            raise HTTPException(422, f"{name} was rejected: {e}") from e
        return c.db.add_portfolio(c.adv["firm_id"], client_id, c.adv["id"], name, data,
                                   hashlib.sha256(data).hexdigest())

    @app.get("/portfolios/{portfolio_id}/profile")
    def profile(portfolio_id: str, c: Ctx = Depends(ctx)) -> dict:
        fid = c.adv["firm_id"]
        own_portfolio(c, portfolio_id)
        res = execute_tool("get_risk_profile",
                           {"holdings_path": str(c.db.holdings_file(fid, portfolio_id))},
                           data_dir=c.db.firm_dir(fid))
        if res.is_error:
            raise HTTPException(422, res.text)
        return {"holdings_sha256": res.holdings_sha256, "profile": json.loads(res.text)}

    # --- assistant -------------------------------------------------------------------

    @app.get("/portfolios/{portfolio_id}/messages")
    def messages(portfolio_id: str, c: Ctx = Depends(ctx)) -> list[dict]:
        own_portfolio(c, portfolio_id)
        return c.db.get_conversation(c.adv["firm_id"], portfolio_id)["messages"]

    @app.post("/portfolios/{portfolio_id}/turns")
    def ask(portfolio_id: str, body: TurnIn, c: Ctx = Depends(ctx)) -> dict:
        fid = c.adv["firm_id"]
        portfolio = own_portfolio(c, portfolio_id)
        question = DRAFT_REQUEST if body.draft else body.message.strip()
        if not question:
            raise HTTPException(422, "Ask a question or request a draft.")
        if not c.db.bump_turns(c.adv["id"], settings.daily_turn_limit):
            raise HTTPException(429, "Daily assistant limit reached; try again tomorrow.")
        client = c.db.get_client(fid, portfolio["client_id"]) or {}
        conversation = c.db.get_conversation(fid, portfolio_id)
        try:
            result = run_turn(
                question, conversation["history"],
                MockClient() if settings.llm == "mock" else None,
                firm_profile={k: client[k] for k in ("objective", "tone") if client.get(k)},
                default_holdings=str(c.db.holdings_file(fid, portfolio_id)),
                data_dir=c.db.firm_dir(fid),
                audit_sink=lambda record: c.db.write_audit(fid, record),
                audit_extra={"event": "turn", "adviser_id": c.adv["id"], "firm_id": fid,
                             "client_id": portfolio["client_id"], "portfolio_id": portfolio_id},
            )
        except Exception as e:  # missing package, model API error, ...
            raise HTTPException(502, f"The assistant is unavailable: {e}") from e

        draft_id = None
        if body.draft and not result.blocked:
            draft_id = c.db.create_draft(fid, {
                "portfolio_id": portfolio_id, "created_by": c.adv["id"],
                "original": result.reply, "tool_calls": result.tool_calls})["id"]
        reply = {"role": "assistant", "content": result.reply, "blocked": result.blocked,
                 "verification": result.verification,
                 "tool_calls": [_tool_view(call) for call in result.tool_calls], "draft_id": draft_id}
        conversation["history"] = result.history
        conversation["messages"] += [{"role": "user", "content": question}, reply]
        c.db.save_conversation(fid, portfolio_id, conversation)
        return reply

    @app.post("/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: ApproveIn, c: Ctx = Depends(ctx)) -> dict:
        fid = c.adv["firm_id"]
        draft = c.db.get_draft(fid, draft_id)
        if draft is None:
            raise HTTPException(404, "Draft not found.")
        if draft["approved"]:
            raise HTTPException(409, "This draft is already approved.")
        # Edits are re-checked: an adviser can reword, but not add a figure the engine
        # never produced.
        check = verify(body.text, [call["output"] for call in draft["tool_calls"]])
        if not check["ok"]:
            raise HTTPException(422, {"message": "These figures are not from the engine.",
                                      "unmatched": check["unmatched"]})
        record = c.db.write_audit(fid, {
            "event": "draft_approved", "model": None, "adviser_id": c.adv["id"],
            "approved_by_email": c.adv["email"], "firm_id": fid,
            "portfolio_id": draft["portfolio_id"], "draft_id": draft_id,
            "user_message": DRAFT_REQUEST, "tool_calls": draft["tool_calls"],
            "reply": draft["original"], "approved_text": body.text,
            "edited": body.text != draft["original"], "verification": check, "blocked": False,
        })
        draft.update(approved=True, approved_text=body.text, approved_by=c.adv["id"],
                     approved_at=record["timestamp"])
        c.db.save_draft(fid, draft)
        return draft

    @app.get("/audit")
    def audit(portfolio_id: str | None = None, c: Ctx = Depends(ctx)) -> list[dict]:
        """The firm's audit trail, newest first, as a summary (full records stay server-side)."""
        rows = c.db.read_audit(c.adv["firm_id"])
        if portfolio_id:
            rows = [r for r in rows if r.get("portfolio_id") == portfolio_id]
        keys = ("timestamp", "event", "engine_version", "model", "adviser_id", "client_id",
                "portfolio_id", "draft_id", "user_message", "blocked", "block_reason", "edited")
        return [{**{k: r.get(k) for k in keys},
                 "verified": (r.get("verification") or {}).get("ok")} for r in reversed(rows)]

    return app


app = create_app()
