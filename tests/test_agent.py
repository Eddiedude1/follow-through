from datetime import datetime, timezone

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
    # Review Focus: tool error surfaces to the model, loop doesn't crash.
    # Final review Important #9: the original version of this test only
    # checked the log entry, not that the is_error tool_result was
    # actually sent back to the model in the next request, or that the
    # loop went on to reach end_turn rather than stalling.
    client = FakeAnthropicClient([
        fake_tool_use_response("create_commitment",
            {"note_id": 999, "act": "x", "due": "bad-date"}),
        fake_text_response("Fixed, retrying."),
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client)
    assert result.log[0]["tool_result"]["is_error"] is True
    assert result.stopped_reason == "end_turn"

    second_call_messages = client.calls[1]["messages"]
    tool_result_blocks = [
        block for message in second_call_messages
        for block in (message["content"] if isinstance(message["content"], list) else [])
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert any(block.get("is_error") is True for block in tool_result_blocks)


def test_unknown_tool_name_returned_as_is_error_not_raised(tmp_db_conn):
    # Final review Important #10: only tools.ToolError was caught — an
    # unknown tool name (KeyError) or bad arguments (TypeError) crashed
    # the loop, violating "tool errors never raised past the loop".
    client = FakeAnthropicClient([
        fake_tool_use_response("totally_unknown_tool", {"x": 1}),
        fake_text_response("Recovered."),
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client)
    assert result.stopped_reason == "end_turn"
    assert result.log[0]["tool_result"]["is_error"] is True


def test_tool_call_with_bad_arguments_returned_as_is_error_not_raised(tmp_db_conn):
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note", {"unexpected_arg": "x"}),
        fake_text_response("Recovered."),
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client)
    assert result.stopped_reason == "end_turn"
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


def test_step_limit_result_has_readable_text(tmp_db_conn):
    # Final review Important #7: an empty final_text means Telegram's
    # reply_text("") raises, so the step-limit stop was invisible to the user.
    client = FakeAnthropicClient([
        fake_tool_use_response("search_notes", {"query": "x"})
        for _ in range(20)
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client, max_steps=15)
    assert result.final_text.strip() != ""
    assert "step limit" in result.final_text.lower()


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


def test_schedule_reminder_called_after_create_commitment(tmp_db_conn):
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "organize the garage", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 1, "act": "organize the garage", "due": "2026-11-02"}),
        fake_tool_use_response("schedule_reminder",
            {"id": 1, "when": "2026-11-02T09:00:00", "text": "Organize the garage today."}),
        fake_text_response("Logged and scheduled."),
    ])
    agent.run_agent(tmp_db_conn, "organize the garage", client)
    # Final review Important #4: schedule_reminder now normalizes a naive
    # "when" to UTC (default config.TIMEZONE), so the stored when_ts gains
    # a "+00:00" suffix.
    due = db.get_due_reminders(tmp_db_conn, "2026-11-02T09:00:00+00:00")
    assert due[0]["text"] == "Organize the garage today."


def test_proactive_suggestion_returns_none_when_nothing_relevant(tmp_db_conn):
    client = FakeAnthropicClient([fake_text_response("")])
    result = agent.get_proactive_suggestion(tmp_db_conn, client)
    assert result is None


def test_proactive_suggestion_never_writes_commitments(tmp_db_conn):
    db.insert_note(tmp_db_conn, "she's been stressed about work", "context", "2026-10-30")
    client = FakeAnthropicClient([
        fake_text_response("Maybe take dinner off her plate tonight."),
    ])
    suggestion = agent.get_proactive_suggestion(tmp_db_conn, client)
    assert suggestion == "Maybe take dinner off her plate tonight."
    assert db.list_open_commitments(tmp_db_conn) == []


def test_run_agent_sends_max_tokens_and_effort(tmp_db_conn):
    # Final review Critical #1: every real API call needs max_tokens or it
    # raises a TypeError before any network I/O.
    client = FakeAnthropicClient([fake_text_response("noted")])
    agent.run_agent(tmp_db_conn, "the weather was nice", client)
    assert "max_tokens" in client.calls[0]
    assert client.calls[0].get("output_config", {}).get("effort") in {"low", "medium"}


def test_get_proactive_suggestion_sends_max_tokens_and_effort(tmp_db_conn):
    client = FakeAnthropicClient([fake_text_response("")])
    agent.get_proactive_suggestion(tmp_db_conn, client)
    assert "max_tokens" in client.calls[0]
    assert client.calls[0].get("output_config", {}).get("effort") in {"low", "medium"}


def test_run_agent_grounds_the_model_with_current_date(tmp_db_conn):
    # Final review Important #4: without a date anchor, the model guesses
    # source_date/due/when from training data, not the actual current date.
    client = FakeAnthropicClient([fake_text_response("noted")])
    agent.run_agent(tmp_db_conn, "the weather was nice", client)
    first_message_content = client.calls[0]["messages"][0]["content"]
    assert "the weather was nice" in first_message_content
    assert str(datetime.now(timezone.utc).year) in first_message_content
