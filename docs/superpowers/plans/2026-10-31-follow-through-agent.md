# Follow Through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 Follow Through system — a Telegram bot backed by a raw Claude tool-calling loop that captures things my wife mentions, turns actionable ones into committed acts with a single due-date nudge, and tracks them to close, running unattended on a home Pi.

**Architecture:** A single SQLite file (`notes`, `commitments`, `reminders`) sits behind a small `db.py` access layer. Six Claude-callable tools (`tools.py`) wrap that layer. A hand-rolled tool-calling loop (`agent.py`) is the interface-agnostic agent core — one `run_agent()` call per captured Telegram message, each call logged. A thin Telegram adapter (`bot.py`) is the only thing that's interface-specific; it also owns the two deterministic, non-model button actions (edit due date, dismiss) that the spec implies but doesn't route through the model. A dumb fixed-cadence `scheduler.py` fires pre-composed reminder text with no model call. The eval harness reuses `run_agent()` against a throwaway DB rather than a parallel classification code path, so eval measures the real system. Task order follows engineering dependency order (db → tools → agent → eval/nudging → scheduler → bot → deploy), not the spec's Build Order numbering, since the eval harness and bot both depend on the agent core existing first.

**Tech Stack:** Python 3.11+, `anthropic` SDK, `python-telegram-bot` v21+, stdlib `sqlite3`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-10-30-follow-through-agent-design.md`

## Global Constraints

- Max 15 tool-call steps per agent run; if `end_turn` isn't reached by then, stop and return a clear "step limit reached" result rather than looping forever.
- Tool errors are returned to the model as a `tool_result` with `is_error: true` — never swallowed, never raised past the loop.
- Every agent run is logged (one record per run: timestamp, model, steps used, tool calls made).
- Model: `claude-sonnet-5-5` by default, `output_config.effort` low/medium. `claude-haiku-5-5` must be swappable for the same code path (A/B in the eval harness).
- One SQLite file; exactly three tables: `notes`, `commitments`, `reminders`. `reminders.text` holds the fully composed nudge — the scheduler never calls the model.
- Single user. No calendar integration. No automatic multi-step chaining — an ask gets only its first concrete step as a commitment.
- No escalation ladder: at most one reminder per commitment, ever.
- The real hand-labeled eval set is never committed (`.gitignore`d); only a fictionalized sample set is committed.
- Secrets (`TELEGRAM_BOT_TOKEN`, `ANTHROPIC_API_KEY`) load from `.env`, which is `.gitignore`d.

## Review Focus

- A captured note with no actionable content (pure observation, no ask) produces zero commitments — the model must not hallucinate an act from nothing. (Task 3)
- A tool call that raises (e.g. a malformed due date) surfaces to the model as `tool_result` with `is_error: true`, and the loop continues instead of crashing. (Task 2 / Task 3)
- An agent run that never reaches `end_turn` within 15 steps stops cleanly with a reportable result instead of looping forever or raising. (Task 3)
- A reminder whose commitment was already marked done before the reminder's scheduled time must not fire — the scheduler is dumb, so this has to be enforced in the query, not at send time. (Task 1, exercised again in Task 6)
- A single captured note containing two distinct, unrelated asks becomes two separate notes and two separate commitments, not one merged item. (Task 3)

---

### Task 1: Database schema & access layer

**Files:**
- Create: `follow_through/__init__.py`
- Create: `follow_through/config.py`
- Create: `follow_through/db.py`
- Test: `tests/test_db.py`
- Create: `tests/conftest.py`
- Create: `.env.example`
- Create: `requirements.txt`

**Interfaces:**
- Produces: `config.DB_PATH: str` (from `FOLLOW_THROUGH_DB_PATH` env var, default `follow_through.db`), `config.ANTHROPIC_API_KEY: str`, `config.TELEGRAM_BOT_TOKEN: str` (all loaded via `python-dotenv`).
- Produces: `db.connect(db_path: str) -> sqlite3.Connection`
- Produces: `db.init_schema(conn: sqlite3.Connection) -> None` — creates `notes(id, text, type, source_date, created_at)`, `commitments(id, note_id, act, due, status, reaction, done_at, created_at)` with `status` constrained to `'open'|'done'|'dismissed'`, `reminders(id, commitment_id, when_ts, text, sent, created_at)`. `due` and `when_ts` are ISO 8601 strings.
- Produces: `db.insert_note(conn, text: str, type: str, source_date: str) -> int`
- Produces: `db.search_notes(conn, query: str) -> list[dict]` — simple `LIKE` match on `text`, newest first.
- Produces: `db.insert_commitment(conn, note_id: int, act: str, due: str) -> int` — inserts with `status='open'`.
- Produces: `db.list_open_commitments(conn) -> list[dict]` — `WHERE status='open'`.
- Produces: `db.update_commitment_due(conn, commitment_id: int, due: str) -> None`
- Produces: `db.dismiss_commitment(conn, commitment_id: int) -> None` — sets `status='dismissed'`.
- Produces: `db.mark_commitment_done(conn, commitment_id: int, reaction: str) -> None` — sets `status='done'`, `reaction`, `done_at`.
- Produces: `db.insert_reminder(conn, commitment_id: int, when_ts: str, text: str) -> int`
- Produces: `db.get_due_reminders(conn, now: str) -> list[dict]` — `WHERE sent=0 AND when_ts <= now AND commitment.status='open'` (join to `commitments`).
- Produces: `db.mark_reminder_sent(conn, reminder_id: int) -> None`

- [ ] **Step 1: Write failing tests for schema + CRUD**

```python
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
```

Add a `tmp_db_conn` pytest fixture in `tests/conftest.py` that creates an in-memory (`:memory:`) connection and calls `db.init_schema`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — `db` module / functions don't exist yet.

- [ ] **Step 3: Implement `follow_through/config.py` and `follow_through/db.py`**

`config.py` loads `.env` via `python-dotenv` and exposes the three constants above. `db.py` implements the schema and functions listed in Interfaces. Use parameterized queries throughout (no string-formatted SQL). `.env.example` lists `TELEGRAM_BOT_TOKEN=`, `ANTHROPIC_API_KEY=`, `FOLLOW_THROUGH_DB_PATH=follow_through.db`. `requirements.txt`: `anthropic`, `python-telegram-bot`, `python-dotenv`, `pytest`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add follow_through/ tests/test_db.py tests/conftest.py .env.example requirements.txt
git commit -m "feat: add SQLite schema and db access layer"
```

