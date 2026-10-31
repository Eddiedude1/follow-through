from follow_through import db


def test_init_schema_creates_tables(tmp_db_conn):
    tables = {r[0] for r in tmp_db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notes", "commitments", "reminders"} <= tables


def test_insert_and_search_notes(tmp_db_conn):
    db.insert_note(tmp_db_conn, "she wants a calmer bedroom", "preference", "2026-10-30")
    results = db.search_notes(tmp_db_conn, "calmer")
    assert len(results) == 1
    assert results[0]["type"] == "preference"


def test_insert_commitment_defaults_to_open(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "organize the garage", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "organize the garage", "2026-11-02")
    assert db.list_open_commitments(tmp_db_conn)[0]["id"] == cid


def test_dismiss_commitment_removes_from_open_list(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.dismiss_commitment(tmp_db_conn, cid)
    assert db.list_open_commitments(tmp_db_conn) == []


def test_mark_done_removes_from_open_list_and_stores_reaction(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.mark_commitment_done(tmp_db_conn, cid, "she loved it")
    assert db.list_open_commitments(tmp_db_conn) == []


def test_get_due_reminders_excludes_closed_commitments(tmp_db_conn):
    # Review Focus: a reminder for an already-done commitment must not fire
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    db.mark_commitment_done(tmp_db_conn, cid, "done early")
    assert db.get_due_reminders(tmp_db_conn, "2026-11-02T09:00:00") == []


def test_get_due_reminders_returns_open_due_unsent(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    rid = db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    due = db.get_due_reminders(tmp_db_conn, "2026-11-02T09:00:00")
    assert [r["id"] for r in due] == [rid]
