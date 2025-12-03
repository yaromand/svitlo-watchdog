
import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import ContextTypes

from powerbot.config.config import settings
from powerbot.constants.constants import DAY_NAMES_SHORT
from powerbot.domain.stats import (
    format_duration_ua,
    compute_day_stats,
    get_last_transitions,
    plural_ua,
)
from powerbot.storage.state import load_state
from powerbot.storage.db import load_all_events
from powerbot.storage.subscribers import load_subscribers, save_subscribers
from powerbot.storage.chat import get_chat_lang, set_chat_lang
from powerbot.yasno.client import (
    yasno_today_slots,
    yasno_tomorrow_slots,
    yasno_predict_on_time,
    DayStatus,
)
from powerbot.lang.i18n import get_lang_from_update, t, SUPPORTED_LANGS, get_lang_name


def is_group_chat(update: Update) -> bool:
    chat = update.effective_chat
    return bool(chat and chat.type in ("group", "supergroup"))


def build_chat_title(chat) -> Optional[str]:
    """
    Строим человеко-читаемое имя чата.
    """
    if chat is None:
        return None

    ctype = getattr(chat, "type", None)

    if ctype in ("group", "supergroup", "channel"):
        return getattr(chat, "title", None)

    if ctype == "private":
        username = getattr(chat, "username", None)
        if username:
            return f"@{username}"
        parts = []
        first_name = getattr(chat, "first_name", None)
        last_name = getattr(chat, "last_name", None)
        if first_name:
            parts.append(first_name)
        if last_name:
            parts.append(last_name)
        name = " ".join(parts).strip()
        return name or None

    return getattr(chat, "title", None)


def resolve_lang(update: Update) -> str:
    """
    Определяет язык для этого апдейта:
    1) если для chat_id/thread_id явно сохранён язык через /lang — берём его;
    2) иначе — по language_code пользователя.
    """
    chat = update.effective_chat
    msg = update.effective_message
    thread_id: Optional[int] = None
    if msg and getattr(msg, "message_thread_id", None) is not None:
        thread_id = msg.message_thread_id

    if chat is not None:
        saved = get_chat_lang(chat.id, thread_id)
        if saved:
            return saved

    return get_lang_from_update(update)


async def send_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> None:
    chat = update.effective_chat
    if not chat:
        return

    chat_id = chat.id

    thread_id: Optional[int] = None
    msg = update.effective_message
    if msg and getattr(msg, "message_thread_id", None) is not None:
        thread_id = msg.message_thread_id

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            message_thread_id=thread_id if thread_id is not None else None,
        )
    except Exception as e:
        logging.warning("Не вдалося надіслати повідомлення у чат %s: %s", chat_id, e)

    if is_group_chat(update) and update.message:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=update.message.message_id,
            )
        except Exception as e:
            logging.warning("Не вдалося видалити повідомлення з командою: %s", e)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    msg = update.effective_message
    chat_id = chat.id

    thread_id: Optional[int] = None
    if msg and getattr(msg, "message_thread_id", None) is not None:
        thread_id = msg.message_thread_id

    title = build_chat_title(chat)
    subscribers = load_subscribers()

    found = False
    for sub in subscribers:
        if sub.get("chat_id") == chat_id and sub.get("thread_id") == thread_id:
            found = True
            old_title = sub.get("title")
            if title and title != old_title:
                sub["title"] = title
            break

    if not found:
        subscribers.append({"chat_id": chat_id, "thread_id": thread_id, "title": title})

    save_subscribers(subscribers)

    logging.info(
        "Новий підписник: chat_id=%s, thread_id=%s, title=%r",
        chat_id,
        thread_id,
        title,
    )

    # уведомление админу
    if settings.ADMIN_CHAT_ID:
        try:
            admin_text = t(
                "admin.new_subscriber",
                lang="uk",
                chat_id=chat_id,
                title=title or "—",
                thread=thread_id if thread_id is not None else "—",
            )
            await context.bot.send_message(chat_id=settings.ADMIN_CHAT_ID, text=admin_text)
        except Exception as e:
            logging.warning("Не вдалося надіслати адмін-увідомлення: %s", e)

    lang = resolve_lang(update)

    if not found:
        text = t("start.new", lang=lang)
        if thread_id is not None:
            # просто допишем строку, i18n не критично
            text += "\n\n(Ти підписаний саме в цій гілці чату 🧵)"
    else:
        text = t("start.existing", lang=lang)

    await send_reply(update, context, text)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    msg = update.effective_message

    chat_id = chat.id
    thread_id: Optional[int] = None
    if msg and getattr(msg, "message_thread_id", None) is not None:
        thread_id = msg.message_thread_id

    subscribers = load_subscribers()
    before_len = len(subscribers)

    subscribers = [
        sub
        for sub in subscribers
        if not (sub.get("chat_id") == chat_id and sub.get("thread_id") == thread_id)
    ]
    after_len = len(subscribers)
    lang = resolve_lang(update)

    if after_len < before_len:
        save_subscribers(subscribers)
        text = t("stop.unsubscribed", lang=lang)
    else:
        text = t("stop.not_subscribed", lang=lang)

    await send_reply(update, context, text)