---

### Task 2: Tool implementations

**Files:**
- Create: `follow_through/tools.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: every `db.*` function from Task 1.
- Produces: `tools.ToolError(Exception)` — raised for invalid tool input (e.g. unparseable date).
- Produces: six functions, each `(conn, **kwargs) -> dict` (JSON-serializable), each raising `ToolError` on bad input:
  - `add_note(conn, text: str, type: str, source_date: str) -> {"note_id": int}` — `type` must be one of `ask`/`preference`/`context`, else `ToolError`.
  - `search_notes(conn, query: str) -> {"notes": list[dict]}`
  - `create_commitment(conn, note_id: int, act: str, due: str) -> {"commitment_id": int}` — `due` must parse as `YYYY-MM-DD`, else `ToolError`.
  - `list_open_commitments(conn) -> {"commitments": list[dict]}`
  - `mark_done(conn, id: int, reaction: str) -> {"status": "done"}` — `ToolError` if `id` doesn't exist or isn't open.
  - `schedule_reminder(conn, id: int, when: str, text: str) -> {"reminder_id": int}` — `when` must parse as ISO 8601 datetime, else `ToolError`.
- Produces: `tools.TOOL_SCHEMAS: list[dict]` — Anthropic tool definitions (`name`, `description`, `input_schema`) for the six functions above, `strict: true`.
- Produces: `tools.TOOL_HANDLERS: dict[str, Callable]` — maps each tool name to its function.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL — `tools` module doesn't exist yet.

- [ ] **Step 3: Implement `follow_through/tools.py`**

Each function validates input, raises `ToolError` with a message useful to the model on failure, then delegates to the matching `db.*` call. Write `TOOL_SCHEMAS` so each `input_schema` has `additionalProperties: false` and lists `required` fields, matching the Tools table in the spec.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add follow_through/tools.py tests/test_tools.py
git commit -m "feat: add Claude-callable tool wrappers with input validation"
```

