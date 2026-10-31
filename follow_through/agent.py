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

When you are done, reply with a short confirmation of what you logged.
"""


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

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = tools.TOOL_HANDLERS[block.name](conn, **block.input)
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
            log.append({
                "tool_name": block.name,
                "tool_input": block.input,
                "tool_result": tool_result,
            })
            tool_results.append(tool_result)

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
