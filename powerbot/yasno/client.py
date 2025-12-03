from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Optional

import requests
from pydantic import BaseModel, TypeAdapter



class Group(StrEnum):
    G1_1 = "1.1"
    G1_2 = "1.2"
    G2_1 = "2.1"
    G2_2 = "2.2"
    G3_1 = "3.1"
    G3_2 = "3.2"
    G4_1 = "4.1"
    G4_2 = "4.2"
    G5_1 = "5.1"
    G5_2 = "5.2"
    G6_1 = "6.1"
    G6_2 = "6.2"


class SlotType(StrEnum):
    DEFINITE = "Definite"
    NOT_PLANNED = "NotPlanned"


class DayName(StrEnum):
    TODAY = "today"
    TOMORROW = "tomorrow"
    MONDAY = "0"
    TUESDAY = "1"
    WEDNESDAY = "2"
    THURSDAY = "3"
    FRIDAY = "4"
    SATURDAY = "5"
    SUNDAY = "6"


class DayStatus(StrEnum):
    SCHEDULE_APPLIES = "ScheduleApplies"
    WAITING_FOR_SCHEDULE = "WaitingForSchedule"
    EMERGENCY_SHUTDOWNS = "EmergencyShutdowns"


class Slot(BaseModel):
    start: int
    end: int
    type: SlotType = SlotType.DEFINITE
    date_start: datetime | None = None
    date_end: datetime | None = None
    day_status: DayStatus | None = None

    @property
    def dt_start(self) -> datetime:
        return self.date_start + timedelta(minutes=self.start)

    @property
    def dt_end(self) -> datetime:
        return self.date_end + timedelta(minutes=self.end)

    @property
    def title(self) -> str:
        match self.day_status:
            case DayStatus.SCHEDULE_APPLIES:
                return "Заплановане відключення"
            case DayStatus.EMERGENCY_SHUTDOWNS:
                return "🚨 Екстрені відключення"
            case DayStatus.WAITING_FOR_SCHEDULE:
                return "Імовірне відключення"
        return "Відключення"


class Day(BaseModel):
    slots: list[Slot]
    date: datetime
    status: DayStatus | None = None

    def get_slots(self) -> list[Slot]:
        match self.status:
            case DayStatus.SCHEDULE_APPLIES | DayStatus.WAITING_FOR_SCHEDULE:
                for slot in self.slots:
                    slot.date_start = slot.date_end = self.date
                    slot.day_status = self.status
            case DayStatus.EMERGENCY_SHUTDOWNS:
                slot = Slot(
                    start=0,
                    end=1440,
                    date_start=self.date,
                    date_end=self.date,
                    day_status=self.status,
                )
                self.slots = [slot]

        # берем только «точные» слоты и выкидываем «очікуємо на графік»
        return [
            slot
            for slot in self.slots
            if slot.type == SlotType.DEFINITE
            and slot.day_status != DayStatus.WAITING_FOR_SCHEDULE
        ]


