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


def test_get_unsent_reminder_for_commitment_returns_latest_unsent(tmp_db_conn):
    # Final review Important #6: editing a due date needs to find the
    # existing reminder for a commitment so it can be moved.
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    rid = db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    reminder = db.get_unsent_reminder_for_commitment(tmp_db_conn, cid)
    assert reminder["id"] == rid


def test_get_unsent_reminder_for_commitment_returns_none_when_sent(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    rid = db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    db.mark_reminder_sent(tmp_db_conn, rid)
    assert db.get_unsent_reminder_for_commitment(tmp_db_conn, cid) is None


def test_update_reminder_when(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    rid = db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    db.update_reminder_when(tmp_db_conn, rid, "2026-11-05T09:00:00")
    reminder = db.get_unsent_reminder_for_commitment(tmp_db_conn, cid)
    assert reminder["when_ts"] == "2026-11-05T09:00:00"


# --- Feedback flags (2026-11-06) ----------------------------------------

def test_feedback_round_trips_with_context(tmp_db_conn):
    turns = [{"role": "user", "content": "/week"}, {"role": "assistant", "content": "Due..."}]
    fid = db.insert_feedback(
        tmp_db_conn, "wrong item", "Idea: pick up chicken", turns, "abc1234"
    )
    [flag] = db.list_feedback(tmp_db_conn)
    assert flag["id"] == fid
    assert flag["note"] == "wrong item"
    assert flag["replied_to_text"] == "Idea: pick up chicken"
    assert flag["recent_turns"] == turns
    assert flag["code_version"] == "abc1234"
    assert flag["status"] == "new"
    assert flag["created_at"]


def test_mark_feedback_addressed_records_commit_and_hides_it(tmp_db_conn):
    fid = db.insert_feedback(tmp_db_conn, "n", "", [], "abc1234")
    assert db.mark_feedback_addressed(tmp_db_conn, fid, "def5678") is True
    assert db.list_feedback(tmp_db_conn) == []
    [flag] = db.list_feedback(tmp_db_conn, status="addressed")
    assert flag["addressed_in"] == "def5678"


def test_mark_feedback_addressed_rejects_unknown_or_already_addressed(tmp_db_conn):
    fid = db.insert_feedback(tmp_db_conn, "n", "", [], "abc1234")
    assert db.mark_feedback_addressed(tmp_db_conn, 999, "def5678") is False
    assert db.mark_feedback_addressed(tmp_db_conn, fid, "def5678") is True
    assert db.mark_feedback_addressed(tmp_db_conn, fid, "zzz") is False
