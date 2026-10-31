"""API tests: sign-in, firm isolation, the assistant loop and draft approval.

Dev auth (an X-Dev-User header) stands in for Supabase except in the token tests, which
sign HS256 tokens with a test secret. Nothing here reaches the network or the real API.
"""

import json
import time

import pytest

pytest.importorskip("fastapi")
import jwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from advisor_engine.api.main import create_app  # noqa: E402
from advisor_engine.api.settings import Settings, load_settings  # noqa: E402
from advisor_engine.assistant._paths import DEFAULT_HOLDINGS  # noqa: E402
from advisor_engine.assistant.tools import execute_tool  # noqa: E402

SUPABASE_URL = "https://example.supabase.co"
SECRET = "test-secret-that-is-long-enough-for-hs256"


@pytest.fixture
def api(tmp_path):
    app = create_app(Settings(auth="dev", store_dir=tmp_path, daily_turn_limit=5))
    return TestClient(app), app.state.store


def as_(user):
    return {"X-Dev-User": user}


def setup_portfolio(client, user="alice"):
    c = client.post("/clients", json={"name": "Sample Household A", "objective": "retirement income"},
                    headers=as_(user)).json()
    p = client.post(f"/clients/{c['id']}/portfolios", headers=as_(user),
                    files={"file": ("holdings.csv", DEFAULT_HOLDINGS.read_bytes(), "text/csv")})
    assert p.status_code == 201, p.text
    return c, p.json()


# --- sign-in -----------------------------------------------------------------------------

def test_requests_without_sign_in_are_refused(api):
    client, _ = api
    assert client.get("/health").status_code == 200
    assert client.get("/clients").status_code == 401


def test_first_sign_in_creates_a_firm_and_dev_auth_is_never_live(api, monkeypatch):
    client, _ = api
    monkeypatch.setenv("ADVISOR_LLM", "anthropic")
    me = client.get("/me", headers=as_("alice")).json()
    assert me["adviser"]["role"] == "owner" and me["firm"]["id"] == me["adviser"]["firm_id"]
    assert me["llm"] == "mock"