async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /lang
    /lang list
    /lang en
    """
    chat = update.effective_chat
    msg = update.effective_message
    if not chat:
        return

    chat_id = chat.id
    thread_id: Optional[int] = None
    if msg and getattr(msg, "message_thread_id", None) is not None:
        thread_id = msg.message_thread_id

    ui_lang = resolve_lang(update)

    args = context.args if getattr(context, "args", None) else []

    supported_codes = list(SUPPORTED_LANGS.keys())
    supported_label = ", ".join(
        f"{code} ({get_lang_name(code, ui_lang)})" for code in supported_codes
    )

    # /lang  или /lang list  → показать текущий язык + инлайн-клавиатуру
    show_keyboard = (not args) or (len(args) == 1 and args[0].lower() == "list")
    if show_keyboard:
        current = get_chat_lang(chat_id, thread_id) or ui_lang
        current_name = get_lang_name(current, ui_lang)

        text = t(
            "lang.current",
            lang=ui_lang,
            lang_name=current_name,
            lang_code=current,
        )
        text += "\n\n" + t("lang.usage", lang=ui_lang, supported=supported_label)
        text += "\n\n👇"

        keyboard = [
            [
                InlineKeyboardButton(
                    get_lang_name(code, ui_lang),
                    callback_data=f"lang:{code}",
                )
            ]
            for code in supported_codes
        ]
        markup = InlineKeyboardMarkup(keyboard)

        await send_reply(update, context, text, reply_markup=markup)
        return

    # /lang en  → явно выставляем язык
    code = args[0].lower()
    if code not in SUPPORTED_LANGS:
        text = t("lang.invalid", lang=ui_lang, supported=supported_label)
        await send_reply(update, context, text)
        return

    set_chat_lang(chat_id, thread_id, code)
    name = get_lang_name(code, ui_lang)
    text = t("lang.updated", lang=ui_lang, lang_name=name, lang_code=code)
    await send_reply(update, context, text)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = resolve_lang(update)
    state = load_state()
    last_status = state.get("last_status")
    last_change_ts = state.get("last_change_ts")

    lines: List[str] = []
    lines.append(t("status.header", lang=lang))

    if last_status is True:
        lines.append(t("status.online", lang=lang))
    elif last_status is False:
        lines.append(t("status.offline", lang=lang))
    else:
        lines.append(t("status.unknown", lang=lang))

    if last_change_ts:
        dt = datetime.fromtimestamp(int(last_change_ts))
        lines.append(
            t("status.last_change", lang=lang, ts=dt.strftime("%d.%m.%Y %H:%M:%S"))
        )

    now_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    lines.append(t("status.now", lang=lang, now=now_str))

    # блок YASNO
    if settings.YASNO_REGION_ID and settings.YASNO_DSO_ID and settings.YASNO_GROUP:
        now_ts = int(time.time())
        today_str = datetime.fromtimestamp(now_ts).strftime("%d.%m.%Y")
        lines.append("")
        lines.append(t("status.yasno.header", lang=lang))

        try:
            eta = yasno_predict_on_time(
                now_ts=now_ts,
                region_id=settings.YASNO_REGION_ID,
                dso_id=settings.YASNO_DSO_ID,
                group_str=settings.YASNO_GROUP,
            )
            slots_today = yasno_today_slots(
                now_ts=now_ts,
                region_id=settings.YASNO_REGION_ID,
                dso_id=settings.YASNO_DSO_ID,
                group_str=settings.YASNO_GROUP,
            )

            lines.append(
                t(
                    "status.yasno.group_date",
                    lang=lang,
                    group=settings.YASNO_GROUP,
                    date=today_str,
                )
            )

            if eta:
                eta_dt, eta_status = eta
                eta_str = eta_dt.strftime("%H:%M")

                eta_ts = int(eta_dt.timestamp())
                delta_sec = max(0, eta_ts - now_ts)
                delta_str = format_duration_ua(delta_sec)

                if eta_status == DayStatus.EMERGENCY_SHUTDOWNS:
                    kind = "екстрене відключення" if lang == "uk" else "emergency outage"
                else:
                    kind = "планове відключення" if lang == "uk" else "planned outage"

                if last_status is False:
                    lines.append(
                        t(
                            "status.yasno.kind_now_eta_off",
                            lang=lang,
                            kind=kind,
                            eta_time=eta_str,
                        )
                    )
                    now_dt = datetime.fromtimestamp(now_ts)
                    remaining_sec = max(
                        0, int((eta_dt - now_dt).total_seconds())
                    )
                    lines.append(
                        t(
                            "status.yasno.remaining_off",
                            lang=lang,
                            duration=format_duration_ua(remaining_sec),
                        )
                    )
                else:
                    lines.append(
                        t(
                            "status.yasno.next_change_on",
                            lang=lang,
                            eta_time=eta_str,
                        )
                    )
            else:
                lines.append(t("status.yasno.cant_predict", lang=lang))

            if slots_today:
                lines.append(t("status.yasno.today_windows_header", lang=lang))
                upcoming = [s for s in slots_today if s.dt_end.timestamp() > now_ts]
                for s in upcoming[:2]:
                    start_str = s.dt_start.strftime("%H:%M")
                    end_str = s.dt_end.strftime("%H:%M")

                    if s.day_status == DayStatus.EMERGENCY_SHUTDOWNS:
                        prefix = "🚨"
                    elif s.day_status == DayStatus.SCHEDULE_APPLIES:
                        prefix = "⚡"
                    else:
                        prefix = "•"

                    lines.append(f"  {prefix} {start_str}–{end_str} — {s.title}")
            else:
                lines.append(t("status.yasno.today_windows_absent", lang=lang))
        except Exception:
            logging.exception("Помилка при отриманні статусу YASNO")
            lines.append(t("status.yasno.error", lang=lang))
    else:
        lines.append(t("status.yasno.config_missing", lang=lang))

    await send_reply(update, context, "\n".join(lines))


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = resolve_lang(update)
    events = load_all_events()
    if not events:
        await send_reply(update, context, t("common.no_data_yet", lang=lang))
        return

    today = date.today()
    stats_today = compute_day_stats(today, events)
    last_off_ts, last_on_ts = get_last_transitions(events)

    state = load_state()
    last_status = state.get("last_status")

    lines: List[str] = []
    lines.append(
        t(
            "today.header",
            lang=lang,
            date=today.strftime("%d.%m.%Y"),
        )
    )

    if last_status is True:
        lines.append(t("today.status.online", lang=lang))
    elif last_status is False:
        lines.append(t("today.status.offline", lang=lang))
    else:
        lines.append(t("today.status.unknown", lang=lang))

    if last_off_ts:
        dt_off = datetime.fromtimestamp(last_off_ts)
        lines.append(
            t(
                "today.last_off",
                lang=lang,
                ts=dt_off.strftime("%d.%m.%Y %H:%M"),
            )
        )
    else:
        lines.append(t("today.last_off_none", lang=lang))

    if last_on_ts:
        dt_on = datetime.fromtimestamp(last_on_ts)
        lines.append(
            t(
                "today.last_on",
                lang=lang,
                ts=dt_on.strftime("%d.%m.%Y %H:%M"),
            )
        )
    else:
        lines.append(t("today.last_on_none", lang=lang))

    if stats_today:
        outages_today = stats_today["outages"]
        n = len(outages_today)
        if lang == "uk":
            word = plural_ua(n, "відключення", "відключення", "відключень")
            lines.append(
                t(
                    "today.outages",
                    lang=lang,
                    count=n,
                    word=word,
                )
            )
        else:
            lines.append(
                t(
                    "today.outages",
                    lang=lang,
                    count=n,
                )
            )
    else:
        lines.append(t("today.no_outages", lang=lang))

    await send_reply(update, context, "\n".join(lines))


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = resolve_lang(update)
    events = load_all_events()
    if not events:
        await send_reply(update, context, t("common.no_data_yet", lang=lang))
        return

    today = date.today()
    weekday = today.weekday()  # 0 = Пн, 6 = Нд
    monday = today - timedelta(days=weekday)

    lines: List[str] = []
    lines.append(
        t(
            "week.header",
            lang=lang,
            monday=monday.strftime("%d.%m"),
            today=today.strftime("%d.%m"),
        )
    )

    has_any = False

    for i in range(weekday + 1):
        day = monday + timedelta(days=i)
        stats = compute_day_stats(day, events)
        name = DAY_NAMES_SHORT[day.weekday()]
        ds = day.strftime("%d.%m")

        if not stats:
            lines.append(
                t(
                    "week.day.no_data",
                    lang=lang,
                    weekday=name,
                    date=ds,
                )
            )
            continue

        has_any = True
        on_s = stats["on_seconds"]
        off_s = stats["off_seconds"]
        outages_count = len(stats["outages"])

        lines.append(
            t(
                "week.day.stats",
                lang=lang,
                weekday=name,
                date=ds,
                outages=outages_count,
                on=format_duration_ua(on_s),
                off=format_duration_ua(off_s),
            )
        )

    if not has_any:
        text = t("week.no_data", lang=lang)
    else:
        text = "\n".join(lines)

    await send_reply(update, context, text)


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Графік відключень YASNO на сьогодні.
    """
    lang = resolve_lang(update)
    now_ts = int(time.time())

    if not (settings.YASNO_REGION_ID and settings.YASNO_DSO_ID and settings.YASNO_GROUP):
        await send_reply(update, context, t("common.yasno_not_configured", lang=lang))
        return

    try:
        slots = yasno_today_slots(
            now_ts=now_ts,
            region_id=settings.YASNO_REGION_ID,
            dso_id=settings.YASNO_DSO_ID,
            group_str=settings.YASNO_GROUP,
        )
    except Exception:
        logging.exception("Помилка при отриманні графіка YASNO")
        await send_reply(
            update,
            context,
            t("common.yasno_fetch_error_today", lang=lang),
        )
        return

    today_str = datetime.fromtimestamp(now_ts).strftime("%d.%m.%Y")
    lines: List[str] = []
    lines.append(
        t(
            "schedule.today.header",
            lang=lang,
            date=today_str,
        )
    )
    lines.append(
        t(
            "schedule.today.group",
            lang=lang,
            group=settings.YASNO_GROUP,
        )
        + "\n"
    )

    if not slots:
        lines.append(t("schedule.today.none", lang=lang))
        await send_reply(update, context, "\n".join(lines))
        return

    for slot in slots:
        start_str = slot.dt_start.strftime("%H:%M")
        end_str = slot.dt_end.strftime("%H:%M")

        if slot.day_status == DayStatus.EMERGENCY_SHUTDOWNS:
            prefix = "🚨"
        elif slot.day_status == DayStatus.SCHEDULE_APPLIES:
            prefix = "⚡"
        else:
            prefix = "•"

        lines.append(f"{prefix} {start_str}–{end_str} — {slot.title}")

    await send_reply(update, context, "\n".join(lines))


