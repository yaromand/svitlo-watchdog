# svitlo-watchdog
├── app.py                      # точка входа
├── powerbot/
│   ├── __init__.py
│   ├── config.py               # все настройки/ENV
│   ├── constants.py            # константы типа DAY_NAMES_SHORT
│   ├── i18n.py                 # простая локализация (uk/en)
│   ├── domain/
│   │   ├── __init__.py
│   │   └── stats.py            # вся математика по событиям, плуралы
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py               # sqlite: init_db, log_power_event, load_all_events
│   │   ├── state_store.py      # load_state/save_state
│   │   ├── subscribers_store.py# подписчики (JSON)
│   │   └── yasno_cache.py      # кэш графика YASNO
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── telegram_client.py  # HTTP-клиент + rate-limit sendMessage
│   │   ├── web.py              # Flask-приложение и роуты
│   │   └── yasno_watchdog.py   # фоновый поток, следит за изменениями графика YASNO
│   ├── services/
│   │   ├── __init__.py
│   │   └── power_status.py     # apply_status_change: бизнес-логика смены статуса
│   ├── bot/
│   │   ├── __init__.py
│   │   └── handlers.py         # async-обработчики Telegram-команд
│   └── yasno/
│       ├── __init__.py
│       └── client.py           # твой текущий graphic.py, перенесён сюда
├── lang/
│   ├── uk.json                 # строки на украинском
│   └── en.json                 # строки на английском
└── templates/
    └── index.html              # твой текущий шаблон

