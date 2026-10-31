import pytest

from follow_through import tools


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


def test_tool_schemas_cover_all_handlers():
    schema_names = {s["name"] for s in tools.TOOL_SCHEMAS}
    assert schema_names == set(tools.TOOL_HANDLERS.keys())
    assert schema_names == {
        "add_note", "search_notes", "create_commitment",
        "list_open_commitments", "mark_done", "schedule_reminder",
    }