class YasnoBlackout:
    URL = "https://app.yasno.ua/api/blackout-service/public/shutdowns"

    _DAY_TA = TypeAdapter(Day)

    def _get(self, *path, **params):
        url = "/".join(map(str, (self.URL, *path)))
        resp = requests.get(url=url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def planned_outages(self, region_id: int, dso_id: int) -> dict[Group, list[Slot]]:
        """
        Возвращает:
            { Group('1.1'): [Slot, Slot, ...], Group('1.2'): [...], ... }
        с уже объединёнными слотами по дням.
        """
        result = self._get("regions", region_id, "dsos", dso_id, "planned-outages")

        groups: dict[Group, list[Slot]] = defaultdict(list)

        for group_id, day_data in result.items():
            for day_name in DayName:
                key = day_name.value
                if key not in day_data:
                    continue

                day_slots = self._DAY_TA.validate_python(day_data[key]).get_slots()
                slots = day_slots[:]

                if groups[Group(group_id)] and slots:
                    last_slot = groups[Group(group_id)][-1]
                    next_slot = slots[0]

                    # если два слота стык в стык и одного типа – склеиваем
                    if (
                        last_slot.dt_end == next_slot.dt_start
                        and last_slot.type == next_slot.type
                        and last_slot.day_status == next_slot.day_status
                    ):
                        joined_slot = Slot(
                            start=last_slot.start,
                            end=next_slot.end,
                            date_start=last_slot.date_start,
                            date_end=next_slot.date_end,
                            day_status=last_slot.day_status,
                        )
                        groups[Group(group_id)] = groups[Group(group_id)][:-1]
                        slots = [joined_slot, *day_slots[1:]]

                groups[Group(group_id)].extend(slots)

        return dict(groups)


yasno_client = YasnoBlackout()


def yasno_predict_on_time(
    now_ts: int,
    region_id: int,
    dso_id: int,
    group_str: str,
) -> Optional[tuple[datetime, DayStatus]]:
    """
    На основе оф. графика YASNO возвращает:
      (ориентировочное_время_включения_или_зміни, статус_дня)

    Если сейчас не в запланированном/екстренном окне – вернёт None.
    """
    try:
        outages = yasno_client.planned_outages(region_id=region_id, dso_id=dso_id)
    except Exception:
        # тут можно залогировать, но не валиться
        return None

    if not outages:
        return None

    try:
        group_enum = Group(group_str)
    except Exception:
        return None

    slots = outages.get(group_enum) or []
    if not slots:
        return None

    now_dt = datetime.fromtimestamp(now_ts)  # локальний час

    for slot in slots:
        start = slot.dt_start.replace(tzinfo=None)
        end = slot.dt_end.replace(tzinfo=None)
        if start <= now_dt < end:
            return end, slot.day_status

    return None


# ---------- УНИВЕРСАЛЬНЫЙ ХЕЛПЕР НА ЛЮБОЙ ДЕНЬ ----------

def yasno_slots_for_day(
    now_ts: int,
    region_id: int,
    dso_id: int,
    group_str: str,
    day_offset: int,
) -> list[Slot]:
    """
    Возвращает слоты для группы на день с заданным сдвигом:
      day_offset = 0 -> сьогодні
      day_offset = 1 -> завтра
      day_offset = 2 -> післязавтра и т.д.
    """
    try:
        outages = yasno_client.planned_outages(region_id=region_id, dso_id=dso_id)
        group_enum = Group(group_str)
    except Exception:
        return []

    slots = outages.get(group_enum) or []
    if not slots:
        return []

    base_date = datetime.fromtimestamp(now_ts).date()
    target_date = base_date + timedelta(days=day_offset)

    # В графіку кожен слот прив'язаний до конкретної дати,
    # тож просто фільтруємо по даті початку.
    day_slots = [s for s in slots if s.dt_start.date() == target_date]

    # На всякий случай отсортируем по времени.
    day_slots.sort(key=lambda s: s.dt_start)
    return day_slots


def yasno_today_slots(
    now_ts: int,
    region_id: int,
    dso_id: int,
    group_str: str,
) -> list[Slot]:
    """
    Возвращает список Slot для СЕГОДНЯ по указанной группе.
    Если для группы нет данных — вернёт [].
    """
    return yasno_slots_for_day(
        now_ts=now_ts,
        region_id=region_id,
        dso_id=dso_id,
        group_str=group_str,
        day_offset=0,
    )


def yasno_tomorrow_slots(
    now_ts: int,
    region_id: int,
    dso_id: int,
    group_str: str,
) -> list[Slot]:
    """
    Возвращает список Slot на ЗАВТРА по указанной группе.
    Якщо для групи немає даних — поверне [].
    """
    return yasno_slots_for_day(
        now_ts=now_ts,
        region_id=region_id,
        dso_id=dso_id,
        group_str=group_str,
        day_offset=1,
    )