---

### Task 3: Agent core (tool-calling loop)

**Files:**
- Create: `follow_through/agent.py`
- Test: `tests/test_agent.py`
- Modify: `tests/conftest.py` (add `FakeAnthropicClient`, `fake_tool_use_response`, `fake_text_response`)

**Interfaces:**
- Consumes: `tools.TOOL_SCHEMAS`, `tools.TOOL_HANDLERS`, `tools.ToolError` from Task 2.
- Produces: `agent.AgentResult` (dataclass): `final_text: str`, `steps_used: int`, `stopped_reason: Literal["end_turn", "step_limit"]`, `log: list[dict]`.
- Produces: `agent.MAX_STEPS = 15`
- Produces: `agent.run_agent(conn, user_message: str, client, model: str = "claude-sonnet-5-5", max_steps: int = MAX_STEPS) -> AgentResult` — `client` is an injected Anthropic-SDK-shaped client (constructor param, not a module-level singleton) so tests can pass a stub.
- Produces: `agent.SYSTEM_PROMPT: str` — instructs the model on the capture→structure→commit→nudge loop per the spec's "Where the Model Makes Decisions" section (narrow first-step acts only, compose nudge text with `search_notes` context at commit time, never chain multi-step asks).
- Produces: `agent.log_run(result: AgentResult) -> None` — appends one JSON line to the log file at `config.LOG_PATH` (add `LOG_PATH` to `config.py` in this task, default `follow_through.log`).

- [ ] **Step 1: Write failing tests using a stub Anthropic client**

Build a `FakeAnthropicClient` test helper in `tests/conftest.py` that returns a scripted sequence of `Message`-shaped responses (`stop_reason`, `content` blocks) per call, so tests control the model's behavior without a real API call.

