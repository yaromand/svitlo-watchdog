import logging

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler


async def ack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обработчик нажатия на кнопку "✅ Прочитано".
    В приватных чатах удаляет сообщение бота.
    """
    query = update.callback_query
    if not query:
        return

    msg = query.message
    if not msg:
        await query.answer()
        return

    chat = msg.chat
    chat_type = getattr(chat, "type", None)

    # Только приватные чаты
    if chat_type != "private":
        await query.answer()
        return

    try:
        await query.answer()
        await context.bot.delete_message(
            chat_id=chat.id,
            message_id=msg.message_id,
        )
    except Exception as e:
        logging.warning("Не вдалося видалити повідомлення по ack: %s", e)
