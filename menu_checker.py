from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests

from config import BotConfig

POLYTERRASSE_URL_TEMPLATE = (
    "https://ethz.ch/de/campus/erleben/gastronomie-und-einkaufen/"
    "gastronomie/menueplaene/offerWeek.html?date={week_monday}&id=9"
)
KLAUSIUS_MENSA_URL_TEMPLATE = (
    "https://ethz.ch/de/campus/erleben/gastronomie-und-einkaufen/"
    "gastronomie/menueplaene/offerWeek.html?date={week_monday}&id=3"
)


@dataclass(frozen=True)
class SpecialMenuHit:
    menu_name: str
    date_label: str
    cantine_name: str


WEEKDAY_OFFSET = {
    "Mo": 0,
    "Di": 1,
    "Mi": 2,
    "Do": 3,
    "Fr": 4,
    "Sa": 5,
    "So": 6,
}

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
}


def _normalize_text(value: str) -> str:
    collapsed = " ".join(value.split())
    return collapsed.casefold()


def _extract_cantine_name(file_path: Path) -> str:
    stem = file_path.stem
    if "ETH Zürich_" in stem:
        return stem.split("ETH Zürich_", maxsplit=1)[1].replace("_", " ").strip()
    return stem


def _extract_week_start(soup: BeautifulSoup) -> datetime | None:
    app_root = soup.select_one("#gastro-app")
    if app_root is None:
        return None

    date_text = app_root.get("data-date")
    if not date_text:
        return None

    try:
        return datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        return None


def _iter_weekday_sections(soup: BeautifulSoup):
    return soup.select("section.cp-week__weekday")


def _clean_menu_title(raw_title: str) -> str:
    title = " ".join(raw_title.split())
    # Remove duplicate whitespace and trailing markers that may appear in saved HTML.
    return re.sub(r"\s+", " ", title).strip(" -|")


def _day_to_date_label(day_code: str, week_start: datetime | None) -> str:
    if week_start is None:
        return day_code

    offset = WEEKDAY_OFFSET.get(day_code)
    if offset is None:
        return day_code

    target = week_start + timedelta(days=offset)
    return f"{day_code} ({target.date().isoformat()})"


def _menu_matches_any_keyword(menu_title: str, keywords: list[str]) -> bool:
    normalized_title = _normalize_text(menu_title)
    for keyword in keywords:
        if _normalize_text(keyword) in normalized_title:
            return True
    return False


def _is_allowed_cantine(cantine_name: str, allowed_names: list[str]) -> bool:
    if not allowed_names:
        return True
    allowed = {_normalize_text(name) for name in allowed_names}
    return _normalize_text(cantine_name) in allowed


def _extract_hits_from_html(
    html_text: str,
    cantine_name: str,
    special_keywords: list[str],
) -> list[SpecialMenuHit]:
    soup = BeautifulSoup(html_text, "html.parser")
    week_start = _extract_week_start(soup)
    hits: list[SpecialMenuHit] = []

    for weekday_section in _iter_weekday_sections(soup):
        day_node = weekday_section.select_one("h2.cp-menu__dayofweek")
        day_code = day_node.get_text(strip=True) if day_node else "?"
        date_label = _day_to_date_label(day_code, week_start)

        for menu_title_node in weekday_section.select("h3.cp-menu__title"):
            raw_title = menu_title_node.get_text(" ", strip=True)
            menu_title = _clean_menu_title(raw_title)
            if not menu_title:
                continue

            if _menu_matches_any_keyword(menu_title, special_keywords):
                hits.append(
                    SpecialMenuHit(
                        menu_name=menu_title,
                        date_label=date_label,
                        cantine_name=cantine_name,
                    )
                )

    return hits


