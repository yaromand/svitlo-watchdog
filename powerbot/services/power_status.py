# powerbot/services/power_status.py
import logging
import time
from typing import Optional

from powerbot.config.config import settings
from powerbot.storage.state import load_state, save_state
from powerbot.storage.db import log_power_event
from powerbot.storage.subscribers import load_subscribers
from powerbot.domain.stats import format_duration_ua
from powerbot.telegram.client import send_telegram_message_limited
from powerbot.yasno.client import yasno_predict_on_time, DayStatus


def apply_status_change(is_online: bool, now_ts: Optional[int] = None) -> Optional[str]:
    """
    Вызывается из вебхука (Flask-поток).
    Логируем событие в БД, обновляем state.json и шлём
    уведомления подписчикам (личка / группы / ветки) с rate-limit
    и поддержкой языка чата.
    """
    if now_ts is None:
        now_ts = int(time.time())

    state = load_state()
    last_status = state.get("last_status")
    last_change_ts = state.get("last_change_ts")

    # первый запуск — просто зафиксировали состояние, без уведомления
    if last_status is None:
        state["last_status"] = is_online
        state["last_change_ts"] = now_ts
        save_state(state)
        log_power_event(is_online, now_ts)
        logging.info("Ініціалізація стану: %s", is_online)
        return None

    # если состояние не изменилось — ничего не делаем
    if is_online == last_status:
        logging.info("Стан не змінився (%s), ігноруємо", is_online)
        return None

    # считаем длительность отключения (если было off -> стало on)
    outage_seconds = None
    if last_status is False and is_online is True and last_change_ts is not None:
        outage_seconds = max(0, now_ts - int(last_change_ts))

    state["last_status"] = is_online
    state["last_change_ts"] = now_ts
    save_state(state)

    log_power_event(is_online, now_ts)

    subscribers = load_subscribers()
    if not subscribers:
        logging.info("Стан змінився на %s, але немає підписників", is_online)
        return None

    # подготовим общий YASNO-прогноз (время включения), чтобы не дергать API для каждого чата
    yasno_eta_dt = None
    yasno_eta_status = None
    yasno_has_data = False

    if (not is_online) and YASNO_REGION_ID and YASNO_DSO_ID and YASNO_GROUP:
        try:
            eta = yasno_predict_on_time(
                now_ts=now_ts,
                region_id=YASNO_REGION_ID,
                dso_id=YASNO_DSO_ID,
                group_str=YASNO_GROUP,
            )
            if eta:
                yasno_eta_dt, yasno_eta_status = eta
                yasno_has_data = True
        except Exception:
            logging.exception("Помилка при розрахунку прогнозу за даними")
            yasno_has_data = False

    first_msg: Optional[str] = None
    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now_ts))

    for sub in subscribers:
        chat_id = sub.get("chat_id")
        thread_id = sub.get("thread_id")
        if chat_id is None:
            continue
        chat_id = int(chat_id)

        lang = get_lang_for_chat(chat_id, thread_id)

        lines: List[str] = []

        # заголовок
        if is_online:
            lines.append(t("notify.online.title", lang=lang))
        else:
            lines.append(t("notify.offline.title", lang=lang))

        # время события
        lines.append(t("notify.timestamp", lang=lang, ts=now_str))

        # длительность последнего отключения (если есть)
        if outage_seconds is not None and outage_seconds > 0:
            outage_str = format_duration_ua(outage_seconds)
            lines.append(
                t(
                    "notify.outage_duration",
                    lang=lang,
                    duration=outage_str,
                )
            )

        # YASNO-прогноз (только при отключении)
        if not is_online:
            if yasno_has_data and yasno_eta_dt is not None and yasno_eta_status is not None:
                eta_str = yasno_eta_dt.strftime("%H:%M")
                if yasno_eta_status == DayStatus.EMERGENCY_SHUTDOWNS:
                    kind = "екстрене відключення" if lang == "uk" else "emergency outage"
                else:
                    kind = "планове відключення" if lang == "uk" else "planned outage"

                lines.append(
                    t(
                        "notify.yasno.predicted_on",
                        lang=lang,
                        group=YASNO_GROUP,
                        kind=kind,
                        eta=eta_str,
                    )
                )
            else:
                # нет данных по графику
                lines.append(t("notify.yasno.no_data", lang=lang))

        msg = "\n".join(lines)

        # запомним любой один текст, чтобы вернуть из функции (для логов/отладки)
        first_msg = first_msg or msg

        # приватные чаты — с кнопкой "Прочитано"
        send_telegram_message_limited(
            chat_id=chat_id,
            text=msg,
            thread_id=thread_id,
            with_read_button=True,
        )

    return first_msg

