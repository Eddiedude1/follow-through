import pytest

from follow_through import db


@pytest.fixture
def tmp_db_conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    yield conn
    conn.close()
