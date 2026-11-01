# Follow Through

A personal agent that helps me catch the small things my wife mentions, turn the actionable ones into committed acts, and make sure I actually follow through — without her having to remind me.

Her top love language is Acts of Service, and the research on it is specific about the single biggest way partners fail at it: lacking follow-through on tasks big and small. This project exists to make sure that failure mode doesn't happen on my watch.

**Status:** implemented and deployed — running live on a Raspberry Pi 3.

## How it works

A Telegram bot captures messy free-text notes, classifies each item (`ask` / `preference` / `context`), proposes a concrete act and due date for anything actionable, nudges once at the due date, and asks for a one-line reaction when something's done.

Full design: [`docs/superpowers/specs/2026-10-30-follow-through-agent-design.md`](docs/superpowers/specs/2026-10-30-follow-through-agent-design.md)

Each revision gets its own dated file in `docs/superpowers/specs/`, so the design history is preserved as this evolves.

## Running it

```bash
uv sync
cp .env.example .env   # fill in your own secrets
uv run pytest          # 61 tests
```

For a full from-scratch deployment (flashing a Raspberry Pi, Telegram bot setup, cloud backups, systemd services, troubleshooting), see [`deploy/README.md`](deploy/README.md).

## License

MIT — see [LICENSE](LICENSE).
