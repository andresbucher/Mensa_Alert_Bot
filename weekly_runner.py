import asyncio
import logging
import os
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from telegram import Bot

from config import load_config
from menu_checker import find_special_menus_for_week


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Avoid logging full Telegram request URLs (which include the bot token).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
LOGGER = logging.getLogger(__name__)


DATE_LABEL_PATTERN = re.compile(r"^(?P<weekday>[^\s]+)\s*\((?P<iso>\d{4}-\d{2}-\d{2})\)$")


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def format_alert(menu_name: str, date_label: str, cantine_name: str) -> str:
    display_date = _format_date_label_german(date_label)
    return (
        f"🚨🚨{menu_name.upper()} ALERT🚨🚨\n"
        f"Datum: {display_date}\n"
        f"Mensa: {cantine_name}"
    )


def _format_date_label_german(date_label: str) -> str:
    match = DATE_LABEL_PATTERN.match(date_label.strip())
    if not match:
        return date_label

    weekday = match.group("weekday")
    iso_date = match.group("iso")
    dt = datetime.strptime(iso_date, "%Y-%m-%d")
    return f"{weekday}, {dt.strftime('%d.%m.%Y')}"


def _should_run_now() -> bool:
    force_run = os.getenv("FORCE_RUN", "0").strip() == "1"
    if force_run:
        return True

    config = load_config()
    tz = ZoneInfo(config.timezone)
    now_local = datetime.now(tz)

    if now_local.weekday() != config.check_weekday:
        return False

    target_minutes = config.check_time.hour * 60 + config.check_time.minute
    now_minutes = now_local.hour * 60 + now_local.minute
    run_window = int(os.getenv("RUN_WINDOW_MINUTES", "20"))

    return target_minutes <= now_minutes < (target_minutes + run_window)


async def _send_weekly_alerts() -> None:
    config = load_config()

    if config.default_chat_id is None:
        raise RuntimeError("ALERT_CHAT_ID is required for weekly_runner.py")

    bot = Bot(token=config.telegram_bot_token)
    hits = find_special_menus_for_week(config)
    if not hits:
        LOGGER.info("No matching special menus found.")
        if _env_flag("NOTIFY_ON_NO_HITS", "1"):
            now_local = datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d %H:%M")
            await bot.send_message(
                chat_id=config.default_chat_id,
                text=(
                    "Mensa check executed.\n"
                    f"Time: {now_local} ({config.timezone})\n"
                    "Result: no keyword matches this run."
                ),
            )
        return

    for hit in hits:
        await bot.send_message(
            chat_id=config.default_chat_id,
            text=format_alert(
                menu_name=hit.menu_name,
                date_label=hit.date_label,
                cantine_name=hit.cantine_name,
            ),
        )

    LOGGER.info("Sent %s alert(s).", len(hits))


def main() -> None:
    if not _should_run_now():
        LOGGER.info("Skipping run because local time is outside configured run window.")
        return

    asyncio.run(_send_weekly_alerts())


if __name__ == "__main__":
    main()
