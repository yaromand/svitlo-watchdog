import logging
import time
from datetime import datetime, timedelta

from powerbot.config.config import settings
from powerbot.lang.i18n import get_lang_for_chat, t
from powerbot.yasno.cache.cache import (
    load_yasno_state,
    save_yasno_state,
    update_day_schedule,
)
from powerbot.storage.subscribers import load_subscribers
from powerbot.telegram.client import send_telegram_message_limited
from powerbot.yasno.client import (
    yasno_today_slots,
    yasno_tomorrow_slots,
    DayStatus,
)


def yasno_watchdog_worker():
    """
    Фоновий потік:
    - періодично тягне графік YASNO на сьогодні та на завтра,
    - зберігає його по датах у yasno_state.json,
    - надсилає сповіщення всім підписникам ТІЛЬКИ коли графік
      для конкретної дати реально змінюється.

    Тепер:
    - якщо оновився сьогодні й завтра — відправляємо ОДНЕ повідомлення,
      в якому є обидва блоки;
    - текст локалізований по мові чату (uk/en);
    - у приватних чатах додається кнопка "Прочитано" з видаленням.
    """
    if not (settings.YASNO_REGION_ID and settings.YASNO_DSO_ID and settings.YASNO_GROUP):
        logging.info(
            "YASNO watchdog вимкнено: не задані YASNO_REGION_ID / YASNO_DSO_ID / YASNO_GROUP"
        )
        return

    logging.info(
        "YASNO watchdog запущено (region_id=%s, dso_id=%s, group=%s, interval=%s сек)",
        settings.YASNO_REGION_ID,
        settings.YASNO_DSO_ID,
        settings.YASNO_GROUP,
        settings.YASNO_POLL_INTERVAL,
    )

    while True:
        try:
            now_ts = int(time.time())
            today_date = datetime.fromtimestamp(now_ts).date()
            tomorrow_date = today_date + timedelta(days=1)

            slots_today = yasno_today_slots(
                now_ts=now_ts,
                region_id=settings.YASNO_REGION_ID,
                dso_id=settings.YASNO_DSO_ID,
                group_str=settings.YASNO_GROUP,
            )
            slots_tomorrow = yasno_tomorrow_slots(
                now_ts=now_ts,
                region_id=settings.YASNO_REGION_ID,
                dso_id=settings.YASNO_DSO_ID,
                group_str=settings.YASNO_GROUP,
            )

            state = load_yasno_state()
            days = state.get("days") or {}

            changed_today = update_day_schedule(days, today_date, slots_today, now_ts)
            changed_tomorrow = update_day_schedule(
                days, tomorrow_date, slots_tomorrow, now_ts
            )

            state["days"] = days
            state["last_check_ts"] = now_ts
            save_yasno_state(state)

            subscribers = load_subscribers()
            if not subscribers:
                time.sleep(settings.YASNO_POLL_INTERVAL)
                continue

            # если график вообще не изменился — ничего не шлём
            if not changed_today and not changed_tomorrow:
                time.sleep(settings.YASNO_POLL_INTERVAL)
                continue

            today_str = today_date.strftime("%d.%m.%Y")
            tomorrow_str = tomorrow_date.strftime("%d.%m.%Y")

            for sub in subscribers:
                chat_id = sub.get("chat_id")
                thread_id = sub.get("thread_id")
                if chat_id is None:
                    continue
                chat_id = int(chat_id)

                lang = get_lang_for_chat(chat_id, thread_id)

                lines: list[str] = []

                # --- блок "сьогодні" ---
                if changed_today:
                    lines.append(
                        t(
                            "yasno.watch.today.header",
                            lang=lang,
                            date=today_str,
                        )
                    )
                    lines.append(
                        t(
                            "yasno.watch.group",
                            lang=lang,
                            group=settings.YASNO_GROUP,
                        )
                    )
                    lines.append("")  # пустая строка

                    if slots_today:
                        for s in slots_today:
                            start_str = s.dt_start.strftime("%H:%M")
                            end_str = s.dt_end.strftime("%H:%M")

                            if s.day_status == DayStatus.EMERGENCY_SHUTDOWNS:
                                prefix = "🚨"
                            elif s.day_status == DayStatus.SCHEDULE_APPLIES:
                                prefix = "⚡"
                            else:
                                prefix = "•"

                            lines.append(
                                t(
                                    "yasno.watch.slot.line",
                                    lang=lang,
                                    prefix=prefix,
                                    start=start_str,
                                    end=end_str,
                                    title=s.title,
                                )
                            )
                    else:
                        lines.append(t("yasno.watch.today.empty", lang=lang))

                # --- блок "завтра" ---
                if changed_tomorrow and slots_tomorrow:
                    if lines:
                        lines.append("")  # разделяем пустой строкой

                    lines.append(
                        t(
                            "yasno.watch.tomorrow.header",
                            lang=lang,
                            date=tomorrow_str,
                        )
                    )
                    lines.append(
                        t(
                            "yasno.watch.group",
                            lang=lang,
                            group=settings.YASNO_GROUP,
                        )
                    )
                    lines.append("")

                    for s in slots_tomorrow:
                        start_str = s.dt_start.strftime("%H:%M")
                        end_str = s.dt_end.strftime("%H:%M")

                        if s.day_status == DayStatus.EMERGENCY_SHUTDOWNS:
                            prefix = "🚨"
                        elif s.day_status == DayStatus.SCHEDULE_APPLIES:
                            prefix = "⚡"
                        else:
                            prefix = "•"

                        lines.append(
                            t(
                                "yasno.watch.slot.line",
                                lang=lang,
                                prefix=prefix,
                                start=start_str,
                                end=end_str,
                                title=s.title,
                            )
                        )

                if not lines:
                    # на всякий случай
                    continue

                full_msg = "\n".join(lines)

                send_telegram_message_limited(
                    chat_id=chat_id,
                    text=full_msg,
                    thread_id=thread_id,
                    with_read_button=True,
                )

        except Exception:
            logging.exception("Помилка в потоці YASNO-watchdog")

        time.sleep(settings.YASNO_POLL_INTERVAL)
