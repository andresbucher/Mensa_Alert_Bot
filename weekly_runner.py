import asyncio
import logging
import os
from datetime import datetime
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


def format_alert(menu_name: str, date_label: str, cantine_name: str) -> str:
    return (
        f"{menu_name.upper()} ALERT\n"
        f"Date: {date_label}\n"
        f"Cantine: {cantine_name}"
    )


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

    hits = find_special_menus_for_week(config)
    if not hits:
        LOGGER.info("No matching special menus found.")
        return

    bot = Bot(token=config.telegram_bot_token)
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
