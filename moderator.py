#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from insult_detect import insult_detect, load_prompt
from config import OWNER_ID

TRUSTED_FILE = os.path.join("data", "trusted_users.json")
PROMPT_FILE = os.path.join("data", "moderation_prompt.txt")


# ------------------ доверенные пользователи ------------------

def load_trusted_users():
    if not os.path.exists(TRUSTED_FILE):
        return {"users": [], "chats": [], "usernames": []}
    with open(TRUSTED_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_trusted_users(data):
    try:
        with open(TRUSTED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения trusted.json: {e}")
        return False


# ------------------ модерация ------------------

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверка сообщения на спам/оскорбления. Возвращает True если оставить, False если удалить."""

    chat_id = update.message.chat.id
    message_id = update.message.message_id
    sender = update.message.from_user
    sender_id = sender.id if sender else None
    sender_name = sender.first_name if sender else "?"
    sender_username = f"@{sender.username}" if sender and sender.username else "@None"

    trusted = load_trusted_users()

    # --- доверенные пользователи/чаты ---
    if (
        sender_id in trusted["users"]
        or sender_username in trusted["usernames"]
        or (update.message.sender_chat and update.message.sender_chat.id in trusted["chats"])
    ):
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                f"Сообщение в группе НЕ проверяется "
                f"(от доверенного источника ID {sender_id or update.message.sender_chat.id})"
            ),
        )
        return True

    # --- вложения (фото/документы) ---
    if update.message.photo or update.message.document:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    f"🚫 Фото/документ в группе {chat_id}\n"
                    f"От: {sender_name} ({sender_username}, ID: {sender_id})\n"
                    f"Статус: УДАЛЕНО ✅"
                ),
            )
            return False
        except Exception as e:
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"❌ Ошибка удаления фото/документа: {e}",
            )
            return False

    # --- проверка текста ---
    text = update.message.text or ""
    gpt_prompt = load_prompt(PROMPT_FILE)
    is_bad = insult_detect(text, gpt_prompt) if text else False

    if is_bad:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            msg_info = (
                f"🚫 ТОКСИЧНОЕ сообщение в группе\n"
                f"Группа: {chat_id}\n"
                f"Отправитель: {sender_name} ({sender_username}, ID: {sender_id})\n"
                f"Текст: {text[:500] if text else '[без текста]'}\n"
                f"Статус: УДАЛЕНО ✅"
            )
        except Exception as e:
            msg_info = f"❌ Ошибка удаления сообщения: {e}"
    else:
        msg_info = (
            f"✅ НОРМАЛЬНОЕ сообщение в группе\n"
            f"Группа: {chat_id}\n"
            f"Отправитель: {sender_name} ({sender_username}, ID: {sender_id})\n"
            f"Текст: {text[:500] if text else '[без текста]'}\n"
            f"Статус: ОСТАВЛЕНО 👍\n\n"
            f"💡 Чтобы добавить в доверенные:\n/add_user {sender_id}"
        )

    # --- отчёт админу ---
    try:
        await context.bot.send_message(chat_id=OWNER_ID, text=msg_info)
    except Exception as e:
        print(f"⚠️ Ошибка при отправке отчёта админу: {e}")

    return not is_bad


# ------------------ команды ------------------

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления пользователя в доверенные"""
    if update.message.chat.id != OWNER_ID:
        return

    args = context.args
    if not args:
        await update.message.reply_text("Использование: /add_user <ID>")
        return

    trusted = load_trusted_users()
    try:
        user_id = int(args[0])
        if user_id not in trusted["users"]:
            trusted["users"].append(user_id)
            if save_trusted_users(trusted):
                await update.message.reply_text(f"✅ Пользователь {user_id} добавлен в доверенные")
            else:
                await update.message.reply_text("❌ Ошибка сохранения")
        else:
            await update.message.reply_text(f"ℹ️ Пользователь {user_id} уже в доверенных")
    except ValueError:
        await update.message.reply_text("❌ ID должен быть числом")


def register_moderator_handlers(app):
    app.add_handler(CommandHandler("add_user", add_user))