```python
def test_no_actionable_content_creates_no_commitments(tmp_db_conn):
    # Review Focus: pure observation, no ask -> zero commitments
    client = FakeAnthropicClient([
        fake_text_response("Got it, just noting that."),
    ])
    agent.run_agent(tmp_db_conn, "the weather was nice today", client)
    assert db.list_open_commitments(tmp_db_conn) == []

def test_tool_error_returned_as_is_error_not_raised(tmp_db_conn):
    # Review Focus: tool error surfaces to the model, loop doesn't crash
    client = FakeAnthropicClient([
        fake_tool_use_response("create_commitment",
            {"note_id": 999, "act": "x", "due": "bad-date"}),
        fake_text_response("Fixed, retrying."),
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client)
    assert result.log[0]["tool_result"]["is_error"] is True

def test_step_limit_stops_loop_cleanly(tmp_db_conn):
    # Review Focus: never reaching end_turn stops at MAX_STEPS, doesn't hang
    client = FakeAnthropicClient([
        fake_tool_use_response("search_notes", {"query": "x"})
        for _ in range(20)
    ])
    result = agent.run_agent(tmp_db_conn, "some ask", client, max_steps=15)
    assert result.steps_used == 15
    assert result.stopped_reason == "step_limit"

def test_two_distinct_asks_become_two_commitments(tmp_db_conn):
    # Review Focus: multiple asks in one note -> separate commitments
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "take out the trash", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("add_note",
            {"text": "call the dentist", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 1, "act": "take out the trash", "due": "2026-11-01"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 2, "act": "call the dentist", "due": "2026-11-03"}),
        fake_text_response("Logged both."),
    ])
    agent.run_agent(tmp_db_conn, "take out the trash and also call the dentist", client)
    assert len(db.list_open_commitments(tmp_db_conn)) == 2

def test_run_is_logged(tmp_db_conn, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOG_PATH", str(tmp_path / "run.log"))
    client = FakeAnthropicClient([fake_text_response("noted")])
    agent.run_agent(tmp_db_conn, "the weather was nice", client)
    assert (tmp_path / "run.log").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL — `agent` module doesn't exist yet.

- [ ] **Step 3: Implement `follow_through/agent.py`**

`run_agent` loops: call `client.messages.create(model=model, system=SYSTEM_PROMPT, tools=tools.TOOL_SCHEMAS, messages=messages)`; while `response.stop_reason == "tool_use"` and `steps_used < max_steps`, execute every `tool_use` block via `tools.TOOL_HANDLERS`, catching `tools.ToolError` into a `tool_result` block with `is_error: true` (per Global Constraints — never let `ToolError` propagate out of the loop), append all results in one `user` message (parallel tool use), increment `steps_used`, call again. On `end_turn`, return `AgentResult(stopped_reason="end_turn", ...)`. On reaching `max_steps` without `end_turn`, return `AgentResult(stopped_reason="step_limit", ...)` instead of looping further. Call `log_run(result)` before returning in both cases.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add follow_through/agent.py follow_through/config.py tests/test_agent.py tests/conftest.py
git commit -m "feat: add Claude tool-calling agent core with step limit and run logging"
```

---

### Task 4: Eval harness + fictionalized sample set

**Files:**
- Create: `eval/run_eval.py`
- Create: `eval/sample/labeled_notes.json`
- Test: `tests/test_eval.py`

**Interfaces:**
- Consumes: `agent.run_agent`, `db.init_schema`, `db.connect` from Tasks 1 & 3.
- Produces: `eval.run_eval.load_labeled_set(path: str) -> list[dict]` — each item `{"text": str, "expected_types": list[str]}` (one entry per item the note should split into, e.g. two `"ask"` entries for a two-ask note).
- Produces: `eval.run_eval.EvalReport` (dataclass): `precision: float`, `recall: float`, `by_type: dict[str, dict]`, `total_examples: int`.
- Produces: `eval.run_eval.evaluate(labeled_set_path: str, client, model: str) -> EvalReport` — for each example, runs `agent.run_agent` against a fresh in-memory DB, reads back `notes` rows, compares `type` counts to `expected_types`, aggregates precision/recall per type.
- `eval/sample/labeled_notes.json`: 5-8 fictionalized examples (not real content — generic household/relationship examples) covering all three types and at least one multi-ask example, committed to the repo per the spec's Repository section.

- [ ] **Step 1: Write failing tests**

```python
def test_load_labeled_set_reads_json(tmp_path):
    p = tmp_path / "set.json"
    p.write_text(json.dumps([{"text": "x", "expected_types": ["ask"]}]))
    items = run_eval.load_labeled_set(str(p))
    assert items == [{"text": "x", "expected_types": ["ask"]}]

def test_evaluate_computes_perfect_precision_recall(tmp_path):
    p = tmp_path / "set.json"
    p.write_text(json.dumps([{"text": "take out the trash", "expected_types": ["ask"]}]))
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "take out the trash", "type": "ask", "source_date": "2026-10-31"}),
        fake_text_response("done"),
    ])
    report = run_eval.evaluate(str(p), client, model="claude-sonnet-5-5")
    assert report.precision == 1.0
    assert report.recall == 1.0

def test_sample_eval_set_is_valid():
    items = run_eval.load_labeled_set("eval/sample/labeled_notes.json")
    assert len(items) >= 5
    assert all(set(i["expected_types"]) <= {"ask", "preference", "context"} for i in items)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_eval.py -v`
