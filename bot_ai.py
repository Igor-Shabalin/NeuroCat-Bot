#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, CommandHandler, ContextTypes

from message_handler import handle_message
from prompt_updater import register_handlers
from moderator import register_moderator_handlers
from config import BOT_TOKEN, OWNER_ID, get_current_time


# 🔹 Логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# 🔇 Отключаем лишние логи от httpx и telegram
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)


def load_start_message():
    """Загружаем приветственный текст из файла"""
    with open("data/start_message.txt", "r", encoding="utf-8") as f:
        return f.read()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка команды /start"""
    user = update.effective_user
    chat = update.effective_chat

    # Текст для пользователя
    text = load_start_message()
    await update.message.reply_text(text)

    # Уведомление админу
    admin_msg = (
        f"🐾 Кто-то нажал /start\n"
        f"👤 Пользователь: {user.first_name} (@{user.username or 'None'}, ID: {user.id})\n"
        f"💬 Чат: {chat.title or 'ЛС с ботом'} (ID: {chat.id})\n"
        f"⏰ Время: {get_current_time()}"
    )
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=admin_msg)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение админу: {e}", exc_info=True)


async def safe_handle(update, context):
    """Обертка для обработки ошибок в handle_message"""
    try:
        await handle_message(update, context)
    except Exception as e:
        logger.error(f"Ошибка в handle_message: {e}", exc_info=True)


def main():
    # Создаем приложение с увеличенными таймаутами
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .read_timeout(60)    # максимум ожидания ответа от Telegram API
        .write_timeout(60)   # максимум времени на отправку
        .connect_timeout(30) # максимум на установку соединения
        .pool_timeout(30)    # ожидание свободного соединения
        .build()
    )

    # Регистрируем обработчики апдейтера промпта (inline-кнопки Да/Нет)
    register_handlers(app)
    register_moderator_handlers(app)

    # 🔹 Команда /start
    app.add_handler(CommandHandler("start", start))

    # Обработчик всех типов сообщений (текст, фото и т.д.)
    app.add_handler(MessageHandler(filters.ALL, safe_handle))

    print("🤖 Бот запущен, слушает группы...")
    app.run_polling()


if __name__ == "__main__":
    main()
