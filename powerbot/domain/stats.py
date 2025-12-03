import time
from datetime import datetime, date, time as dtime, timedelta
from typing import List, Tuple, Optional


def plural_ua(n: int, form1: str, form2: str, form5: str) -> str:
    n = abs(int(n))
    n10 = n % 10
    n100 = n % 100
    if n10 == 1 and n100 != 11:
        return form1
    if 2 <= n10 <= 4 and not (12 <= n100 <= 14):
        return form2
    return form5


def format_duration_ua(seconds: int) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    parts = []
    if h > 0:
        parts.append(f"{h} {plural_ua(h, 'година', 'години', 'годин')}")
    if m > 0 or not parts:
        parts.append(f"{m} {plural_ua(m, 'хвилина', 'хвилини', 'хвилин')}")
    return " ".join(parts)


def compute_day_stats(day: date, events: List[Tuple[int, bool]]) -> Optional[dict]:
    now_ts = int(time.time())

    day_start = datetime.combine(day, dtime.min)
    day_end = day_start + timedelta(days=1)

    day_start_ts = int(day_start.timestamp())
    day_end_ts = int(day_end.timestamp())

    if day == datetime.fromtimestamp(now_ts).date():
        day_end_ts = min(day_end_ts, now_ts)

    before = None
    for ts, st in events:
        if ts < day_start_ts:
            before = (ts, st)
        else:
            break

    events_in_day = [(ts, st) for ts, st in events if day_start_ts <= ts < day_end_ts]

    if before is None and not events_in_day:
        return None

    if before is not None:
        cur_status = before[1]
        current_ts = day_start_ts
        idx_start = 0
        off_start_ts = day_start_ts if cur_status is False else None
    else:
        cur_status = events_in_day[0][1]
        current_ts = events_in_day[0][0]
        idx_start = 1
        off_start_ts = current_ts if cur_status is False else None

    on_seconds = 0
    off_seconds = 0
    outages: List[Tuple[int, Optional[int]]] = []

    for ts, status in events_in_day[idx_start:]:
        duration = ts - current_ts
        if duration < 0:
            duration = 0

        if cur_status:
            on_seconds += duration
        else:
            off_seconds += duration

        if cur_status and not status:
            off_start_ts = ts
        elif (not cur_status) and status:
            if off_start_ts is None:
                off_start_ts = current_ts
            outages.append((off_start_ts, ts))
            off_start_ts = None

        cur_status = status
        current_ts = ts

    duration = day_end_ts - current_ts
    if duration < 0:
        duration = 0

    if cur_status:
        on_seconds += duration
    else:
        off_seconds += duration

    if not cur_status and duration > 0:
        if off_start_ts is None:
            off_start_ts = current_ts
        outages.append((off_start_ts, None))

    return {
        "on_seconds": on_seconds,
        "off_seconds": off_seconds,
        "outages": outages,
        "day_start_ts": day_start_ts,
        "day_end_ts": day_end_ts,
    }


def compute_day_hourly_online(
    day: date,
    events: List[Tuple[int, bool]],
) -> Optional[list]:
    now_ts = int(time.time())
    day_start = datetime.combine(day, dtime.min)
    day_end = day_start + timedelta(days=1)
    day_start_ts = int(day_start.timestamp())
    day_end_ts = int(day_end.timestamp())
    if day == datetime.fromtimestamp(now_ts).date():
        day_end_ts = min(day_end_ts, now_ts)

    before = None
    idx_first_in_day = None
    for idx, (ts, st) in enumerate(events):
        if ts < day_start_ts:
            before = (ts, st)
        elif ts < day_end_ts and idx_first_in_day is None:
            idx_first_in_day = idx
        elif ts >= day_end_ts:
            break

    events_in_day = []
    if idx_first_in_day is not None:
        for ts, st in events[idx_first_in_day:]:
            if ts >= day_end_ts:
                break
            events_in_day.append((ts, st))

    if before is None and not events_in_day:
        return None

    if before is not None:
        cur_status = before[1]
        cur_ts = day_start_ts
        idx_start = 0
    else:
        cur_status = events_in_day[0][1]
        cur_ts = events_in_day[0][0]
        idx_start = 1

    online = [0] * 24

    def add_segment(start_ts: int, end_ts: int) -> None:
        nonlocal online, day_start_ts
        if end_ts <= start_ts:
            return
        s = start_ts
        while s < end_ts:
            hour_idx = int((s - day_start_ts) // 3600)
            if hour_idx < 0:
                hour_idx = 0
            if hour_idx > 23:
                hour_idx = 23
            hour_start_ts = day_start_ts + hour_idx * 3600
            hour_end_ts = hour_start_ts + 3600
            seg_end = min(end_ts, hour_end_ts)
            dur = seg_end - s
            if 0 <= hour_idx < 24:
                online[hour_idx] += dur
            s = seg_end

    for ts, st in events_in_day[idx_start:]:
        seg_end = ts
        if cur_status:
            add_segment(cur_ts, seg_end)
        cur_status = st
        cur_ts = ts

    if cur_ts < day_end_ts and cur_status:
        add_segment(cur_ts, day_end_ts)

    return online


def get_last_transitions(
    events: List[Tuple[int, bool]],
) -> Tuple[Optional[int], Optional[int]]:
    if not events:
        return None, None

    last_off_ts: Optional[int] = None
    last_on_ts: Optional[int] = None

    prev_ts, prev_status = events[0]

    for ts, status in events[1:]:
        if prev_status and not status:
            last_off_ts = ts
        elif (not prev_status) and status:
            last_on_ts = ts
        prev_ts, prev_status = ts, status

    return last_off_ts, last_on_ts