Expected: FAIL — `eval/run_eval.py` and the sample set don't exist yet.

- [ ] **Step 3: Implement `eval/run_eval.py` and write `eval/sample/labeled_notes.json`**

Precision/recall defined per-example on the multiset of extracted `type` values vs. `expected_types` (order-independent). Write the fictionalized sample examples by hand — generic household/relationship scenarios, no real content.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_eval.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add eval/ tests/test_eval.py
git commit -m "feat: add eval harness and fictionalized sample eval set"
```

---

### Task 5: Nudge composition & proactive suggestion

**Files:**
- Modify: `follow_through/agent.py` (extend `SYSTEM_PROMPT`; add `get_proactive_suggestion`)
- Test: `tests/test_agent.py` (append)

**Interfaces:**
- Consumes: `tools.search_notes`, `tools.list_open_commitments` from Task 2; `agent.AgentResult`, injected `client` pattern from Task 3.
- Produces: `agent.get_proactive_suggestion(conn, client, model: str = "claude-sonnet-5-5") -> str | None` — a single Claude call (may use `search_notes`/`list_open_commitments` as tools) that returns at most one short suggestion string, or `None` if nothing relevant is found. Never writes to the DB — purely informational, per the spec's Out of Scope line that proactive suggestions never become commitments or reminders.
- `SYSTEM_PROMPT` gains explicit instructions: after calling `create_commitment` for an ask, call `search_notes` for related `preference`/`context` notes and compose the `schedule_reminder` `text` to include anything relevant found, with the reminder `when` on or before the commitment's `due` date.

- [ ] **Step 1: Write failing tests**

```python
def test_schedule_reminder_called_after_create_commitment(tmp_db_conn):
    client = FakeAnthropicClient([
        fake_tool_use_response("add_note",
            {"text": "organize the garage", "type": "ask", "source_date": "2026-10-31"}),
        fake_tool_use_response("create_commitment",
            {"note_id": 1, "act": "organize the garage", "due": "2026-11-02"}),
        fake_tool_use_response("schedule_reminder",
            {"id": 1, "when": "2026-11-02T09:00:00", "text": "Organize the garage today."}),
        fake_text_response("Logged and scheduled."),
    ])
    agent.run_agent(tmp_db_conn, "organize the garage", client)
    due = db.get_due_reminders(tmp_db_conn, "2026-11-02T09:00:00")
    assert due[0]["text"] == "Organize the garage today."

def test_proactive_suggestion_returns_none_when_nothing_relevant(tmp_db_conn):
    client = FakeAnthropicClient([fake_text_response("")])
    result = agent.get_proactive_suggestion(tmp_db_conn, client)
    assert result is None

def test_proactive_suggestion_never_writes_commitments(tmp_db_conn):
    db.insert_note(tmp_db_conn, "she's been stressed about work", "context", "2026-10-30")
    client = FakeAnthropicClient([
        fake_text_response("Maybe take dinner off her plate tonight."),
    ])
    suggestion = agent.get_proactive_suggestion(tmp_db_conn, client)
    assert suggestion == "Maybe take dinner off her plate tonight."
    assert db.list_open_commitments(tmp_db_conn) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent.py -v -k "reminder or proactive"`
Expected: FAIL — `get_proactive_suggestion` doesn't exist; `SYSTEM_PROMPT` doesn't yet direct nudge composition.

- [ ] **Step 3: Extend `follow_through/agent.py`**

Add `get_proactive_suggestion` as a minimal single-call-or-short-loop path (reuse the same tool-dispatch helper `run_agent` uses internally rather than duplicating it) that only ever reads (`search_notes`, `list_open_commitments`) and returns the final text, or `None` if the model's final text is empty/declines to suggest anything. Update `SYSTEM_PROMPT` per the Interfaces note above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent.py -v`
Expected: PASS (all agent tests, including the 3 new ones)

