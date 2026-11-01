# Deploying to a Raspberry Pi

End-to-end setup, from a blank SD card to a running bot. Written against a Raspberry Pi 3 Model B; substitute your own username/hostname throughout (this doc uses `eddiedude`/`rambo` as the worked example).

## 1. Flash the SD card

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your computer.
2. Insert the microSD card (use a USB adapter if your computer has no card slot).
3. In Imager: choose **Raspberry Pi OS (64-bit)** — a Pi 3 is 64-bit capable, and `uv` only ships prebuilt binaries for `aarch64`. The 32-bit image will not work.
4. Click the gear/⚙️ icon for **advanced options** (or you'll be prompted after choosing OS/storage, depending on Imager version) and set:
   - **Hostname** — whatever you want to reach the Pi by (e.g. `rambo`), used as `<hostname>.local`
   - **Enable SSH** → **Allow public-key authentication only** (recommended) — paste the contents of `~/.ssh/id_ed25519.pub` from the computer you'll SSH from. If you don't have a key pair yet, generate one with `ssh-keygen -t ed25519` first.
   - **Set username and password** — pick a username (e.g. `eddiedude`); this is the account the systemd services will run as.
   - **Configure wireless LAN** — SSID/password for your Wi-Fi. Leave "Hidden SSID" unchecked unless your network actually hides its SSID.
5. Write the image, then move the SD card to the Pi.

## 2. First boot and SSH in

1. Insert the SD card **before** applying power — the Pi only reads it at power-on.
2. Connect power (and Ethernet, if using it) and wait 1–2 minutes for first boot.
3. From your computer:
   ```bash
   ssh <username>@<hostname>.local
   ```
   If `.local` doesn't resolve (mDNS can be unreliable on some networks/routers), find the Pi's IP instead:
   ```bash
   arp -a | grep -i b8:27:eb   # b8:27:eb is a Raspberry Pi Foundation MAC prefix
   ```
   then `ssh <username>@<that-ip>`.

**No green activity LED / nothing on the network:** power off, reseat the SD card fully, power back on.

## 3. Confirm you're on the 64-bit OS

```bash
uname -m
```

Must print `aarch64`. If it prints `armv7l`, you flashed the 32-bit image — re-flash with the 64-bit OS before continuing.

## 4. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
uv --version
```

## 5. Clone the repo and install dependencies

```bash
git clone https://github.com/Eddiedude1/follow-through.git
cd follow-through
uv sync
uv run pytest   # confirm the whole suite passes on the actual hardware
```

## 6. Configure secrets

```bash
cp .env.example .env
nano .env
```

Fill in:

**`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`** — full steps:

1. Install Telegram (if you don't have it) and sign up/log in with your phone number.
2. Open a chat with **`@BotFather`**, Telegram's own official bot for creating other bots. If searching `BotFather` in-app doesn't find it, open **https://t.me/botfather** directly — it opens the chat in the app.
3. Send `/newbot`.
4. When asked for a **name**, type anything you like (e.g. `Follow Through`) — this is just the display name.
5. When asked for a **username**, it must be unique and end in `bot` (e.g. `Follow_Through_Eddie_Bot`). BotFather tells you if it's taken.
6. BotFather replies with an **API token** — a string like `123456789:AAEz...`. This is `TELEGRAM_BOT_TOKEN`.
   **Treat it as a secret** — never paste it into a chat, commit, or log. If it's ever exposed, revoke and reissue it immediately: in BotFather, send `/mybots`, select your bot, **API Token** → **Revoke current token**, then use the new one.
7. In Telegram, search for the bot you just created by its exact username and open a chat with it.
8. Send it any message (e.g. "hi") — this gives Telegram something to hand back in the next step.
9. Run (substituting your real token — this command itself is safe to run, since the response only contains your chat info, not the token):
   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"
   ```
10. In the JSON response, find `"chat":{"id":...}` — that number is `TELEGRAM_CHAT_ID`. This value (unlike the token) is fine to share/note openly; it only identifies your chat, not your bot's credentials.

- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com/settings/keys). Create a dedicated key for this app rather than reusing one from somewhere else, so you can track/revoke its usage independently.
- `FOLLOW_THROUGH_BACKUP_DEST_DIR` — a local directory where daily DB backups land, e.g.:
  ```bash
  mkdir -p /home/<username>/follow-through-backups
  ```
- `FOLLOW_THROUGH_TIMEZONE` — an IANA timezone name (e.g. `America/Chicago`); defaults to `UTC` if unset, which will make reminder times wrong for most users.

Confirm all six keys are present without printing the secret values:
```bash
cut -d= -f1 .env
```

## 7. Set up cloud backup sync (rclone)

