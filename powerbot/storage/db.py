import logging
import sqlite3
import time
from typing import List, Tuple, Optional

from powerbot.config.config import settings
from powerbot.storage.chat import init_chat_settings

def init_db() -> None:
    """
    Инициализация базы:
    - гарантируем, что директория для файла БД существует;
    - создаём таблицу power_events при необходимости.
    """
    try:
        settings.DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        logging.exception("Не вдалося створити директорію для БД: %s", settings.DB_FILE.parent)
        raise

    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS power_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                status INTEGER NOT NULL  -- 1 = онлайн, 0 = офлайн
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    init_chat_settings()


def log_power_event(status: bool, ts: Optional[int] = None) -> None:
    if ts is None:
        ts = int(time.time())
    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO power_events (ts, status) VALUES (?, ?)",
            (int(ts), 1 if status else 0),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_events() -> List[Tuple[int, bool]]:
    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute("SELECT ts, status FROM power_events ORDER BY ts ASC")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [(int(ts), bool(st)) for ts, st in rows]
