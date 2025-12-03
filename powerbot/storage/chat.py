# powerbot/storage/chat.py
import logging
import sqlite3
import time
from typing import Optional

from powerbot.config.config import settings


def init_chat_settings() -> None:
    """
    Таблица chat_settings:
      - chat_id
      - thread_id (NULL для обычных чатов / лички)
      - lang ('uk', 'en' и т.д.)
    """
    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                thread_id INTEGER,
                lang TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                UNIQUE(chat_id, thread_id)
            )
            """
        )
        conn.commit()
    except Exception:
        logging.exception("Не вдалося створити таблицю chat_settings")
    finally:
        conn.close()


def _select_lang(cur: sqlite3.Cursor, chat_id: int, thread_id: Optional[int]) -> Optional[str]:
    if thread_id is None:
        cur.execute(
            "SELECT lang FROM chat_settings WHERE chat_id=? AND thread_id IS NULL",
            (chat_id,),
        )
    else:
        cur.execute(
            "SELECT lang FROM chat_settings WHERE chat_id=? AND thread_id=?",
            (chat_id, thread_id),
        )
    row = cur.fetchone()
    return row[0] if row else None


def get_chat_lang(chat_id: int, thread_id: Optional[int]) -> Optional[str]:
    """
    Возвращает сохранённый язык для чата/треда, либо None.
    """
    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        return _select_lang(cur, chat_id, thread_id)
    except Exception:
        logging.exception("Не вдалося прочитати chat_lang")
        return None
    finally:
        conn.close()


def set_chat_lang(chat_id: int, thread_id: Optional[int], lang: str) -> None:
    """
    Сохраняет язык для чата/треда (INSERT или UPDATE).
    """
    now_ts = int(time.time())
    conn = sqlite3.connect(settings.DB_FILE)
    try:
        cur = conn.cursor()
        existing = _select_lang(cur, chat_id, thread_id)
        if existing is None:
            # INSERT
            if thread_id is None:
                cur.execute(
                    """
                    INSERT INTO chat_settings (chat_id, thread_id, lang, created_at, updated_at)
                    VALUES (?, NULL, ?, ?, ?)
                    """,
                    (chat_id, lang, now_ts, now_ts),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO chat_settings (chat_id, thread_id, lang, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chat_id, thread_id, lang, now_ts, now_ts),
                )
        else:
            # UPDATE
            if thread_id is None:
                cur.execute(
                    """
                    UPDATE chat_settings
                    SET lang = ?, updated_at = ?
                    WHERE chat_id = ? AND thread_id IS NULL
                    """,
                    (lang, now_ts, chat_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE chat_settings
                    SET lang = ?, updated_at = ?
                    WHERE chat_id = ? AND thread_id = ?
                    """,
                    (lang, now_ts, chat_id, thread_id),
                )
        conn.commit()
    except Exception:
        logging.exception("Не вдалося оновити chat_lang")
    finally:
        conn.close()
