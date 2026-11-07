"""Review feedback flags saved by the bot's /feedback command.

    python -m follow_through.feedback list
    python -m follow_through.feedback address <id> <commit>

`list` is read-only: it never creates the database or the feedback table.
"""
import argparse
import os
import sqlite3

from follow_through import config, db


def _one_line(text: str) -> str:
    return text.replace("\n", " / ")


def _print_flag(flag: dict) -> None:
    print(f"#{flag['id']}  {flag['created_at']} UTC  version {flag['code_version']}")
    print(f"  note: {_one_line(flag['note']) or '(no note)'}")
    if flag["replied_to_text"]:
        print(f"  replying to: {_one_line(flag['replied_to_text'])}")
    if flag["recent_turns"]:
        print("  recent conversation:")
        for turn in flag["recent_turns"]:
            print(f"    {turn['role']}: {_one_line(turn['content'])}")
    print()


def _list() -> int:
    try:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        flags = db.list_feedback(conn)
    except sqlite3.OperationalError:
        # No database yet, or the bot hasn't restarted onto the feedback table.
        flags = []
    if not flags:
        print("No new feedback.")
        return 0
    print(f"{len(flags)} new feedback flag(s):\n")
    for flag in flags:
        _print_flag(flag)
    return 0


def _address(feedback_id: int, commit: str) -> int:
    if not os.path.exists(config.DB_PATH):
        print(f"No database at {config.DB_PATH}.")
        return 1
    conn = db.connect(config.DB_PATH)
    try:
        updated = db.mark_feedback_addressed(conn, feedback_id, commit)
    except sqlite3.OperationalError:
        updated = False
    if not updated:
        print(f"No new feedback #{feedback_id} to mark addressed.")
        return 1
    print(f"Marked #{feedback_id} addressed in {commit}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m follow_through.feedback")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show new feedback flags")
    address = sub.add_parser("address", help="mark a flag addressed")
    address.add_argument("id", type=int)
    address.add_argument("commit")
    args = parser.parse_args(argv)

    if args.command == "list":
        return _list()
    return _address(args.id, args.commit)


if __name__ == "__main__":
    raise SystemExit(main())
