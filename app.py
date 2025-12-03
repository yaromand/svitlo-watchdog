import logging
import threading

from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

from pathlib import Path
from dotenv import load_dotenv


# грузим .env из корня проекта (там же, где app.py)
load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

from powerbot.telegram.callback.ack import ack_callback
from powerbot.telegram.callback.lang import lang_callback

from powerbot.config.config import settings
from powerbot.storage.db import init_db
from powerbot.web.web import run_flask
from powerbot.yasno.watchdog.start import yasno_watchdog_worker
from powerbot.telegram.handlers.handlers import (
    cmd_start,
    cmd_stop,
    cmd_status,
    cmd_today,
    cmd_week,
    cmd_schedule,
    cmd_schedule_tomorrow,
    cmd_lang,
)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not settings.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Спочатку вкажи TELEGRAM_BOT_TOKEN в ENV.")

    init_db()

    logging.info("WEB_PORT=%s, WEB_BASE_URL=%s", settings.WEB_PORT, settings.WEB_BASE_URL)
    logging.info("WEBHOOK_SECRET length=%s", len(settings.WEBHOOK_SECRET))

    # Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logging.info("Flask веб-сервер запущений на %s:%s", settings.BIND_HOST, settings.WEB_PORT)

    # YASNO-watchdog в отдельном потоке
    yasno_thread = threading.Thread(target=yasno_watchdog_worker, daemon=True)
    yasno_thread.start()
    logging.info(
        "YASNO watchdog потік запущено з інтервалом %s сек",
        settings.YASNO_POLL_INTERVAL,
    )

    # Telegram-бот
    application = ApplicationBuilder().token(settings.TELEGRAM_BOT_TOKEN).concurrent_updates(True).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("week", cmd_week))
    application.add_handler(CommandHandler("schedule", cmd_schedule))
    application.add_handler(CommandHandler("tomorrow", cmd_schedule_tomorrow))
    application.add_handler(CommandHandler("lang", cmd_lang))
    application.add_handler(CallbackQueryHandler(lang_callback, pattern=r"^lang:"))
    application.add_handler(CallbackQueryHandler(ack_callback, pattern=r"^ack$"))
    logging.info("Telegram-бот запущений. Чекаємо /start та вебхуки.")
    application.run_polling()


if __name__ == "__main__":
    main()
