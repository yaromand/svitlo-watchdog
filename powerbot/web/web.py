import logging
import time
from datetime import datetime, date, timedelta
from typing import List, Optional
from flask import Flask, request, jsonify, render_template, Response

from powerbot.config.config import settings
from powerbot.constants.constants import DAY_NAMES_SHORT
from powerbot.storage.db import load_all_events
from powerbot.storage.state import load_state
from powerbot.domain.stats import (
    compute_day_stats,
    compute_day_hourly_online,
    format_duration_ua,
)
from powerbot.services.power_status import apply_status_change


flask_app = Flask(
    "svitlo_watchdog",
    template_folder=str(settings.PROJECT_ROOT / "templates"),
    static_folder=None,  # если статики нет; можно убрать или поменять
)

@flask_app.route("/power-hook", methods=["POST"])
def power_hook():
    data = request.get_json(force=True, silent=True) or {}
    logging.info("Отримано webhook: %s", data)

    if data.get("secret") != settings.WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    status_str = data.get("status")
    if status_str not in ("on", "off"):
        return jsonify({"ok": False, "error": "invalid status"}), 400

    is_online = (status_str == "on")

    ts = data.get("ts")
    try:
        now_ts = int(ts) if ts is not None else int(time.time())
    except Exception:
        now_ts = int(time.time())

    msg = apply_status_change(is_online, now_ts)

    return jsonify({"ok": True, "applied": bool(msg), "message": msg}), 200


@flask_app.route("/healthz")
def healthz():
    """
    Простий healthcheck:
    - пробуем прочитать события из БД
    """
    try:
        events = load_all_events()
        return jsonify({"ok": True, "events_count": len(events)}), 200
    except Exception as e:
        logging.exception("Healthcheck failed")
        return jsonify({"ok": False, "error": str(e)}), 500


def compute_uptime_ratio_window(
    events: List[tuple[int, bool]],
    window_seconds: int,
    now_ts: Optional[int] = None,
) -> Optional[float]:
    """
    Считает долю времени "online" за последний window_seconds.

    Возвращает число от 0 до 1 или None, если данных нет.
    Окно скользящее: [now - window, now].
    """
    if not events:
        return None

    if now_ts is None:
        now_ts = int(time.time())

    window_end = now_ts
    window_start = now_ts - window_seconds

    # если все события в будущем относительно окна — смысла нет
    first_ts = events[0][0]
    if first_ts >= window_end:
        return None

    # не уходим левее первой записи
    if window_start < first_ts:
        window_start = first_ts

    # статус в момент window_start
    cur_status = events[0][1]
    for ts, st in events:
        if ts <= window_start:
            cur_status = st
        else:
            break

    cur_ts = window_start
    online = 0

    for ts, st in events:
        if ts <= window_start:
            continue
        if ts >= window_end:
            break

        dur = ts - cur_ts
        if dur > 0 and cur_status:
            online += dur

        cur_status = st
        cur_ts = ts

    # хвост до window_end
    if cur_ts < window_end and cur_status:
        online += window_end - cur_ts

    total = window_end - window_start
    if total <= 0:
        return None

    return online / total


@flask_app.route("/metrics")
def metrics():
    """
    Prometheus metrics (text/plain):
      - power_events_total
      - power_status{status="online|offline|unknown"}
      - power_uptime_ratio{window="24h|7d"}
    """
    events = load_all_events()
    events_total = len(events)

    state = load_state()
    last_status = state.get("last_status")

    if last_status is True:
        current_label = "online"
    elif last_status is False:
        current_label = "offline"
    else:
        current_label = "unknown"

    now_ts = int(time.time())
    uptime_24h = compute_uptime_ratio_window(events, 24 * 3600, now_ts)
    uptime_7d = compute_uptime_ratio_window(events, 7 * 24 * 3600, now_ts)

    lines = []
    # --- общее количество событий ---
    lines.append("# HELP power_events_total Total number of power events")
    lines.append("# TYPE power_events_total counter")
    lines.append(f"power_events_total {events_total}")

    # --- текущий статус ---
    lines.append("# HELP power_status Current power status as a one-hot gauge")
    lines.append("# TYPE power_status gauge")
    for st in ("online", "offline", "unknown"):
        val = 1 if st == current_label else 0
        lines.append(f'power_status{{status="{st}"}} {val}')

    # --- аптайм ---
    lines.append("# HELP power_uptime_ratio Power uptime ratio over rolling window (0..1)")
    lines.append("# TYPE power_uptime_ratio gauge")
    if uptime_24h is not None:
        lines.append(f'power_uptime_ratio{{window="24h"}} {uptime_24h:.6f}')
    if uptime_7d is not None:
        lines.append(f'power_uptime_ratio{{window="7d"}} {uptime_7d:.6f}')

    text = "\n".join(lines) + "\n"
    return Response(text, mimetype="text/plain")