def _extract_hits_from_eth_api(
    html_text: str,
    cantine_name: str,
    special_keywords: list[str],
    timezone_name: str,
    week_offset_weeks: int,
) -> list[SpecialMenuHit]:
    soup = BeautifulSoup(html_text, "html.parser")
    app_root = soup.select_one("#gastro-app")
    if app_root is None:
        return []

    base_url = (app_root.get("data-baseurl") or "").strip()
    facility = (app_root.get("data-facility") or "").strip()
    locale = (app_root.get("data-locale") or "de").strip() or "de"
    if not base_url or not facility:
        return []

    week_monday_iso = _current_week_monday_iso(timezone_name, week_offset_weeks)
    valid_after = datetime.strptime(week_monday_iso, "%Y-%m-%d")
    valid_before = valid_after + timedelta(days=7)

    try:
        response = requests.get(
            f"{base_url.rstrip('/')}/weeklyrotas",
            params={
                "client-id": "ethz-wcms",
                "lang": locale,
                "rs-first": 0,
                "rs-size": 50,
                "valid-after": valid_after.strftime("%Y-%m-%d"),
                "valid-before": valid_before.strftime("%Y-%m-%d"),
                "facility": int(facility),
            },
            headers=HTTP_HEADERS,
            timeout=30,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
    except (ValueError, requests.RequestException):
        return []

    hits: list[SpecialMenuHit] = []
    week_entries = payload.get("weekly-rota-array", [])
    for week_entry in week_entries:
        day_entries = week_entry.get("day-of-week-array", [])
        for day_entry in day_entries:
            day_code = day_entry.get("day-of-week-code")
            day_short = day_entry.get("day-of-week-desc-short", "?")
            if isinstance(day_code, int) and 1 <= day_code <= 7:
                target_date = valid_after + timedelta(days=(day_code - 1))
                date_label = f"{day_short} ({target_date.date().isoformat()})"
            else:
                date_label = str(day_short)

            for opening_hour in day_entry.get("opening-hour-array", []):
                for meal_time in opening_hour.get("meal-time-array", []):
                    for line in meal_time.get("line-array", []):
                        meal = line.get("meal", {})
                        if not isinstance(meal, dict):
                            continue

                        raw_name = str(meal.get("name", "")).strip()
                        menu_title = _clean_menu_title(raw_name)
                        if not menu_title:
                            continue

                        if _menu_matches_any_keyword(menu_title, special_keywords):
                            hits.append(
                                SpecialMenuHit(
                                    menu_name=menu_title,
                                    date_label=date_label,
                                    cantine_name=cantine_name,
                                )
                            )

    return hits


def _current_week_monday_iso(timezone_name: str, week_offset_weeks: int = 0) -> str:
    now = datetime.now(ZoneInfo(timezone_name))
    monday = now.date() - timedelta(days=now.weekday()) + timedelta(weeks=week_offset_weeks)
    return monday.isoformat()


def _build_week_url(
    base_url: str,
    timezone_name: str,
    week_offset_weeks: int = 0,
) -> str:
    """Build a weekly URL using current week Monday date.

    Supported patterns:
    - Placeholder style: ...date={week_monday}...
    - Existing date query: ...?date=YYYY-MM-DD&id=...
    If neither is present, the URL is returned unchanged.
    """
    week_monday = _current_week_monday_iso(timezone_name, week_offset_weeks)

    if "{week_monday}" in base_url:
        return base_url.replace("{week_monday}", week_monday)

    parsed = urlparse(base_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "date" not in query:
        return base_url

    query["date"] = week_monday
    updated_query = urlencode(query)
    return urlunparse(parsed._replace(query=updated_query))


def find_special_menus_for_week(
    config: BotConfig,
    week_offset_weeks: int = 0,
) -> list[SpecialMenuHit]:
    if not config.special_keywords:
        return []

    source_list = config.cantine_sources or [
        ("Polyterasse", POLYTERRASSE_URL_TEMPLATE),
        ("Klausius Mensa", KLAUSIUS_MENSA_URL_TEMPLATE),
    ]

    hits: list[SpecialMenuHit] = []
    seen: set[tuple[str, str, str]] = set()

    for cantine_name, base_url in source_list:
        if not _is_allowed_cantine(cantine_name, config.cantine_names):
            continue

        url = _build_week_url(base_url, config.timezone, week_offset_weeks)

        try:
            response = requests.get(url, headers=HTTP_HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            continue

        html_hits = _extract_hits_from_html(
            html_text=response.text,
            cantine_name=cantine_name,
            special_keywords=config.special_keywords,
        )
        if not html_hits:
            html_hits = _extract_hits_from_eth_api(
                html_text=response.text,
                cantine_name=cantine_name,
                special_keywords=config.special_keywords,
                timezone_name=config.timezone,
                week_offset_weeks=week_offset_weeks,
            )

        for hit in html_hits:
            key = (hit.menu_name, hit.date_label, hit.cantine_name)
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)

    html_files = sorted(Path(__file__).resolve().parent.glob("*.html"))
    for html_file in html_files:
        cantine_name = _extract_cantine_name(html_file)
        if not _is_allowed_cantine(cantine_name, config.cantine_names):
            continue

        html_text = html_file.read_text(encoding="utf-8", errors="ignore")
        for hit in _extract_hits_from_html(
            html_text=html_text,
            cantine_name=cantine_name,
            special_keywords=config.special_keywords,
        ):
            key = (hit.menu_name, hit.date_label, hit.cantine_name)
            if key in seen:
                continue
            seen.add(key)
            hits.append(hit)

    return hits
