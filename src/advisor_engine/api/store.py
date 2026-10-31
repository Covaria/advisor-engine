"""Persistence for the API, scoped by firm.

`LocalStore` keeps everything on local disk (JSON plus the uploaded CSVs) for
development, tests and single-machine demos. The Supabase store (Postgres + Storage,
phase 2 of docs/migration-plan.md) implements the same methods.

Firm isolation is structural, not just a filter:
- Every read takes a `firm_id` and returns None for another firm's ids, so routes answer
  404 and never reveal that the id exists.
- Each firm's CSVs live under their own directory, which is passed to the engine tool
  as its `data_dir`. The tool's path guard then refuses anything outside that firm,
  even if the model is asked for another firm's file by path.
- Each firm's audit log sits in `<firm dir>/audit/`, which the path guard also refuses.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.RLock()

    # --- files -----------------------------------------------------------------------

    def _read(self, path: Path, default):
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default

    def _write(self, path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, default=str))
        tmp.replace(path)  # atomic, so a crash never leaves half a file

    def firm_dir(self, firm_id: str) -> Path:
        return self.root / "firms" / firm_id

    def audit_path(self, firm_id: str) -> Path:
        return self.firm_dir(firm_id) / "audit" / "audit.jsonl"

    def _state_path(self, firm_id: str) -> Path:
        return self.firm_dir(firm_id) / "state.json"

    def _state(self, firm_id: str) -> dict:
        return self._read(self._state_path(firm_id),
                          {"clients": {}, "portfolios": {}, "conversations": {}, "drafts": {}})

    def _update(self, firm_id: str, fn):
        with self._lock:
            state = self._state(firm_id)
            out = fn(state)
            self._write(self._state_path(firm_id), state)
            return out

    # --- advisers and firms ----------------------------------------------------------

    def get_or_create_adviser(self, user_id: str, email: str) -> dict:
        """Open sign-up: a new user gets a new firm of their own, as its owner."""
        path = self.root / "advisers.json"
        with self._lock:
            advisers = self._read(path, {})
            if user_id not in advisers:
                firm_id = _new_id()
                advisers[user_id] = {"id": user_id, "email": email, "firm_id": firm_id,
                                     "role": "owner", "created_at": _now()}
                self._write(path, advisers)
                self._write(self.firm_dir(firm_id) / "firm.json",
                            {"id": firm_id, "name": email.split("@")[-1] or "My firm",
                             "created_at": _now()})
            return advisers[user_id]

    def get_firm(self, firm_id: str) -> dict:
        return self._read(self.firm_dir(firm_id) / "firm.json", {"id": firm_id})

    def bump_turns(self, adviser_id: str, limit: int) -> bool:
        """Count one assistant turn for today (UTC). False once `limit` is reached."""
        path = self.root / "usage.json"
        day = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            usage = self._read(path, {})
            key = f"{adviser_id}|{day}"
            if usage.get(key, 0) >= limit:
                return False
            usage[key] = usage.get(key, 0) + 1
            self._write(path, usage)
            return True

    # --- clients ---------------------------------------------------------------------

    def create_client(self, firm_id: str, adviser_id: str, fields: dict) -> dict:
        client = {"id": _new_id(), "firm_id": firm_id, "created_by": adviser_id,
                  "created_at": _now(), **fields}
        return self._update(firm_id, lambda s: s["clients"].setdefault(client["id"], client))

    def list_clients(self, firm_id: str) -> list[dict]:
        return sorted(self._state(firm_id)["clients"].values(), key=lambda c: c["created_at"])

    def get_client(self, firm_id: str, client_id: str) -> dict | None:
        return self._state(firm_id)["clients"].get(client_id)

    # --- portfolios ------------------------------------------------------------------

    def portfolio_csv(self, firm_id: str, portfolio_id: str) -> Path:
        return self.firm_dir(firm_id) / "portfolios" / f"{portfolio_id}.csv"

    def add_portfolio(self, firm_id: str, client_id: str, adviser_id: str, filename: str,
                      csv_bytes: bytes, sha256: str) -> dict:
        pid = _new_id()
        path = self.portfolio_csv(firm_id, pid)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(csv_bytes)
        record = {"id": pid, "firm_id": firm_id, "client_id": client_id, "filename": filename,
                  "sha256": sha256, "uploaded_by": adviser_id, "created_at": _now()}
        return self._update(firm_id, lambda s: s["portfolios"].setdefault(pid, record))

    def list_portfolios(self, firm_id: str, client_id: str) -> list[dict]:
        ps = self._state(firm_id)["portfolios"].values()
        return sorted((p for p in ps if p["client_id"] == client_id), key=lambda p: p["created_at"])

    def get_portfolio(self, firm_id: str, portfolio_id: str) -> dict | None:
        return self._state(firm_id)["portfolios"].get(portfolio_id)

    # --- conversations and drafts ----------------------------------------------------

    def get_conversation(self, firm_id: str, portfolio_id: str) -> dict:
        return self._state(firm_id)["conversations"].get(
            portfolio_id, {"history": [], "messages": []})

    def save_conversation(self, firm_id: str, portfolio_id: str, conversation: dict) -> None:
        self._update(firm_id, lambda s: s["conversations"].__setitem__(portfolio_id, conversation))

    def create_draft(self, firm_id: str, fields: dict) -> dict:
        draft = {"id": _new_id(), "firm_id": firm_id, "approved": False,
                 "created_at": _now(), **fields}
        return self._update(firm_id, lambda s: s["drafts"].setdefault(draft["id"], draft))

    def get_draft(self, firm_id: str, draft_id: str) -> dict | None:
        return self._state(firm_id)["drafts"].get(draft_id)

    def save_draft(self, firm_id: str, draft: dict) -> None:
        self._update(firm_id, lambda s: s["drafts"].__setitem__(draft["id"], draft))

    # --- audit -----------------------------------------------------------------------

    def read_audit(self, firm_id: str) -> list[dict]:
        path = self.audit_path(firm_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
