import time
from datetime import datetime, timezone
from typing import Callable

from follow_through import db


def fire_due_reminders(conn, now: str, send_fn: Callable[[dict], None]) -> int:
    due = db.get_due_reminders(conn, now)
    for reminder in due:
        send_fn(reminder)
        db.mark_reminder_sent(conn, reminder["id"])
    return len(due)


def run_forever(conn, send_fn: Callable[[dict], None], poll_seconds: int = 1800) -> None:
    while True:
        now = datetime.now(timezone.utc).isoformat()
        fire_due_reminders(conn, now, send_fn)
        time.sleep(poll_seconds)


def _connect():
    from follow_through import config

    conn = db.connect(config.DB_PATH)
    db.init_schema(conn)
    return conn


def main() -> None:
    from follow_through import bot

    conn = _connect()
    run_forever(conn, bot.send_reminder)


if __name__ == "__main__":
    main()
