import logging
import threading
import time
from collections import deque
from typing import Optional

import requests

from powerbot.config.config import settings

MAX_GLOBAL_MSG_PER_SEC = settings.MAX_GLOBAL_MSG_PER_SEC
MIN_PER_CHAT_INTERVAL = settings.MIN_PER_CHAT_INTERVAL
SEND_WINDOW_SEC = settings.SEND_WINDOW_SEC

recent_sends = deque()                 # timestamps последних отправок
last_chat_send: dict[int, float] = {}  # chat_id -> last_ts
send_lock = threading.Lock()


def send_telegram_message_limited(
    chat_id: int,
    text: str,
    thread_id: Optional[int] = None,
    with_read_button: bool = False,
) -> None:
    """
    Синхронная отправка сообщения в Telegram с простым rate-limit:
    - глобально не больше MAX_GLOBAL_MSG_PER_SEC сообщений/сек;
    - не чаще MIN_PER_CHAT_INTERVAL сообщений/сек в один chat_id.
    Если thread_id указан — шлём в ветку (topic) супергруппы.

    Если with_read_button=True и чат приватный (chat_id > 0),
    добавляется инлайн-кнопка "✅ Прочитано" с callback_data="ack".
    """
    global recent_sends, last_chat_send

    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    with send_lock:
        while True:
            now = time.time()

            # чистим старые отправки
            while recent_sends and now - recent_sends[0] > SEND_WINDOW_SEC:
                recent_sends.popleft()

            # лимит по конкретному чату
            last_ts = last_chat_send.get(chat_id)
            if last_ts is not None and now - last_ts < MIN_PER_CHAT_INTERVAL:
                sleep_time = MIN_PER_CHAT_INTERVAL - (now - last_ts)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    continue

            # глобальный лимит
            if len(recent_sends) >= MAX_GLOBAL_MSG_PER_SEC:
                oldest = recent_sends[0]
                sleep_time = SEND_WINDOW_SEC - (now - oldest)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    continue

            break

        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        # Кнопка "Прочитано" только в приватных чатах
        if with_read_button and chat_id > 0:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [
                        {
                            "text": "✅ Прочитано",
                            "callback_data": "ack",
                        }
                    ]
                ]
            }

        try:
            resp = requests.post(api_url, json=payload, timeout=10)
            if not resp.ok:
                logging.warning(
                    "Помилка Telegram API для чату %s: %s %s",
                    chat_id,
                    resp.status_code,
                    resp.text,
                )
        except Exception as e:
            logging.warning("Не вдалося надіслати повідомлення у чат %s: %s", chat_id, e)

        now2 = time.time()
        recent_sends.append(now2)
        last_chat_send[chat_id] = now2