@flask_app.route("/")
def index():
    events = load_all_events()
    today = date.today()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    current_status = events[-1][1] if events else None
    stats_today = compute_day_stats(today, events) if events else None

    if stats_today:
        on_str = format_duration_ua(stats_today["on_seconds"])
        off_str = format_duration_ua(stats_today["off_seconds"])
        total = stats_today["on_seconds"] + stats_today["off_seconds"]
        avail_pct = round(stats_today["on_seconds"] * 100 / total, 1) if total > 0 else None
    else:
        on_str = off_str = ""
        avail_pct = None

    hourly = compute_day_hourly_online(today, events) if events else None
    if hourly:
        hourly_pct = [round(sec * 100 / 3600, 1) for sec in hourly]
    else:
        hourly_pct = [0] * 24

    labels = [f"{h:02d}:00" for h in range(24)]

    days_param = request.args.get("days", "1")
    try:
        days_window = int(days_param)
    except ValueError:
        days_window = 1
    days_window = max(1, min(days_window, 30))

    history_days = []
    now_ts = int(time.time())

    for i in range(days_window):
        day = today - timedelta(days=i)
        stats_day = compute_day_stats(day, events)

        entry = {
            "date_str": day.strftime("%d.%m.%Y"),
            "weekday": DAY_NAMES_SHORT[day.weekday()],
            "has_data": bool(stats_day),
            "on_str": "",
            "off_str": "",
            "outages": [],
        }

        if stats_day:
            entry["on_str"] = format_duration_ua(stats_day["on_seconds"])
            entry["off_str"] = format_duration_ua(stats_day["off_seconds"])
            outages_list = []
            for start_ts, end_ts in stats_day["outages"]:
                if end_ts is None:
                    if day == today:
                        end_ts_eff = now_ts
                        is_open = True
                    else:
                        end_ts_eff = stats_day["day_end_ts"]
                        is_open = False
                else:
                    end_ts_eff = end_ts
                    is_open = False

                start_dt = datetime.fromtimestamp(start_ts)
                end_dt = datetime.fromtimestamp(end_ts_eff)
                duration = max(0, end_ts_eff - start_ts)
                outages_list.append(
                    {
                        "start_str": start_dt.strftime("%d.%m %H:%M"),
                        "end_str": "триває" if is_open else end_dt.strftime("%d.%m %H:%M"),
                        "duration_str": format_duration_ua(duration),
                        "is_open": is_open,
                    }
                )
            entry["outages"] = outages_list

        history_days.append(entry)

    return render_template(
        "index.html",
        now_str=now_str,
        current_status=current_status,
        stats=stats_today,
        on_str=on_str,
        off_str=off_str,
        avail_pct=avail_pct,
        hourly_pct=hourly_pct,
        labels=labels,
        history_days=history_days,
        days_window=days_window,
        web_base_url=settings.WEB_BASE_URL,
    )


@flask_app.route("/history-data")
def history_data():
    events = load_all_events()
    today = date.today()

    days_param = request.args.get("days", "1")
    try:
        days_window = int(days_param)
    except ValueError:
        days_window = 1
    days_window = max(1, min(days_window, 30))

    history_days = []
    now_ts = int(time.time())

    for i in range(days_window):
        day = today - timedelta(days=i)
        stats_day = compute_day_stats(day, events)

        entry = {
            "date_str": day.strftime("%d.%m.%Y"),
            "weekday": DAY_NAMES_SHORT[day.weekday()],
            "has_data": bool(stats_day),
            "on_str": "",
            "off_str": "",
            "outages": [],
        }

        if stats_day:
            entry["on_str"] = format_duration_ua(stats_day["on_seconds"])
            entry["off_str"] = format_duration_ua(stats_day["off_seconds"])

            outages_list = []
            for start_ts, end_ts in stats_day["outages"]:
                if end_ts is None:
                    if day == today:
                        end_ts_eff = now_ts
                        is_open = True
                    else:
                        end_ts_eff = stats_day["day_end_ts"]
                        is_open = False
                else:
                    end_ts_eff = end_ts
                    is_open = False

                start_dt = datetime.fromtimestamp(start_ts)
                end_dt = datetime.fromtimestamp(end_ts_eff)
                duration = max(0, end_ts_eff - start_ts)

                outages_list.append(
                    {
                        "start_str": start_dt.strftime("%d.%м %H:%M").replace("%м", "%m"),
                        "end_str": "триває" if is_open else end_dt.strftime("%d.%m %H:%M"),
                        "duration_str": format_duration_ua(duration),
                        "is_open": is_open,
                    }
                )

            entry["outages"] = outages_list

        history_days.append(entry)

    return jsonify({"history_days": history_days, "days_window": days_window})


def run_flask() -> None:
    flask_app.run(
        host=settings.BIND_HOST,
        port=settings.WEB_PORT,
        debug=False,
        use_reloader=False,
    )
