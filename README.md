# Mensa Telegram Bot Starter

This starter runs a Telegram bot continuously and executes a weekly menu check job.
It can also run online with GitHub Actions every Monday morning.

## 1) First Step to Setup a Groupchat

Get a Token from @BotFather via Telegram and also get the ChatID so you can add it as an action variable in the Githuv Settings

## 2) Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Fill values in `.env`, especially `TELEGRAM_BOT_TOKEN`.

Run the bot:

```powershell
python main.py
```

## 3) Configure alert chat

In Telegram, open the chat/group where alerts should go and run:

- `/setchat` to store that chat id in `bot_state.json`
- `/testalert` to verify messaging
- `/runcheck` to parse local `.html` files immediately and send matching alerts
- `/runcheck -1` to check last week (useful if you missed the week)

### Keyword config and GitHub

- `.env` is intentionally ignored by git (see `.gitignore`), so changes there do not appear in GitHub Desktop.
- Keep real values in your local `.env` (tokens, chat id, your private keyword list).
- Keep only templates/defaults in `.env.example` if you want tracked config examples in git.
- For GitHub Actions, set `SPECIAL_KEYWORDS` in repository Secrets (not in `.env`).

## 4) Weekly schedule

Scheduler settings in `.env`:

- `CHECK_WEEKDAY`: 0..6 for Monday..Sunday
- `CHECK_TIME`: `HH:MM` (server local time)

The bot executes `find_special_menus_for_week` from `menu_checker.py` on schedule.
It can parse both:

- Local `.html` files in the project folder
- Online pages configured via `CANTINE_SOURCES` in `.env`

For `CANTINE_SOURCES`, use stable base links and let the bot inject the week date:

- Preferred: `...date={week_monday}&id=...`
- Also supported: `...date=2026-04-06&id=...` (the date part is replaced automatically)

## 5) Add your scraper later

Implement scraping logic in `menu_checker.py`:

- Fetch cantine HTML
- Parse dates/menu names
- Match against `SPECIAL_KEYWORDS`
- Return matching entries so alerts are sent automatically

## 6) Keep bot online 24/7 (recommended)

### Option A: VPS + systemd (most reliable)

1. Copy project to Linux server (for example `/opt/mensa-bot`)
2. Create venv and install requirements
3. Add real `.env`
4. Copy `deployment/mensa-bot.service` to `/etc/systemd/system/mensa-bot.service`
5. Adjust paths/user in service file
6. Start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable mensa-bot
sudo systemctl start mensa-bot
sudo systemctl status mensa-bot
```

### Option B: Cloud platforms (Railway/Render/Fly.io)

Deploy from GitHub and set `.env` values in platform secrets. Ensure your plan does not sleep the service.

### Option C: GitHub Actions scheduled run (no always-on server needed)

Use this when you only need weekly checks and alerts.

1. Push this project to a GitHub repository.
2. The workflow file is already included: `.github/workflows/weekly-alert.yml`.
3. In your GitHub repo, set these Secrets (Settings -> Secrets and variables -> Actions):

- `TELEGRAM_BOT_TOKEN`
- `ALERT_CHAT_ID`
- `SPECIAL_KEYWORDS` (example: `Crispy Beef`)
- `CANTINE_NAMES` (example: `Polyterasse`)
- `CANTINE_SOURCES` (example: `Polyterasse|https://...date={week_monday}&id=9`) 

4. The workflow runs every hour on Monday in UTC, and `weekly_runner.py` checks local Zurich time before sending.
5. Configure these values in workflow env if needed:

- `CHECK_WEEKDAY` (0=Monday)
- `CHECK_TIME` (for example `08:00`)
- `TIMEZONE` (for example `Europe/Zurich`)
- `RUN_WINDOW_MINUTES` (for example `60`)

This pattern avoids UTC daylight-saving issues while still using GitHub cron.

## 7) Notes

- Current bot uses long polling for simplicity.
- If you scale later, you can migrate to webhooks.
