import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import load_config
from menu_checker import SpecialMenuHit, find_online_menus_for_week, find_special_menus_for_week
from state_store import BotStateStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# Avoid logging full Telegram request URLs (which include the bot token).
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.INFO)
LOGGER = logging.getLogger(__name__)


def _parse_runcheck_week_offset(args: list[str]) -> int:
    if not args:
        return 0

    value = args[0].strip().lower()
    aliases = {
        "this": 0,
        "current": 0,
        "last": -1,
        "previous": -1,
        "next": 1,
    }
    if value in aliases:
        return aliases[value]

    try:
        offset = int(value)
    except ValueError as exc:
        raise ValueError(
            "Usage: /runcheck [week_offset]. Examples: /runcheck, /runcheck -1, /runcheck last"
        ) from exc

    if offset < -12 or offset > 12:
        raise ValueError("week_offset must be between -12 and 12")

    return offset


def format_alert(menu_name: str, date_label: str, cantine_name: str) -> str:
    return (
        f"{menu_name.upper()} ALERT\n"
        f"Date: {date_label}\n"
        f"Cantine: {cantine_name}"
    )


def _chunk_text_lines(lines: list[str], max_chars: int = 3500) -> list[str]:
    chunks: list[str] = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
        current = line

    if current:
        chunks.append(current)

    return chunks


def _filter_entries_for_today(
    entries: list[SpecialMenuHit],
    timezone_name: str,
) -> list[SpecialMenuHit]:
    today_iso = datetime.now(ZoneInfo(timezone_name)).date().isoformat()
    return [entry for entry in entries if f"({today_iso})" in entry.date_label]


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
    config = load_config()
    context.application.bot_data["config"] = config
    try:
        week_offset = _parse_runcheck_week_offset(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    hits = find_special_menus_for_week(config, week_offset_weeks=week_offset)

    if not hits:
        await update.message.reply_text(
            "No configured special menus found in online sources or local HTML files for the selected week."
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


async def debugmenus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    context.application.bot_data["config"] = config

    try:
        week_offset = _parse_runcheck_week_offset(context.args)
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    entries = find_online_menus_for_week(config, week_offset_weeks=week_offset)
    if not entries:
        await update.message.reply_text(
            "No online menu entries found for the selected week."
        )
        return

    lines = [
        f"{entry.date_label} | {entry.cantine_name} | {entry.menu_name}"
        for entry in entries
    ]
    header = (
        f"Found {len(entries)} online menu entries for week_offset={week_offset}."
    )
    for chunk in _chunk_text_lines(lines):
        await update.message.reply_text(f"{header}\n{chunk}")
        header = ""


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    context.application.bot_data["config"] = config

    entries = find_online_menus_for_week(config, week_offset_weeks=0)
    todays_entries = _filter_entries_for_today(entries, config.timezone)

    if not todays_entries:
        await update.message.reply_text(
            "No online menu entries found for today."
        )
        return

    lines = [
        f"{entry.cantine_name} | {entry.menu_name}"
        for entry in todays_entries
    ]
    header = f"Today's menus ({len(todays_entries)}):"
    for chunk in _chunk_text_lines(lines):
        await update.message.reply_text(f"{header}\n{chunk}")
        header = ""


async def weekly_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    config = load_config()
    context.application.bot_data["config"] = config
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

    LOGGER.info("Weekly check finished: sent %s alert(s).", len(hits))


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
    app.add_handler(CommandHandler("debugmenus", debugmenus))
    app.add_handler(CommandHandler("menu", menu))

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