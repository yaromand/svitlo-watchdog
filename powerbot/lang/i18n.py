import json
import os
from pathlib import Path
import threading
from typing import Dict, Optional

from powerbot.storage.chat import get_chat_lang

BASE_LANG = "uk"

_LANG_CACHE: Dict[str, Dict[str, str]] = {}
_LANG_LOCK = threading.Lock()

# Список языков + имена (как раньше)
SUPPORTED_LANGS = {
    "uk": {"uk": "Українська", "en": "Ukrainian"},
    "en": {"uk": "Англійська", "en": "English"},
}


def get_lang_name(lang_code: str, ui_lang: str) -> str:
    info = SUPPORTED_LANGS.get(lang_code)
    if not info:
        return lang_code
    return info.get(ui_lang, info.get("en", lang_code))


def _get_lang_dir() -> Path:
    """
    Определяем директорию с JSON-файлами локализаций.

    Приоритет:
    1) ENV LANG_DIR
    2) <project_root>/lang, где project_root — родитель папки powerbot
       (т.е. там, где лежит app.py, lang/, templates/).
    """
    env_dir = os.getenv("LANG_DIR")
    if env_dir:
        return Path(env_dir)

    this_file = Path(__file__).resolve()
    project_root = this_file.parent.parent  # powerbot -> project root
    return project_root / "lang"


def _load_lang(lang: str) -> Dict[str, str]:
    if lang in _LANG_CACHE:
        return _LANG_CACHE[lang]

    with _LANG_LOCK:
        if lang in _LANG_CACHE:
            return _LANG_CACHE[lang]

        lang_dir = _get_lang_dir()
        path = lang_dir / f"{lang}.json"

        if not path.exists():
            # если нет конкретного языка — падаем на BASE_LANG
            if lang != BASE_LANG:
                return _load_lang(BASE_LANG)
            _LANG_CACHE[lang] = {}
            return _LANG_CACHE[lang]

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        _LANG_CACHE[lang] = data
        return data


def t(key: str, lang: str = BASE_LANG, **kwargs) -> str:
    translations = _load_lang(lang)
    template = translations.get(key)

    if template is None and lang != BASE_LANG:
        translations = _load_lang(BASE_LANG)
        template = translations.get(key, key)
    elif template is None:
        template = key

    try:
        return template.format(**kwargs)
    except Exception:
        return template


def get_lang_from_update(update) -> str:
    user = getattr(update, "effective_user", None)
    code = getattr(user, "language_code", None) if user else None
    if not code:
        return BASE_LANG

    short = code.split("-")[0].lower()
    if short in ("uk", "ua"):
        return "uk"
    if short == "en":
        return "en"

    # прочие (ru, ...) — дефолтом украинский
    return BASE_LANG

def get_lang_for_chat(chat_id: int, thread_id: Optional[int]) -> str:
    """
    Определяем язык для конкретного чата/гілки.
    Если в chat_settings нет ничего — по умолчанию 'uk'.
    """
    lang = get_chat_lang(chat_id, thread_id)
    return lang or "uk"