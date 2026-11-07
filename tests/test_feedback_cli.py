import pytest

from follow_through import config, db, feedback


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "ft.db")
    monkeypatch.setattr(config, "DB_PATH", path)
    return path


def _seed(path):
    conn = db.connect(path)
    db.init_schema(conn)
    first = db.insert_feedback(
        conn, "wrong item", "Idea: pick up the chicken",
        [{"role": "user", "content": "/week"}], "abc1234",
    )
    second = db.insert_feedback(conn, "already handled", "", [], "abc1234")
    db.mark_feedback_addressed(conn, second, "def5678")
    conn.close()
    return first, second


def test_list_shows_new_flags_with_their_context(db_path, capsys):
    first, _ = _seed(db_path)
    assert feedback.main(["list"]) == 0
    out = capsys.readouterr().out
    assert f"#{first}" in out
    assert "wrong item" in out
    assert "Idea: pick up the chicken" in out
    assert "abc1234" in out
    assert "/week" in out
    assert "already handled" not in out


def test_list_with_nothing_new(db_path, capsys):
    conn = db.connect(db_path)
    db.init_schema(conn)
    conn.close()
    assert feedback.main(["list"]) == 0
    assert "No new feedback" in capsys.readouterr().out


def test_list_before_the_table_exists_does_not_create_it(db_path, capsys):
    # The bot creates the table on its next start; reviewing must not write.
    import sqlite3
    sqlite3.connect(db_path).close()
    assert feedback.main(["list"]) == 0
    assert "No new feedback" in capsys.readouterr().out
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "feedback" not in tables


def test_address_marks_the_flag_and_records_the_commit(db_path, capsys):
    first, _ = _seed(db_path)
    assert feedback.main(["address", str(first), "fff1111"]) == 0
    assert f"#{first}" in capsys.readouterr().out
    conn = db.connect(db_path)
    flags = db.list_feedback(conn, status="addressed")
    assert {f["id"]: f["addressed_in"] for f in flags}[first] == "fff1111"


def test_address_unknown_flag_fails(db_path, capsys):
    _seed(db_path)
    assert feedback.main(["address", "999", "fff1111"]) == 1
    assert "999" in capsys.readouterr().out
