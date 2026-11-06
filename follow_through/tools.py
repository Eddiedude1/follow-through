import sqlite3
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from follow_through import config, db

VALID_NOTE_TYPES = {"ask", "preference", "context"}


class ToolError(Exception):
    pass


def add_note(conn, text: str, type: str, source_date: str) -> dict:
    if type not in VALID_NOTE_TYPES:
        raise ToolError(f"type must be one of {sorted(VALID_NOTE_TYPES)}, got {type!r}")
    note_id = db.insert_note(conn, text, type, source_date)
    return {"note_id": note_id}


def search_notes(conn, query: str) -> dict:
    notes = db.search_notes(conn, query)
    return {"notes": notes}


def create_commitment(conn, note_id: int, act: str, due: str) -> dict:
    try:
        date.fromisoformat(due)
    except ValueError:
        raise ToolError(f"due must be an ISO 8601 date (YYYY-MM-DD), got {due!r}")
    commitment_id = db.insert_commitment(conn, note_id, act, due)
    return {"commitment_id": commitment_id}


def list_open_commitments(conn) -> dict:
    commitments = db.list_open_commitments(conn)
    return {"commitments": commitments}


def mark_done(conn, id: int, reaction: str | None = None) -> dict:
    open_ids = {c["id"] for c in db.list_open_commitments(conn)}
    if id not in open_ids:
        raise ToolError(f"commitment {id} does not exist or is not open")
    db.mark_commitment_done(conn, id, reaction)
    return {"status": "done"}


def schedule_reminder(conn, id: int, when: str, text: str) -> dict:
    open_ids = {c["id"] for c in db.list_open_commitments(conn)}
    if id not in open_ids:
        raise ToolError(f"commitment {id} does not exist or is not open")

    try:
        parsed = datetime.fromisoformat(when)
    except ValueError:
        raise ToolError(f"when must be an ISO 8601 datetime, got {when!r}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(config.TIMEZONE))
    normalized_when = parsed.astimezone(timezone.utc).isoformat()

    try:
        reminder_id = db.insert_reminder(conn, id, normalized_when, text)
    except sqlite3.IntegrityError:
        raise ToolError(f"commitment {id} already has a reminder scheduled")
    return {"reminder_id": reminder_id}


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "add_note",
        "description": "Store an extracted item from a captured note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "type": {"type": "string", "enum": sorted(VALID_NOTE_TYPES)},
                "source_date": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD)"},
            },
            "required": ["text", "type", "source_date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "search_notes",
        "description": "Retrieve stored preferences/context notes matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "create_commitment",
        "description": "Turn an ask into a committed act with a due date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer"},
                "act": {"type": "string"},
                "due": {"type": "string", "description": "ISO 8601 date (YYYY-MM-DD)"},
            },
            "required": ["note_id", "act", "due"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "list_open_commitments",
        "description": "See what's pending or stale.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "mark_done",
        "description": (
            "Close a commitment. Include her reaction only if the user "
            "volunteered one; omit it otherwise."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "reaction": {"type": "string"},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "schedule_reminder",
        "description": "Queue a nudge with its fully composed text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "when": {"type": "string", "description": "ISO 8601 datetime"},
                "text": {"type": "string"},
            },
            "required": ["id", "when", "text"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

TOOL_HANDLERS = {
    "add_note": add_note,
    "search_notes": search_notes,
    "create_commitment": create_commitment,
    "list_open_commitments": list_open_commitments,
    "mark_done": mark_done,
    "schedule_reminder": schedule_reminder,
}
