import json
import os
from typing import Optional


class BotStateStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}

        with open(self.path, "r", encoding="utf-8") as handle:
            try:
                data = json.load(handle)
                if isinstance(data, dict):
                    return data
                return {}
            except json.JSONDecodeError:
                return {}

    def _save(self, data: dict) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)

    def save_alert_chat_id(self, chat_id: int) -> None:
        data = self._load()
        data["alert_chat_id"] = chat_id
        self._save(data)

    def get_alert_chat_id(self, fallback: Optional[int]) -> Optional[int]:
        data = self._load()
        value = data.get("alert_chat_id")
        if isinstance(value, int):
            return value
        return fallback