`backup.service` (below) only copies the DB to a **local** directory — getting it off-device (so an SD card failure doesn't lose everything) is a separate step using [`rclone`](https://rclone.org/), since most desktop cloud-sync clients (Dropbox included) don't support Raspberry Pi's ARM architecture.

```bash
sudo apt update
sudo apt install -y rclone
rclone config
```

In the wizard:
- `n` — new remote
- name: `gdrive` (or your provider's name)
- storage type: `drive` for Google Drive (type the short code directly rather than hunting for its number)
- `client_id` / `client_secret`: leave blank (Enter) — uses rclone's built-in key
- `scope`: `3` — `drive.file` (rclone can only see/manage files it creates itself, not your whole Drive — least-privilege)
- `service_account_file`: leave blank
- `Edit advanced config?`: `n`
- `Use auto config?`: **`n`** — the Pi is headless, so this prints an `rclone authorize "drive" "..."` command instead of trying to open a local browser
- Run that exact `rclone authorize ...` command on a computer that **does** have a browser (install rclone there too if needed: `brew install rclone` on a Mac). It opens a Google login/consent page, then prints a JSON token.
- Paste that JSON token at the Pi's `config_token>` prompt
- `Configure this as a Shared Drive (Team Drive)?`: `n` (unless you actually want a Team Drive — this needs broader scope and will 403 under `drive.file`)
- `y` to keep the remote, `q` to quit the wizard

Verify it works:
```bash
rclone mkdir gdrive:follow-through-backups
rclone lsd gdrive:
```

Then add a nightly sync job. **Avoid pasting a long single line into `crontab -e`** if your terminal/SSH client doesn't handle wrapped lines cleanly (some break one logical line into several, which cron then rejects) — type it directly instead, or build it carefully in `nano` (`select-editor` → choose nano if `vim` isn't your thing):

```bash
crontab -e
```
Add one line:
```
0 3 * * * /usr/bin/rclone sync /home/<username>/follow-through-backups gdrive:follow-through-backups --config /home/<username>/.config/rclone/rclone.conf >> /home/<username>/rclone-sync.log 2>&1
```

## 8. Install and start the three systemd units

The unit files assume the repo lives at `/home/<username>/follow-through` and runs as `<username>` — edit `deploy/*.service` first if yours differs.

```bash
sudo cp deploy/follow-through-bot.service /etc/systemd/system/
sudo cp deploy/follow-through-scheduler.service /etc/systemd/system/
sudo cp deploy/follow-through-backup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now follow-through-bot
sudo systemctl enable --now follow-through-scheduler
sudo systemctl enable --now follow-through-backup
```

Check status/logs:
```bash
systemctl status follow-through-bot follow-through-scheduler follow-through-backup --no-pager
journalctl -u follow-through-bot -f
```

## Troubleshooting

**`telegram.error.TimedOut` on startup or when sending a message, with no other error:**
- Confirm the Pi is actually using the network interface you think it is:
  ```bash
  ip -s link show eth0
  ip -s link show wlan0
  ```
  A plugged-in Ethernet cable that shows `NO-CARRIER` / `state DOWN` with zero bytes means it isn't actually linked (bad cable, bad port, or the port on your router/switch is off) — the Pi is likely still running over Wi-Fi despite the cable. Check with `sudo ethtool eth0 | grep -i "link detected"`.
- If you're on Wi-Fi, disable IPv6 — a broken/unreachable IPv6 route can stall `httpx`'s connection attempts long enough to blow past Telegram's timeouts, even though IPv4 works fine:
  ```bash
  sudo nano /etc/sysctl.d/99-disable-ipv6.conf
  ```
  Contents:
  ```
  net.ipv6.conf.all.disable_ipv6 = 1
  net.ipv6.conf.default.disable_ipv6 = 1
  ```
  Then: `sudo sysctl --system` (or reboot), and restart the bot service.
- The bot's own timeouts are already raised above `python-telegram-bot`'s 5s default (see `build_app()` in `follow_through/bot.py`) specifically for flaky home networks — if timeouts persist after the above, check general Wi-Fi signal quality to the Pi's location.

**Bot replies "Something went wrong handling that. Try again?":**
`handle_error` logs the real exception via Python's `logging` module — check `journalctl -u follow-through-bot -n 30 --no-pager -o cat` right after reproducing it (`-o cat` strips the timestamp/hostname prefix so long traceback lines are less likely to be cut off in a narrow terminal).

**Pasting a long one-line command (e.g. a `crontab -e` entry, or `python3 -c "..."` with semicolons) breaks it into several lines once pasted:**
If the command was copied from somewhere that visually wraps long lines for display (a chat UI, a narrow terminal), the paste can carry those wraps as real line breaks, splitting one logical line into several — cron then rejects the entry, and Python raises `IndentationError` on the broken-up `-c` string. Workaround: skip the one-liner entirely and write a small script file instead, with each statement on its own short line:
```bash
nano inspect.py
```
```python
import sqlite3
c = sqlite3.connect("follow_through.db")
c.row_factory = sqlite3.Row
for r in c.execute("SELECT * FROM notes"):
    print(dict(r))
```
```bash
.venv/bin/python3 inspect.py
```
Each line short enough that it can't wrap even in a narrow terminal, so the paste lands exactly as written.
