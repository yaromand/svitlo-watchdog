import json
import logging
import os

from powerbot.config.config import settings


def load_state() -> dict:
    path = settings.STATE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        logging.exception("Не вдалося прочитати %s", path)
        return {}


def save_state(state: dict) -> None:
    path = settings.STATE_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Не вдалося записати %s", path)