- [ ] **Step 5: Commit**

```bash
git add follow_through/agent.py tests/test_agent.py
git commit -m "feat: compose nudge text with related context, add proactive suggestions"
```

---

### Task 6: Scheduler

**Files:**
- Create: `follow_through/scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.get_due_reminders`, `db.mark_reminder_sent` from Task 1.
- Produces: `scheduler.fire_due_reminders(conn, now: str, send_fn: Callable[[dict], None]) -> int` — queries due reminders, calls `send_fn(reminder_dict)` for each, marks each sent, returns count fired. Never calls the model (Global Constraints).
- Produces: `scheduler.run_forever(conn, send_fn, poll_seconds: int = 1800) -> None` — thin loop calling `fire_due_reminders` with `now = datetime.utcnow().isoformat()`, then `time.sleep(poll_seconds)`. Not unit tested directly (infinite loop); `fire_due_reminders` carries the test coverage.

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL — `scheduler` module doesn't exist yet.

- [ ] **Step 3: Implement `follow_through/scheduler.py`**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add follow_through/scheduler.py tests/test_scheduler.py
git commit -m "feat: add fixed-cadence reminder scheduler"
```

---

### Task 7: Telegram bot adapter

**Files:**
- Create: `follow_through/bot.py`
- Test: `tests/test_bot.py`
- Modify: `tests/conftest.py` (add `fake_update`, `fake_context`, `fake_callback_query`)

**Interfaces:**
- Consumes: `agent.run_agent`, `agent.get_proactive_suggestion` (Tasks 3 & 5), `db.list_open_commitments`, `db.update_commitment_due`, `db.dismiss_commitment` (Task 1), `scheduler.run_forever` (Task 6).
- Produces: `bot.handle_message(update, context) -> None` — calls `agent.run_agent` with the message text, replies with `result.final_text`, and if any commitments were created this run (diff `db.list_open_commitments` before/after, or read `result.log` for `create_commitment` tool results), sends one message per new commitment with an inline keyboard: `Confirm` (no-op, just clears the keyboard), `Edit due date` (prompts for free-text date, then calls `db.update_commitment_due` directly — no model call), `Dismiss` (calls `db.dismiss_commitment` directly — no model call).
- Produces: `bot.handle_open(update, context) -> None` — `/open`, lists `db.list_open_commitments`.
- Produces: `bot.handle_week(update, context) -> None` — `/week`, lists commitments due within 7 days, then calls `agent.get_proactive_suggestion`; if not `None`, appends it as a clearly-labeled suggestion line.
- Produces: `bot.handle_done_reply(update, context) -> None` — invoked after a `Done` tap prompts for a reaction; takes the free-text reply and routes it through `agent.run_agent` so the model calls `mark_done`.
- Produces: `bot.send_reminder(reminder: dict) -> None` — the `send_fn` passed to `scheduler.run_forever`; sends `reminder["text"]` to the single configured chat ID.
- Produces: `bot.build_app() -> telegram.ext.Application` — registers all handlers, used by `main()`.

- [ ] **Step 1: Write failing tests using python-telegram-bot's test doubles**

```python
@pytest.mark.asyncio
async def test_handle_open_lists_open_commitments(tmp_db_conn, fake_update, fake_context):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    db.insert_commitment(tmp_db_conn, note_id, "organize the garage", "2026-11-02")
    await bot.handle_open(fake_update, fake_context)
    assert "organize the garage" in fake_update.message.replies[0]

@pytest.mark.asyncio
async def test_dismiss_button_calls_dismiss_commitment_directly(tmp_db_conn, fake_callback_query):
    note_id = db.insert_note(tmp_db_conn, "x", "ask", "2026-10-30")
    cid = db.insert_commitment(tmp_db_conn, note_id, "x", "2026-11-02")
    fake_callback_query.data = f"dismiss:{cid}"
    await bot.handle_button(fake_callback_query.update, fake_callback_query.context)
    assert db.list_open_commitments(tmp_db_conn) == []