def test_dev_auth_refuses_to_start_on_render(monkeypatch):
    for k in ("ADVISOR_AUTH", "SUPABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="Dev auth"):
        load_settings()


def token(**claims):
    base = {"sub": "user-1", "email": "a@firm.com", "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1", "exp": int(time.time()) + 600}
    return jwt.encode({**base, **claims}, SECRET, algorithm="HS256")


@pytest.mark.parametrize("claims, ok", [
    ({}, True),
    ({"aud": "anon"}, False),                        # anon / service keys are not sign-ins
    ({"iss": "https://other.supabase.co/auth/v1"}, False),
    ({"exp": int(time.time()) - 10}, False),
    ({"is_anonymous": True}, False),
])
def test_supabase_tokens_are_verified(tmp_path, claims, ok):
    app = create_app(Settings(auth="supabase", store_dir=tmp_path, supabase_url=SUPABASE_URL,
                              supabase_jwt_secret=SECRET))
    r = TestClient(app).get("/me", headers={"Authorization": f"Bearer {token(**claims)}"})
    assert r.status_code == (200 if ok else 401), r.text


def test_token_signed_with_another_secret_is_refused(tmp_path):
    app = create_app(Settings(auth="supabase", store_dir=tmp_path, supabase_url=SUPABASE_URL,
                              supabase_jwt_secret=SECRET))
    forged = jwt.encode(jwt.decode(token(), options={"verify_signature": False}),
                        "x" * 40, algorithm="HS256")
    assert TestClient(app).get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


# --- engine and assistant ------------------------------------------------------------------

def test_profile_is_the_engine_output(api):
    client, _ = api
    _, p = setup_portfolio(client)
    got = client.get(f"/portfolios/{p['id']}/profile", headers=as_("alice")).json()
    expected = json.loads(execute_tool("get_risk_profile", {"holdings_path": str(DEFAULT_HOLDINGS)}).text)
    assert got["profile"] == expected


def test_turn_is_verified_saved_and_audited_with_the_adviser(api):
    client, store = api
    c, p = setup_portfolio(client)
    r = client.post(f"/portfolios/{p['id']}/turns", json={"message": "How risky is this portfolio?"},
                    headers=as_("alice")).json()
    assert not r["blocked"] and r["verification"]["ok"]
    assert r["tool_calls"][0]["label"] == "Risk profile"
    assert "holdings_path" not in json.dumps(r["tool_calls"])  # no server paths leak
    assert len(client.get(f"/portfolios/{p['id']}/messages", headers=as_("alice")).json()) == 2
    rec = store.read_audit(p["firm_id"])[-1]
    assert rec["adviser_id"] == "dev:alice" and rec["portfolio_id"] == p["id"]
    assert rec["client_id"] == c["id"] and rec["model"] == "mock"


def test_bad_csv_is_rejected(api):
    client, _ = api
    c = client.post("/clients", json={"name": "X"}, headers=as_("alice")).json()
    r = client.post(f"/clients/{c['id']}/portfolios", headers=as_("alice"),
                    files={"file": ("h.csv", b"ticker,shares\nAAA,-1\n", "text/csv")})
    assert r.status_code == 422


def test_daily_turn_limit(api):
    client, _ = api
    _, p = setup_portfolio(client)
    codes = [client.post(f"/portfolios/{p['id']}/turns", json={"message": "risk?"},
                         headers=as_("alice")).status_code for _ in range(6)]
    assert codes == [200] * 5 + [429]


# --- drafts --------------------------------------------------------------------------------

def make_draft(client):
    _, p = setup_portfolio(client)
    r = client.post(f"/portfolios/{p['id']}/turns", json={"draft": True}, headers=as_("alice")).json()
    assert r["draft_id"], r
    return r


def test_approving_a_draft_records_who_approved(api):
    client, store = api
    r = make_draft(client)
    ok = client.post(f"/drafts/{r['draft_id']}/approve", json={"text": r["content"]}, headers=as_("alice"))
    assert ok.status_code == 200 and ok.json()["approved_by"] == "dev:alice"
    rec = store.read_audit(ok.json()["firm_id"])[-1]
    assert rec["event"] == "draft_approved" and rec["approved_by_email"] == "alice@dev.local"
    again = client.post(f"/drafts/{r['draft_id']}/approve", json={"text": r["content"]}, headers=as_("alice"))
    assert again.status_code == 409


def test_edited_draft_with_invented_figure_is_not_approved(api):
    client, _ = api
    r = make_draft(client)
    bad = client.post(f"/drafts/{r['draft_id']}/approve",
                      json={"text": r["content"] + " Expect 91.2% next year."}, headers=as_("alice"))
    assert bad.status_code == 422 and "91.2%" in bad.json()["detail"]["unmatched"]


# --- firm isolation ------------------------------------------------------------------------

def test_another_firm_cannot_see_or_use_anything(api):
    client, _ = api
    c, p = setup_portfolio(client, "alice")
    draft = client.post(f"/portfolios/{p['id']}/turns", json={"draft": True}, headers=as_("alice")).json()
    bob = as_("bob")
    assert client.get("/clients", headers=bob).json() == []
    assert client.get(f"/clients/{c['id']}", headers=bob).status_code == 404
    assert client.get(f"/portfolios/{p['id']}/profile", headers=bob).status_code == 404
    assert client.get(f"/portfolios/{p['id']}/messages", headers=bob).status_code == 404
    assert client.post(f"/portfolios/{p['id']}/turns", json={"message": "risk?"}, headers=bob).status_code == 404
    assert client.post(f"/drafts/{draft['draft_id']}/approve", json={"text": draft["content"]},
                       headers=bob).status_code == 404
    up = client.post(f"/clients/{c['id']}/portfolios", headers=bob,
                     files={"file": ("h.csv", DEFAULT_HOLDINGS.read_bytes(), "text/csv")})
    assert up.status_code == 404
    assert client.get("/audit", headers=bob).json() == []


def test_engine_tool_cannot_read_another_firms_file(api):
    """Even if the model is handed another firm's path, the tool's path guard refuses it."""
    client, store = api
    _, p = setup_portfolio(client, "alice")
    bob_firm = client.get("/me", headers=as_("bob")).json()["firm"]["id"]
    alice_csv = store.portfolio_csv(p["firm_id"], p["id"])
    res = execute_tool("get_risk_profile", {"holdings_path": str(alice_csv)},
                       data_dir=store.firm_dir(bob_firm))
    assert res.is_error and "must be inside" in res.text
    rel = f"{p['firm_id']}/portfolios/{p['id']}.csv"  # relative to the firms/ folder
    assert execute_tool("get_risk_profile", {"holdings_path": rel},
                        data_dir=store.firm_dir(bob_firm)).is_error
