from follow_through import config, db, scheduler


def test_fire_due_reminders_calls_send_fn_for_each_due(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    sent = []
    count = scheduler.fire_due_reminders(tmp_db_conn, "2026-11-02T09:00:00", sent.append)
    assert count == 1
    assert sent[0]["text"] == "reminder text"


def test_fire_due_reminders_marks_sent_so_it_does_not_refire(tmp_db_conn):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    scheduler.fire_due_reminders(tmp_db_conn, "2026-11-02T09:00:00", lambda r: None)
    count_again = scheduler.fire_due_reminders(tmp_db_conn, "2026-11-02T09:00:00", lambda r: None)
    assert count_again == 0


def test_fire_due_reminders_skips_done_commitment(tmp_db_conn):
    # Review Focus, re-verified at the scheduler boundary
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    db.insert_reminder(tmp_db_conn, cid, "2026-11-02T09:00:00", "reminder text")
    db.mark_commitment_done(tmp_db_conn, cid, "done already")
    count = scheduler.fire_due_reminders(tmp_db_conn, "2026-11-02T09:00:00", lambda r: None)
    assert count == 0


def test_connect_initializes_schema_on_a_fresh_db(tmp_path, monkeypatch):
    # Final review Critical #2: production entry points never called
    # init_schema, so a fresh Pi crash-loops with "no such table".
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "fresh.db"))
    conn = scheduler._connect()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"notes", "commitments", "reminders"} <= tables
