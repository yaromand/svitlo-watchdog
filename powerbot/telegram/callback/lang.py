import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

from powerbot.lang.i18n import SUPPORTED_LANGS, get_lang_name, t
from powerbot.storage.chat import set_chat_lang


async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработка нажатий на инлайн-кнопки выбора языка.
    callback_data вида: "lang:uk", "lang:en"
    """
    query = update.callback_query
    if not query or not query.data:
        return

    data = query.data
    if not data.startswith("lang:"):
        return

    code = data.split(":", 1)[1].lower()
    if code not in SUPPORTED_LANGS:
        await query.answer("Unknown language", show_alert=True)
        return

    message = query.message
    if not message:
        await query.answer()
        return

    chat = message.chat
    chat_id = chat.id
    thread_id = getattr(message, "message_thread_id", None)

    # Сохраняем язык для этого чата/ветки
    set_chat_lang(chat_id, thread_id, code)

    # Для текста используем уже выбранный язык
    ui_lang = code
    name = get_lang_name(code, ui_lang)

    text = t(
        "lang.updated",
        lang=ui_lang,
        lang_name=name,
        lang_code=code,
    )

    await query.answer()
    try:
        await query.edit_message_text(text=text)
    except Exception:
        # если редактировать не удалось — шлём новое сообщение
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            message_thread_id=thread_id,
        )

