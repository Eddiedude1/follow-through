import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from follow_through import config, tools

MAX_STEPS = 15

SYSTEM_PROMPT = """\
You help capture the small things a user's wife mentions, and make sure \
actionable ones get followed through on.

For each message:
1. Split it into discrete items and classify each with add_note as `ask` \
(actionable), `preference` (durable fact), or `context` (situational, \
time-bound). A message with no actionable content may produce zero items.
2. For each `ask`, call create_commitment with ONLY the first concrete, \
doable step — never try to chain or plan out the ask's larger goal. If an \
ask implies several steps, commit to just the first one; later steps only \
become commitments if the user mentions them again themselves.
3. If a tool call fails, read the error and adjust your next call \
accordingly — do not repeat the same failing call unchanged.
4. After calling create_commitment for an ask, call search_notes to look \
for related preference/context notes, then call schedule_reminder with a \
single due-date-based reminder: set `when` on or before the commitment's \
`due` date, and write `text` as a short, ready-to-send nudge message that \
includes anything relevant you found via search_notes.

When you are done, reply with a short confirmation of what you logged.
"""

_PROACTIVE_SUGGESTION_PROMPT = """\
Look at open commitments and stored preference/context notes for anything \
that would make a good, low-effort act of service to do unprompted right \
now. If something genuinely stands out, reply with ONE short, concrete \
suggestion in a single sentence. If nothing stands out, reply with an \
empty response — do not force a suggestion. Never propose or create a \
commitment; this is informational only.
"""

_READ_ONLY_TOOL_NAMES = {"search_notes", "list_open_commitments"}
_READ_ONLY_TOOL_SCHEMAS = [s for s in tools.TOOL_SCHEMAS if s["name"] in _READ_ONLY_TOOL_NAMES]
_READ_ONLY_TOOL_HANDLERS = {
    name: handler for name, handler in tools.TOOL_HANDLERS.items() if name in _READ_ONLY_TOOL_NAMES
}


@dataclass
class AgentResult:
    final_text: str
    steps_used: int
    stopped_reason: Literal["end_turn", "step_limit"]
    log: list[dict] = field(default_factory=list)


def _block_to_param(block) -> dict:
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    if block.type == "text":
        return {"type": "text", "text": block.text}
    raise ValueError(f"unexpected content block type: {block.type}")


def _extract_text(content) -> str:
    return "".join(block.text for block in content if block.type == "text")


def _execute_tool_use_blocks(conn, content, handlers: dict) -> tuple[list[dict], list[dict]]:
    tool_results = []
    log_entries = []
    for block in content:
        if block.type != "tool_use":
            continue
        try:
            output = handlers[block.name](conn, **block.input)
            tool_result = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(output),
            }
        except tools.ToolError as e:
            tool_result = {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(e),
                "is_error": True,
            }
        log_entries.append({
            "tool_name": block.name,
            "tool_input": block.input,
            "tool_result": tool_result,
        })
        tool_results.append(tool_result)
    return tool_results, log_entries


def run_agent(
    conn,
    user_message: str,
    client,
    model: str = "claude-sonnet-5-5",
    max_steps: int = MAX_STEPS,
) -> AgentResult:
    messages = [{"role": "user", "content": user_message}]
    steps_used = 0
    log: list[dict] = []

    while True:
        response = client.messages.create(
            model=model,
            system=SYSTEM_PROMPT,
            tools=tools.TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            result = AgentResult(
                final_text=_extract_text(response.content),
                steps_used=steps_used,
                stopped_reason="end_turn",
                log=log,
            )
            log_run(result)
            return result

        if steps_used >= max_steps:
            result = AgentResult(
                final_text="",
                steps_used=steps_used,
                stopped_reason="step_limit",
                log=log,
            )
            log_run(result)
            return result

        messages.append(
            {"role": "assistant", "content": [_block_to_param(b) for b in response.content]}
        )

        tool_results, log_entries = _execute_tool_use_blocks(conn, response.content, tools.TOOL_HANDLERS)
        log.extend(log_entries)

        messages.append({"role": "user", "content": tool_results})
        steps_used += 1


def get_proactive_suggestion(conn, client, model: str = "claude-sonnet-5-5") -> str | None:
    messages = [
        {"role": "user", "content": "Is there a good proactive act-of-service suggestion right now?"}
    ]
    steps_used = 0

    while True:
        response = client.messages.create(
            model=model,
            system=_PROACTIVE_SUGGESTION_PROMPT,
            tools=_READ_ONLY_TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text = _extract_text(response.content).strip()
            return text if text else None

        if steps_used >= MAX_STEPS:
            return None

        messages.append(
            {"role": "assistant", "content": [_block_to_param(b) for b in response.content]}
        )
        tool_results, _log_entries = _execute_tool_use_blocks(
            conn, response.content, _READ_ONLY_TOOL_HANDLERS
        )
        messages.append({"role": "user", "content": tool_results})
        steps_used += 1


def log_run(result: AgentResult) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps_used": result.steps_used,
        "stopped_reason": result.stopped_reason,
        "tool_calls": [entry["tool_name"] for entry in result.log],
    }
    with open(config.LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")
