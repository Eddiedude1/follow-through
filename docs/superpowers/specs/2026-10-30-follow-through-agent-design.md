# Follow Through — v1 Spec

## Purpose

Help me capture the small things my wife mentions, turn the actionable ones into committed acts, and make sure I follow through. The agent plans, remembers, and nudges. I do the acts.

Her top love language is Acts of Service. The research on it is specific about the single biggest way partners fail at it: lacking follow-through on tasks big and small. This project exists to make sure that failure mode doesn't happen on my watch.

## Core Loop

**capture → structure → commit → nudge → close**

1. **Capture:** I dump a messy free-text note. The agent extracts discrete items and classifies each as `ask` (actionable), `preference` (durable fact), or `context` (situational, time-bound).
2. **Commit:** For each `ask`, the agent proposes a concrete act and a due date. For a multi-step or fuzzy ask (e.g. "organize the garage so the car fits inside, freeing up the driveway"), the agent proposes only the first concrete step — it doesn't try to track or chain the larger goal. Later steps become new commitments only if I mention them again myself. I confirm, edit, or dismiss.
3. **Nudge:** At commit time, the agent composes one due-date-based reminder per commitment — picking the time and writing the full nudge text, including any related `preference`/`context` notes pulled via `search_notes`. That pre-composed text is stored as-is; a scheduler fires it later with no further judgment. There is no escalation ladder in v1 — `/open` and `/week` are my manual staleness check.
4. **Close:** I mark an act done. The agent asks for one line on her reaction and stores it, in full, indefinitely.

Alongside the core loop, `/week` may also surface **one proactive, unprompted act-of-service suggestion**, drawn from stored `preference`/`context` notes — e.g. noticing she's been stressed about work this week and suggesting I take dinner off her plate. This is informational only: no due date, no reminder, no escalation. It rides on a command I already check, not a new nudge channel.

## Where the Model Makes Decisions

- Splitting a note into items and classifying them
- Proposing a specific, narrowly-scoped act and due date (first concrete step only, no multi-step chaining)
- Composing the nudge: picking the due-date-based reminder time, and pulling related preference/context via `search_notes` to bake into the nudge text — done once, at commit time
- When `/week` is invoked, optionally surfacing at most one proactive act-of-service suggestion drawn from stored preference/context notes — informational only, never turned into a commitment or reminder on its own

## Tools

| Tool | Purpose |
| --- | --- |
| `add_note(text, type, source_date)` | Store an extracted item |
| `search_notes(query)` | Retrieve preferences/context |
| `create_commitment(note_id, act, due)` | Turn an ask into a committed act |
| `list_open_commitments()` | See what's pending or stale |
| `mark_done(id, reaction)` | Close a commitment with her reaction |
| `schedule_reminder(id, when, text)` | Queue a nudge with its fully composed text |

`/week`'s proactive suggestion reuses `search_notes` — no new tool needed.

## Storage

Single SQLite file. Tables: `notes`, `commitments`, `reminders` (`reminders.text` holds the fully composed nudge, written once at commit time — the scheduler fires it verbatim and never calls the model).

## Model / API

- Raw Anthropic (Claude) API tool-calling loop, no framework
- **Model: Claude Sonnet 5.5** (`claude-sonnet-5-5`) — classification/extraction/nudge-composition here is lightweight judgment, not long-horizon agentic work, so Sonnet is the right cost/quality balance to start from. Effort: low/medium.
- When the hand-labeled eval set exists (Build Order step 1/4), A/B against **Claude Haiku 5.5** (`claude-haiku-5-5`, ~20x cheaper) on extraction accuracy. For a single-user, low-volume bot, if Haiku clears the accuracy target, prefer it long-term; otherwise stay on Sonnet 5.5. Only escalate to Opus if both undershoot the target.

## v1 Scope

- Telegram bot over long polling (no public endpoint), text input
- Inline buttons for confirm / edit due date / dismiss / done
- `/open` and `/week` commands for action item tracking
- `/week` also surfaces, at most, one proactive suggestion (no due date/reminder) drawn from stored preference/context notes
- Scheduler polls on a fixed cadence (e.g. every 30 min) and fires pre-composed reminder text — no model call at send time
- Agent core stays interface-agnostic; the bot is a thin adapter
- Backend runs on a Raspberry Pi / dedicated home device, always on; no public endpoint needed since long polling is outbound-only
- Daily backup of the SQLite file to cloud storage I already use (e.g. Google Drive), to protect against SD card failure
- Single user
- No calendar integration
- Raw API tool-calling loop, no framework

## Out of Scope (v1)

- Calendar read
- Event-based proactive recall (no event entity, no calendar — recall only happens via explicit `search_notes` or alongside a nudge)
- Escalating/multi-step reminder ladders for stale commitments (`/open`/`/week` is the manual check instead)
- Automatic decomposition or tracking of multi-step asks beyond the first act
- Turning proactive suggestions into automatic commitments, due dates, or nudges — they're informational only, at most one per `/week` call
- Voice notes (Whisper transcription): v1.1
- Doing the acts on my behalf
- Framework port (LangGraph etc.)

## Loop Requirements

- Max-step limit per run
- Tool errors returned to the model, not swallowed
- Full message history managed explicitly
- Every run logged for debugging

## Success Criteria

- **Zero dropped asks:** every `ask` ends as done or explicitly dismissed
- **Commitment completion rate:** done / total committed
- **Median time from capture to done**
- **Extraction accuracy:** measured on a hand-labeled set of \~30 of my own notes (precision/recall on item type)

## Done Means

- I use it daily for 3+ weeks
- Extraction accuracy is at or above my target on the labeled set
- No ask has gone silently stale
- I can explain every failure mode I hit (tool misuse, looping, context bloat, misclassification)

## Build Order

1. Hand-label eval set
2. Schema + tool implementations (no model yet)
3. Raw-API loop
4. Run evals (Sonnet 5.5 vs. Haiku 5.5), iterate
5. Add nudging/reminders
6. Dogfood for 3 weeks
7. Then consider calendar and a framework port

## Repository

- Public GitHub repo, standalone (not nested inside a personal monorepo)
- License: MIT
- The real hand-labeled eval set (~30 of my actual notes) stays local, `.gitignore`d — it's personal content and never gets committed
- A separate, small, fictionalized sample eval set IS committed, so the eval harness is runnable and checkable by others
- No real examples of things she's said, or her real reactions, appear anywhere in committed docs or code — illustrative examples are generic/fictional

## Resolved Questions

- **Privacy:** Telegram (not end-to-end encrypted) is acceptable for v1's content. Revisit a PWA/Tailscale setup only if dogfooding surfaces a real concern.
- **Escalation aggressiveness:** moot — there is no escalation in v1, just a single due-date nudge per commitment.
- **Reaction data:** store it all, indefinitely, tied to its commitment — it's meant to be a lasting record, not just working data, which is why the SQLite file gets a daily backup.
