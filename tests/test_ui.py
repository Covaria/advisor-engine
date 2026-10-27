"""UI smoke test via Streamlit's headless AppTest (skipped without the `ui` extra)."""

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from advisor_engine.assistant import audit  # noqa: E402

APP = str(Path(__file__).resolve().parents[1] / "src" / "advisor_engine" / "ui" / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("ADVISOR_LLM", "mock")
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    return AppTest.from_file(APP, default_timeout=60).run(), tmp_path / "audit.jsonl"


def records(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


def test_loads_in_mock_mode_with_engine_numbers(app):
    at, _ = app
    assert not at.exception
    assert "MOCK" in at.info[0].value and "Synthetic data" in at.info[0].value
    assert {m.label for m in at.metric} >= {"Independent bets", "1-in-100 stress loss"}


def test_chat_reply_is_verified_and_logged(app):
    at, log = app
    at.chat_input[0].set_value("How risky is this portfolio?").run()
    assert not at.exception and not at.error
    rec = [r for r in records(log) if r.get("user_message")][-1]
    assert rec["model"] == "mock" and rec["verification"]["ok"] and not rec["blocked"]


def test_guardrail_demo_withholds_reply(app):
    at, log = app
    at.checkbox[0].check().run()
    at.chat_input[0].set_value("How risky is this portfolio?").run()
    assert "Withheld" in at.error[0].value
    assert records(log)[-1]["blocked"] is True


def test_approving_a_draft_writes_an_audit_entry(app):
    at, log = app
    next(b for b in at.button if b.label == "Draft client explanation").click().run()
    assert at.text_area[-1].value.startswith("DRAFT for advisor review")
    next(b for b in at.button if b.label == "Approve").click().run()
    assert at.success and records(log)[-1]["event"] == "draft_approved"


def test_edit_with_invented_figure_cannot_be_approved(app):
    at, log = app
    next(b for b in at.button if b.label == "Draft client explanation").click().run()
    at.text_area[-1].set_value(at.text_area[-1].value + " Expect 91.2% next year.").run()
    next(b for b in at.button if b.label == "Approve").click().run()
    assert "91.2%" in at.error[0].value
    assert all(r.get("event") != "draft_approved" for r in records(log))


def markdown_text(at):
    return "\n".join(m.value for m in at.markdown)


def test_headline_cards_show_engine_figures(app):
    at, _ = app
    from advisor_engine.assistant._paths import DEFAULT_HOLDINGS
    from advisor_engine.assistant.tools import execute_tool

    conc = json.loads(execute_tool("get_risk_profile",
                                   {"holdings_path": str(DEFAULT_HOLDINGS)}).text)["concentration"]
    text = markdown_text(at)
    assert "Effective independent bets" in text and f"{conc['effective_bets']:.1f}" in text
    assert f"{conc['top_component_share']:.1%}" in text
    assert "Where the risk comes from" in text and "Audit trail" in text


def test_follow_up_button_shows_tools_used_and_sources(app):
    at, log = app
    next(b for b in at.button if b.label == "Stress test a severe period").click().run()
    assert not at.exception and not at.error
    rec = records(log)[-1]
    assert rec["user_message"] == "What is the stress loss in a severe period?"
    assert rec["verification"]["ok"]
    text = markdown_text(at)
    assert "Risk profile" in text and "engine v" in text and rec["holdings_sha256"][:8] in text


def test_uploaded_names_are_escaped_in_html():
    from advisor_engine.ui import theme

    out = theme.card("<b>x</b>", "1.0", "<script>alert(1)</script>")
    assert "<script>" not in out and "&lt;script&gt;" in out
