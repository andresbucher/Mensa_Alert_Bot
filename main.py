import logging
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import load_config
from menu_checker import find_special_menus_for_week
from state_store import BotStateStore


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Mensa bot is running. Use /setchat in your target chat to receive alerts."
    )


async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state_store: BotStateStore = context.application.bot_data["state_store"]
    chat_id = update.effective_chat.id
    state_store.save_alert_chat_id(chat_id)
    await update.message.reply_text(
        f"This chat is now configured for weekly alerts. chat_id={chat_id}"
    )


async def testalert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        format_alert(
            menu_name="CRISPY BEEF",
            date_label=str(datetime.now().date()),
            cantine_name="Example Cantine",
        )
    )


async def runcheck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    hits = find_special_menus_for_week(config)

    if not hits:
        await update.message.reply_text(
            "No configured special menus found in online sources or local HTML files."
        )
        return

    for hit in hits:
        await update.message.reply_text(
            format_alert(
                menu_name=hit.menu_name,
                date_label=hit.date_label,
                cantine_name=hit.cantine_name,
            )
        )


async def weekly_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    config = context.application.bot_data["config"]
    state_store: BotStateStore = context.application.bot_data["state_store"]
    alert_chat_id = state_store.get_alert_chat_id(config.default_chat_id)

    if alert_chat_id is None:
        LOGGER.warning("No alert chat configured. Set ALERT_CHAT_ID or use /setchat.")
        return

    hits = find_special_menus_for_week(config)
    if not hits:
        LOGGER.info("Weekly check finished: no configured specials found.")
        return

    for hit in hits:
        await context.bot.send_message(
            chat_id=alert_chat_id,
            text=format_alert(
                menu_name=hit.menu_name,
                date_label=hit.date_label,
                cantine_name=hit.cantine_name,
            ),
        )

    LOGGER.info("Weekly check is finished: sent %s alert(s).", len(hits))


def main() -> None:
    config = load_config()
    state_store = BotStateStore(config.state_file)

    app = Application.builder().token(config.telegram_bot_token).build()
    app.bot_data["config"] = config
    app.bot_data["state_store"] = state_store

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setchat", setchat))
    app.add_handler(CommandHandler("testalert", testalert))
    app.add_handler(CommandHandler("runcheck", runcheck))

    app.job_queue.run_daily(
        weekly_check,
        time=config.check_time,
        days=(config.check_weekday,),
        name="weekly-cantine-check",
    )

    LOGGER.info(
        "Bot started. Weekly check scheduled: weekday=%s time=%s",
        config.check_weekday,
        config.check_time,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()