async def cmd_schedule_tomorrow(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Графік відключень YASNO на завтра.
    """
    lang = resolve_lang(update)
    now_ts = int(time.time())

    if not (settings.YASNO_REGION_ID and settings.YASNO_DSO_ID and settings.YASNO_GROUP):
        await send_reply(update, context, t("common.yasno_not_configured", lang=lang))
        return

    try:
        slots = yasno_tomorrow_slots(
            now_ts=now_ts,
            region_id=settings.YASNO_REGION_ID,
            dso_id=settings.YASNO_DSO_ID,
            group_str=settings.YASNO_GROUP,
        )
    except Exception:
        logging.exception("Помилка при отриманні завтрашнього графіка")
        await send_reply(
            update,
            context,
            t("common.yasno_fetch_error_tomorrow", lang=lang),
        )
        return

    tomorrow_date = (
        datetime.fromtimestamp(now_ts).date() + timedelta(days=1)
    ).strftime("%d.%m.%Y")

    lines: List[str] = []
    lines.append(
        t(
            "schedule.tomorrow.header",
            lang=lang,
            date=tomorrow_date,
        )
    )
    lines.append(
        t(
            "schedule.tomorrow.group",
            lang=lang,
            group=settings.YASNO_GROUP,
        )
        + "\n"
    )

    if not slots:
        lines.append(t("schedule.tomorrow.none", lang=lang))
        await send_reply(update, context, "\n".join(lines))
        return

    for slot in slots:
        start_str = slot.dt_start.strftime("%H:%M")
        end_str = slot.dt_end.strftime("%H:%M")

        if slot.day_status == DayStatus.EMERGENCY_SHUTDOWNS:
            prefix = "🚨"
        elif slot.day_status == DayStatus.SCHEDULE_APPLIES:
            prefix = "⚡"
        else:
            prefix = "•"

        lines.append(f"{prefix} {start_str}–{end_str} — {slot.title}")

    await send_reply(update, context, "\n".join(lines))