@pytest.mark.asyncio
async def test_week_appends_proactive_suggestion(tmp_db_conn, fake_update, fake_context, monkeypatch):
    monkeypatch.setattr(agent, "get_proactive_suggestion", lambda conn, client: "Take dinner off her plate tonight.")
    await bot.handle_week(fake_update, fake_context)
    assert "Take dinner off her plate tonight." in fake_update.message.replies[-1]
```

Add `fake_update`/`fake_context`/`fake_callback_query` fixtures in `tests/conftest.py` — minimal stand-ins exposing `.message.reply_text` (recording to a `.replies` list) and `.bot_data["conn"]`, following `python-telegram-bot`'s `ContextTypes.DEFAULT_TYPE` shape.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_bot.py -v`
Expected: FAIL — `bot` module doesn't exist yet.

- [ ] **Step 3: Implement `follow_through/bot.py`**

Store the SQLite connection and Anthropic client on `application.bot_data` so handlers can reach them via `context.bot_data`. Use `telegram.InlineKeyboardMarkup`/`InlineKeyboardButton` with `callback_data` encoding `"<action>:<commitment_id>"`, dispatched from one `handle_button` callback-query handler via a dict keyed on the action prefix.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_bot.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add follow_through/bot.py tests/test_bot.py tests/conftest.py
git commit -m "feat: add Telegram bot adapter with /open, /week, and confirm/edit/dismiss/done buttons"
```

---

### Task 8: Deployment — systemd units & backup

**Files:**
- Create: `follow_through/backup.py`
- Create: `deploy/follow-through-bot.service`
- Create: `deploy/follow-through-scheduler.service`
- Create: `deploy/README.md`
- Test: `tests/test_backup.py`

**Interfaces:**
- Consumes: `config.DB_PATH`.
- Produces: `backup.backup_once(db_path: str, dest_dir: str) -> str` — copies the SQLite file to `dest_dir` with a timestamped filename (`follow_through-YYYYMMDD.db`), returns the destination path. Uses `shutil.copyfile` on the live file (acceptable for SQLite given WAL is off / default rollback-journal mode and the copy is infrequent and low-stakes for a single-user hobby DB).
- Produces: `backup.run_forever(db_path: str, dest_dir: str, interval_seconds: int = 86400) -> None` — thin loop, not unit tested directly; `backup_once` carries the coverage.
- `deploy/*.service`: systemd unit files (`ExecStart=python3 -m follow_through.bot` / `python3 -m follow_through.scheduler` / `python3 -m follow_through.backup`, `Restart=always`, `WorkingDirectory=`, `EnvironmentFile=.env`).
- `deploy/README.md`: install steps for the Pi (clone repo, `pip install -r requirements.txt`, copy `.env.example` to `.env` and fill in secrets, point `dest_dir` at the mounted/synced cloud storage folder, `systemctl enable --now` the three units).

- [ ] **Step 1: Write failing tests**

```python
def test_backup_once_copies_db_with_timestamped_name(tmp_path):
    src = tmp_path / "follow_through.db"
    src.write_text("fake db contents")
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    dest_path = backup.backup_once(str(src), str(dest_dir))
    assert Path(dest_path).read_text() == "fake db contents"
    assert Path(dest_path).parent == dest_dir

def test_backup_once_raises_if_source_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.backup_once(str(tmp_path / "missing.db"), str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backup.py -v`
Expected: FAIL — `backup` module doesn't exist yet.

- [ ] **Step 3: Implement `follow_through/backup.py` and the `deploy/` files**

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backup.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add follow_through/backup.py deploy/ tests/test_backup.py
git commit -m "feat: add daily backup script and systemd deployment units"
```
