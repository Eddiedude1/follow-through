import json
import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('ask', 'preference', 'context')),
            source_date TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER NOT NULL REFERENCES notes(id),
            act TEXT NOT NULL,
            due TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed')),
            reaction TEXT,
            done_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commitment_id INTEGER NOT NULL REFERENCES commitments(id),
            when_ts TEXT NOT NULL,
            text TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(commitment_id)
        );

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note TEXT NOT NULL,
            replied_to_text TEXT NOT NULL DEFAULT '',
            recent_turns TEXT NOT NULL DEFAULT '[]',
            code_version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'addressed')),
            addressed_in TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def insert_note(conn: sqlite3.Connection, text: str, type: str, source_date: str) -> int:
    cur = conn.execute(
        "INSERT INTO notes (text, type, source_date) VALUES (?, ?, ?)",
        (text, type, source_date),
    )
    conn.commit()
    return cur.lastrowid


def search_notes(conn: sqlite3.Connection, query: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM notes WHERE text LIKE ? ORDER BY created_at DESC",
        (f"%{query}%",),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def insert_commitment(conn: sqlite3.Connection, note_id: int, act: str, due: str) -> int:
    cur = conn.execute(
        "INSERT INTO commitments (note_id, act, due, status) VALUES (?, ?, ?, 'open')",
        (note_id, act, due),
    )
    conn.commit()
    return cur.lastrowid


def list_open_commitments(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM commitments WHERE status = 'open' ORDER BY due ASC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_commitment_due(conn: sqlite3.Connection, commitment_id: int, due: str) -> None:
    conn.execute(
        "UPDATE commitments SET due = ? WHERE id = ?",
        (due, commitment_id),
    )
    conn.commit()


def dismiss_commitment(conn: sqlite3.Connection, commitment_id: int) -> None:
    conn.execute(
        "UPDATE commitments SET status = 'dismissed' WHERE id = ?",
        (commitment_id,),
    )
    conn.commit()


def mark_commitment_done(
    conn: sqlite3.Connection, commitment_id: int, reaction: str | None = None
) -> None:
    conn.execute(
        """
        UPDATE commitments
        SET status = 'done', reaction = ?, done_at = datetime('now')
        WHERE id = ?
        """,
        (reaction, commitment_id),
    )
    conn.commit()


def insert_reminder(conn: sqlite3.Connection, commitment_id: int, when_ts: str, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO reminders (commitment_id, when_ts, text) VALUES (?, ?, ?)",
        (commitment_id, when_ts, text),
    )
    conn.commit()
    return cur.lastrowid


def get_due_reminders(conn: sqlite3.Connection, now: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT reminders.*
        FROM reminders
        JOIN commitments ON commitments.id = reminders.commitment_id
        WHERE reminders.sent = 0
          AND reminders.when_ts <= ?
          AND commitments.status = 'open'
        ORDER BY reminders.when_ts ASC
        """,
        (now,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def mark_reminder_sent(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute(
        "UPDATE reminders SET sent = 1 WHERE id = ?",
        (reminder_id,),
    )
    conn.commit()


def get_unsent_reminder_for_commitment(conn: sqlite3.Connection, commitment_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM reminders WHERE commitment_id = ? AND sent = 0 ORDER BY id DESC LIMIT 1",
        (commitment_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def update_reminder_when(conn: sqlite3.Connection, reminder_id: int, when_ts: str) -> None:
    conn.execute(
        "UPDATE reminders SET when_ts = ? WHERE id = ?",
        (when_ts, reminder_id),
    )
    conn.commit()


def insert_feedback(
    conn: sqlite3.Connection,
    note: str,
    replied_to_text: str,
    recent_turns: list[dict],
    code_version: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO feedback (note, replied_to_text, recent_turns, code_version)
        VALUES (?, ?, ?, ?)
        """,
        (note, replied_to_text, json.dumps(recent_turns), code_version),
    )
    conn.commit()
    return cursor.lastrowid


def list_feedback(conn: sqlite3.Connection, status: str = "new") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM feedback WHERE status = ? ORDER BY id ASC", (status,)
    ).fetchall()
    flags = [_row_to_dict(r) for r in rows]
    for flag in flags:
        flag["recent_turns"] = json.loads(flag["recent_turns"])
    return flags


def mark_feedback_addressed(conn: sqlite3.Connection, feedback_id: int, commit: str) -> bool:
    cursor = conn.execute(
        """
        UPDATE feedback SET status = 'addressed', addressed_in = ?
        WHERE id = ? AND status = 'new'
        """,
        (commit, feedback_id),
    )
    conn.commit()
    return cursor.rowcount == 1
