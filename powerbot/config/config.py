import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _int_opt(name: str) -> Optional[int]:
    val = os.getenv(name)
    if val is None or val == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _int(name: str, default: int) -> int:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        return default

def _float(name: str, default: float) -> float:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    try:
        return float(val)
    except ValueError:
        return default


@dataclass
class Settings:
    # Telegram
    TELEGRAM_BOT_TOKEN: str
    ADMIN_CHAT_ID: Optional[int]

    # HTTP / Flask
    BIND_HOST: str
    WEB_PORT: int
    WEB_BASE_URL: str
    WEBHOOK_SECRET: str

    # TG rate-limit
    MAX_GLOBAL_MSG_PER_SEC: float
    MIN_PER_CHAT_INTERVAL: float
    SEND_WINDOW_SEC: float

    # YASNO
    YASNO_REGION_ID: Optional[int]
    YASNO_DSO_ID: Optional[int]
    YASNO_GROUP: Optional[str]
    YASNO_POLL_INTERVAL: int

    # Файловая структура
    PROJECT_ROOT: Path
    DATA_DIR: Path

    DB_FILE: Path
    STATE_FILE: Path
    YASNO_STATE_FILE: Path
    SUBSCRIBERS_FILE: Path


def load_settings() -> Settings:
    # /.../powerbot/config/settings.py -> проектный корень (где лежат app.py, lang/, templates/)
    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent.parent

    # DATA_DIR — базовая директория для всех файлов состояния
    data_dir_env = os.getenv("DATA_DIR")
    data_dir = Path(data_dir_env) if data_dir_env else project_root

    db_file = Path(os.getenv("DB_FILE") or (data_dir / "power_events.db"))
    state_file = Path(os.getenv("STATE_FILE") or (data_dir / "power_state.json"))
    yasno_state_file = Path(os.getenv("YASNO_STATE_FILE") or (data_dir / "yasno_state.json"))
    subscribers_file = Path(os.getenv("SUBSCRIBERS_FILE") or (data_dir / "subscribers.json"))

    return Settings(
        TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        ADMIN_CHAT_ID=_int_opt("ADMIN_CHAT_ID"),

        BIND_HOST=os.getenv("BIND_HOST", "0.0.0.0"),
        WEB_PORT=_int("WEB_PORT", 8080),
        WEB_BASE_URL=os.getenv("WEB_BASE_URL", "").rstrip("/"),
        WEBHOOK_SECRET=os.getenv("WEBHOOK_SECRET", "CHANGE_ME_SECRET"),

        MAX_GLOBAL_MSG_PER_SEC=_float("MAX_GLOBAL_MSG_PER_SEC", 25.0),
        MIN_PER_CHAT_INTERVAL=_float("MIN_PER_CHAT_INTERVAL", 1.0),
        SEND_WINDOW_SEC=_float("SEND_WINDOW_SEC", 1.0),


        YASNO_REGION_ID=_int_opt("YASNO_REGION_ID"),
        YASNO_DSO_ID=_int_opt("YASNO_DSO_ID"),
        YASNO_GROUP=os.getenv("YASNO_GROUP", None),
        YASNO_POLL_INTERVAL=_int("YASNO_POLL_INTERVAL", 900),

        PROJECT_ROOT=project_root,
        DATA_DIR=data_dir,

        DB_FILE=db_file,
        STATE_FILE=state_file,
        YASNO_STATE_FILE=yasno_state_file,
        SUBSCRIBERS_FILE=subscribers_file,
    )


settings = load_settings()
