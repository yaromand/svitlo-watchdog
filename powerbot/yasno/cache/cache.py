import json
import logging
import os
from datetime import date
from typing import Dict, Any, List

from powerbot.config.config import settings


def load_yasno_state() -> dict:
    """
    Читаем локальный кэш графика YASNO.

    Формат v2:
    {
      "days": {
        "2025-11-29": {
          "slots": [
            {"start_ts": ..., "end_ts": ..., "status": "ScheduleApplies", "title": "..."},
            ...
          ],
          "updated_at": 1234567890
        },
        ...
      },
      "last_check_ts": 1234567890
    }
    """
    path = settings.YASNO_STATE_FILE
    if not os.path.exists(path):
        return {"days": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {"days": {}}
        if "days" not in data:
            return {"days": {}}
        return data
    except Exception:
        logging.exception("Не вдалося прочитати %s", path)
        return {"days": {}}


def save_yasno_state(state: dict) -> None:
    path = settings.YASNO_STATE_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Не вдалося записати %s", path)


def _serialize_yasno_slots(slots) -> List[dict]:
    """
    Перетворюємо список Slot у простий список dict,
    щоб його можна було покласти в JSON.
    """
    result: List[dict] = []
    for s in slots:
        try:
            result.append(
                {
                    "start_ts": int(s.dt_start.timestamp()),
                    "end_ts": int(s.dt_end.timestamp()),
                    "status": s.day_status.value if getattr(s, "day_status", None) else None,
                    "title": s.title,
                }
            )
        except Exception:
            result.append(
                {
                    "start_ts": None,
                    "end_ts": None,
                    "status": None,
                    "title": str(s),
                }
            )
    return result


def update_day_schedule(
    days: Dict[str, Any],
    day_date: date,
    slots,
    now_ts: int,
) -> bool:
    """
    Оновлює кэш для конкретної календарної дати.

    Повертає True, якщо для цієї дати графік ЗМІНИВСЯ:
    - це перша поява даних для цього дня, або
    - список слотів відрізняється від того, що був збережений раніше.
    """
    key = day_date.isoformat()
    new_slots_serialized = _serialize_yasno_slots(slots)

    existed_before = key in days
    old_slots = days.get(key, {}).get("slots") if existed_before else None

    changed = (not existed_before) or (old_slots != new_slots_serialized)

    days[key] = {
        "slots": new_slots_serialized,
        "updated_at": now_ts,
    }
    return changed
