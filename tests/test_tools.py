import pytest

from follow_through import config, db, tools


def test_add_note_rejects_invalid_type(tmp_db_conn):
    with pytest.raises(tools.ToolError):
        tools.add_note(tmp_db_conn, "x", "not_a_type", "2026-10-30")


def test_add_note_returns_note_id(tmp_db_conn):
    result = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")
    assert isinstance(result["note_id"], int)


def test_create_commitment_rejects_bad_date(tmp_db_conn):
    note_id = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")["note_id"]
    with pytest.raises(tools.ToolError):
        tools.create_commitment(tmp_db_conn, note_id, "x", "next tuesday")


def test_mark_done_rejects_unknown_id(tmp_db_conn):
    with pytest.raises(tools.ToolError):
        tools.mark_done(tmp_db_conn, 999, "reaction")


def test_schedule_reminder_rejects_bad_timestamp(tmp_db_conn):
    note_id = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")["note_id"]
    cid = tools.create_commitment(tmp_db_conn, note_id, "x", "2026-11-02")["commitment_id"]
    with pytest.raises(tools.ToolError):
        tools.schedule_reminder(tmp_db_conn, cid, "not-a-timestamp", "text")


def test_schedule_reminder_normalizes_naive_when_using_configured_timezone(tmp_db_conn, monkeypatch):
    # Final review Important #4: a naive "when" stored verbatim gets
    # compared as a UTC string by the scheduler, firing at the wrong
    # local time. December avoids DST ambiguity for Los Angeles (PST, UTC-8).
    # 9am Pacific = 17:00 UTC. Querying at 12:00 UTC (= 4am Pacific) must
    # NOT be due yet. An unnormalized store ("2026-12-15T09:00:00" stored
    # verbatim) would wrongly say it's due here, since the lexicographic
    # string "09" < "12" even though the real due instant (17:00 UTC) is
    # still 5 hours in the future — this query time is chosen specifically
    # so string-comparison coincidence can't make the test pass by accident.
    monkeypatch.setattr(config, "TIMEZONE", "America/Los_Angeles")
    note_id = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")["note_id"]
    cid = tools.create_commitment(tmp_db_conn, note_id, "x", "2026-12-15")["commitment_id"]
    tools.schedule_reminder(tmp_db_conn, cid, "2026-12-15T09:00:00", "text")

    not_yet_due = db.get_due_reminders(tmp_db_conn, "2026-12-15T12:00:00+00:00")
    assert not_yet_due == []

    due = db.get_due_reminders(tmp_db_conn, "2026-12-15T17:00:00+00:00")
    assert len(due) == 1


def test_schedule_reminder_rejects_unknown_commitment(tmp_db_conn):
    # Final review Important #8: "at most one reminder per commitment,
    # ever" was only prompt-enforced, with no check that the commitment
    # even exists.
    with pytest.raises(tools.ToolError):
        tools.schedule_reminder(tmp_db_conn, 999, "2026-11-02T09:00:00", "text")


def test_schedule_reminder_rejects_dismissed_commitment(tmp_db_conn):
    note_id = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")["note_id"]
    cid = tools.create_commitment(tmp_db_conn, note_id, "x", "2026-11-02")["commitment_id"]
    db.dismiss_commitment(tmp_db_conn, cid)
    with pytest.raises(tools.ToolError):
        tools.schedule_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "text")


def test_schedule_reminder_rejects_duplicate_for_same_commitment(tmp_db_conn):
    note_id = tools.add_note(tmp_db_conn, "x", "ask", "2026-10-30")["note_id"]
    cid = tools.create_commitment(tmp_db_conn, note_id, "x", "2026-11-02")["commitment_id"]
    tools.schedule_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "text")
    with pytest.raises(tools.ToolError):
        tools.schedule_reminder(tmp_db_conn, cid, "2026-11-02T10:00:00", "second attempt")


def test_tool_schemas_cover_all_handlers():
    schema_names = {s["name"] for s in tools.TOOL_SCHEMAS}
    assert schema_names == set(tools.TOOL_HANDLERS.keys())
    assert schema_names == {
        "add_note", "search_notes", "create_commitment",
        "list_open_commitments", "mark_done", "schedule_reminder",
    }


# --- Dogfooding fixes (2026-11-06) -------------------------------------

def test_mark_done_without_reaction_closes_commitment(tmp_db_conn):
    # The bot asked for "her reaction" when the user only said "done".
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    tools.mark_done(tmp_db_conn, cid)
    assert db.list_open_commitments(tmp_db_conn) == []


def test_mark_done_schema_does_not_require_reaction():
    schema = next(s for s in tools.TOOL_SCHEMAS if s["name"] == "mark_done")
    assert schema["input_schema"]["required"] == ["id"]
    assert "reaction" in schema["input_schema"]["properties"]
