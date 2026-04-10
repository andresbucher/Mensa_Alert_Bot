import os
from dataclasses import dataclass
from datetime import time
from typing import Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class BotConfig:
    telegram_bot_token: str
    default_chat_id: Optional[int]
    check_weekday: int
    check_time: time
    timezone: str
    special_keywords: list[str]
    cantine_names: list[str]
    cantine_sources: list[tuple[str, str]]
    state_file: str


def _parse_int(value: str | None) -> Optional[int]:
    if not value:
        return None
    return int(value)


def _parse_time(value: str) -> time:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("CHECK_TIME must be in HH:MM format")

    hour = int(parts[0])
    minute = int(parts[1])
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("CHECK_TIME contains invalid hour or minute")

    return time(hour=hour, minute=minute)


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_cantine_sources(value: str | None) -> list[tuple[str, str]]:
    if not value:
        return []

    pairs: list[tuple[str, str]] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue

        if "|" not in item:
            raise ValueError(
                "CANTINE_SOURCES must use 'Cantine Name|https://url' pairs, comma-separated"
            )

        name, url = item.split("|", maxsplit=1)
        name = name.strip()
        url = url.strip()
        if not name or not url:
            raise ValueError(
                "CANTINE_SOURCES contains an empty cantine name or URL"
            )

        pairs.append((name, url))

    return pairs


def load_config() -> BotConfig:
    # Always refresh from .env so runtime config edits are picked up reliably.
    load_dotenv(override=True)

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN in environment")

    default_chat_id = _parse_int(os.getenv("ALERT_CHAT_ID"))
    check_weekday = int(os.getenv("CHECK_WEEKDAY", "0"))
    if check_weekday < 0 or check_weekday > 6:
        raise ValueError("CHECK_WEEKDAY must be in range 0..6 (Mon..Sun)")

    check_time = _parse_time(os.getenv("CHECK_TIME", "08:00"))
    timezone = os.getenv("TIMEZONE", "Europe/Zurich").strip() or "Europe/Zurich"

    keywords = _parse_csv(
        os.getenv(
            "SPECIAL_KEYWORDS",
            "crispy beef,truffle pasta,sushi bowl",
        )
    )

    cantine_names = _parse_csv(os.getenv("CANTINE_NAMES", ""))
    cantine_sources = _parse_cantine_sources(os.getenv("CANTINE_SOURCES", ""))
    state_file = os.getenv("STATE_FILE", "bot_state.json")

    return BotConfig(
        telegram_bot_token=token,
        default_chat_id=default_chat_id,
        check_weekday=check_weekday,
        check_time=check_time,
        timezone=timezone,
        special_keywords=keywords,
        cantine_names=cantine_names,
        cantine_sources=cantine_sources,
        state_file=state_file,
    )
