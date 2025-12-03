import json
import logging
import os
from typing import List

from powerbot.config.config import settings


def load_subscribers() -> List[dict]:
    """
    Формат НОВЫЙ:
      [
        {"chat_id": -100123, "thread_id": null, "title": "..."},
        ...
      ]

    Если файл в старом формате [chat_id, ...] (list int),
    конвертируем в новый with thread_id = None.
    """
    path = settings.SUBSCRIBERS_FILE
    if not os.path.exists(path):
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list) or not data:
            return []

        # старый формат: список chat_id
        if isinstance(data[0], int):
            subs = [
                {"chat_id": int(cid), "thread_id": None, "title": None}
                for cid in data
            ]
            try:
                with open(path, "w", encoding="utf-8") as fw:
                    json.dump(subs, fw, ensure_ascii=False, indent=2)
            except Exception:
                logging.exception("Не вдалося оновити формат %s", path)
            return subs

        # новый формат: список dict
        subs: List[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            cid = item.get("chat_id")
            tid = item.get("thread_id", None)
            title = item.get("title", None)
            if cid is None:
                continue
            try:
                cid = int(cid)
            except Exception:
                continue
            if tid is not None:
                try:
                    tid = int(tid)
                except Exception:
                    tid = None
            subs.append({"chat_id": cid, "thread_id": tid, "title": title})
        return subs

    except Exception:
        logging.exception("Не вдалося прочитати %s", path)
        return []


def save_subscribers(subs: List[dict]) -> None:
    path = settings.SUBSCRIBERS_FILE
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(subs, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception("Не вдалося записати %s", path)
