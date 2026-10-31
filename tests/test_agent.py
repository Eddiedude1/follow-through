from follow_through import agent, config, db
from tests.conftest import FakeAnthropicClient, fake_text_response, fake_tool_use_response


def test_no_actionable_content_creates_no_commitments(tmp_db_conn):
    # Review Focus: pure observation, no ask -> zero commitments
    client = FakeAnthropicClient([
        fake_text_response("Got it, just noting that."),
    ])
    agent.run_agent(tmp_db_conn, "the weather was nice today", client)
    assert db.list_open_commitments(tmp_db_conn) == []


def test_tool_error_returned_as_is_error_not_raised(tmp_db_conn):
    # Review Focus: tool error surfaces to the model, loop doesn't crash
    client = FakeAnthropicClient([
        fake_tool_use_response("create_commitment",
            {"note_id": 999, "act": "x", "due": "bad-date"}),
        fake_text_response("Fixed, retrying."),
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client)
    assert result.log[0]["tool_result"]["is_error"] is True


def test_step_limit_stops_loop_cleanly(tmp_db_conn):
    # Review Focus: never reaching end_turn stops at MAX_STEPS, doesn't hang
    client = FakeAnthropicClient([
        fake_tool_use_response("search_notes", {"query": "x"})
        for _ in range(20)
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client, max_steps=15)
    assert result.steps_used == 15
    assert result.stopped_reason == "step_limit"


def test_two_distinct_asks_become_two_commitments(tmp_db_conn):
    # Review Focus: multiple asks in one note -> separate commitments
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "take out the trash", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("add_note",
            {"text": "call the dentist", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 1, "act": "take out the trash", "due": "2026-11-01"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 2, "act": "call the dentist", "due": "2026-11-03"}),
        fake_text_response("Logged both."),
    ])
    agent.run_agent(tmp_db_conn, "take out the trash and also call the dentist", client)
    assert len(db.list_open_commitments(tmp_db_conn)) == 2


def test_run_is_logged(tmp_db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_PATH", str(tmp_path / "run.log"))
    client = FakeAnthropicClient([fake_text_response("noted")])
    agent.run_agent(tmp_db_conn, "the weather was nice", client)
    assert (tmp_path / "run.log").exists()
