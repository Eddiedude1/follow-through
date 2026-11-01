# Deploying to the Pi

Assumes the Raspberry Pi 3 Model B is already flashed with 64-bit Raspberry Pi OS and reachable over SSH.

## 1. Confirm you're on the 64-bit OS

```bash
uname -m
```

Must print `aarch64`. If it prints `armv7l`, re-flash with the 64-bit Raspberry Pi OS image before continuing — `uv` only ships prebuilt binaries for `aarch64`.

## 2. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 3. Clone the repo and install dependencies

```bash
git clone <repo-url> /home/eddiedude/follow-through
cd /home/eddiedude/follow-through
uv sync
```

This creates `.venv/` with the exact dependency versions pinned in `uv.lock`.

## 4. Configure secrets

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from @BotFather
- `TELEGRAM_CHAT_ID` — message your bot once, then check its logs/getUpdates for your chat ID
- `ANTHROPIC_API_KEY`
- `FOLLOW_THROUGH_BACKUP_DEST_DIR` — a path inside your mounted/synced cloud storage folder (e.g. a Google Drive sync directory) where daily DB backups land

## 5. Install and start the three systemd units

```bash
sudo cp deploy/follow-through-bot.service /etc/systemd/system/
sudo cp deploy/follow-through-scheduler.service /etc/systemd/system/
sudo cp deploy/follow-through-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now follow-through-bot
sudo systemctl enable --now follow-through-scheduler
sudo systemctl enable --now follow-through-backup
```

Check status/logs with `systemctl status follow-through-bot` and `journalctl -u follow-through-bot -f` (swap in the other two unit names as needed).
