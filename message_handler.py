#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
import sqlite3
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes

from moderator import moderate_message
from photo_responder import analyze_photo
from responder_claude import generate_response
from prompt_updater import check_and_update_prompt
from config import ALLOWED_GROUPS, OWNER_ID
from interest import analyze_message, report_interest
from web_search import search_and_summarize
import pprint

DB_PATH = os.path.join(os.getcwd(), "group_history.db")
PHOTO_DIR = os.path.join(os.getcwd(), "channel_pics")


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def save_message(
    chat_id,
    message_id,
    user_id,
    username,
    role,
    content,
    reply_to_user_id=None,
    source=None,
):
    """
    Сохраняем сообщение в БД (таблица history в group_history.db).
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO history (chat_id, message_id, user_id, first_name, role, created, content, reply_to_user_id, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                message_id,
                user_id,
                username,
                role,
                datetime.now(),
                content,
                reply_to_user_id,
                source,
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главная функция обработки входящих сообщений.
    """
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat_id
    if chat_id not in ALLOWED_GROUPS:
        return  # игнорируем чаты, которые не разрешены

    # --- 1. Проверка модерации ---
    is_ok = await moderate_message(update, context)
    if not is_ok:
        return

    # --- 2. Определяем отправителя ---
    user_id = msg.from_user.id if msg.from_user else None
    username = (
        msg.from_user.first_name
        if msg.from_user
        else (msg.sender_chat.title if msg.sender_chat else "anon")
    )

    # --- 3. Извлекаем текст и фото ---
    text = msg.text or msg.caption or ""
    image_path = None
    vision_description = None

    if msg.photo or msg.document:
        # Если это фото или документ → сохраняем
        os.makedirs(PHOTO_DIR, exist_ok=True)

        if msg.photo:
            file_obj = await msg.photo[-1].get_file()
            filename = os.path.join(PHOTO_DIR, f"{msg.message_id}.jpg")
        else:
            file_obj = await msg.document.get_file()
            ext = (
                os.path.splitext(msg.document.file_name)[-1]
                if msg.document.file_name
                else ".jpg"
            )
            filename = os.path.join(PHOTO_DIR, f"{msg.message_id}{ext}")

        await file_obj.download_to_drive(custom_path=filename)
        print(f"📷 Фото сохранено: {filename}")
        image_path = filename

        # Сохраняем текстовое описание фото в историю
        if text:
            user_content = f"📷 Фото + подпись: {text}"
        else:
            user_content = "📷 Пользователь прислал фото"
        save_message(chat_id, msg.message_id, user_id, username, "user", user_content)

        # Анализ фото (vision модель)
        vision_description = await asyncio.to_thread(analyze_photo, filename)
        if vision_description:
            vision_content = f"🔎 Анализ фото: {vision_description}"
            save_message(chat_id, msg.message_id, user_id, username, "vision", vision_content)

    else:
        # --- Обычный текст ---
        role = "user"
        if msg.from_user and msg.from_user.is_bot:
            if msg.from_user.id == context.bot.id:
                role = "assistant"
        save_message(chat_id, msg.message_id, user_id, username, role, text)

    # --- 4. Проверка апдейта промптов ---
    await check_and_update_prompt(context)

    if not text.strip() and not image_path:
        return  # пустое сообщение → игнор

    # --- 5. Анализ интересности ---
    if image_path:
        message_text = f"📷 Фото. Подпись: {text or 'без подписи'}"
    else:
        message_text = text

    result = await analyze_message(message_text, chat_id, msg=msg)

    # Отправляем отчёт админу и сохраняем в БД
    await report_interest(update, context, result)

    interesting = result.get("INTEREST") == "YES"

    # --- 6. Логика "реплай коту" ---
    # Раньше: бот ВСЕГДА отвечал, если это реплай к его сообщению.
    # Теперь: бот отвечает на реплай только если сообщение интересное.
    must_answer = (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.is_bot
        and interesting  # ключевое изменение
    )

    # --- 7. Если сообщение неинтересное и не реплай → игнорируем ---
    if not interesting and not must_answer:
        return

    # --- 8. Ставим реакцию (если есть) ---
    if result.get("REACTION"):
        try:
            reaction = result["REACTION"][0]  # только одна реакция
            await context.bot.set_message_reaction(
                chat_id=chat_id,
                message_id=msg.message_id,
                reaction=reaction,
            )
            print(f"✅ Реакция установлена: {reaction}")
        except Exception as e:
            print(f"❌ Ошибка при установке реакции: {e}")

    # --- 9. Веб-поиск (если нужен) ---
    web_summary = None
    if result.get("SEARCH") == "YES":
        query = result.get("QUERY") or text
        print(f"🌍 Выполняем веб-поиск: {query}")
        try:
            web_summary, sources = await asyncio.wait_for(
                search_and_summarize(query, num_results=5),
                timeout=20,
            )

            # Лог результатов поиска
            print("=== WEB SUMMARY (debug) ===")
            print(web_summary)
            print("=== SOURCES (debug) ===")
            print(sources)

            if sources:
                web_summary += "\n\n🔗 Источники:\n" + "\n".join(f"- {s}" for s in sources[:5])

            # Сохраняем результат поиска как отдельный блок
            save_message(
                chat_id,
                msg.message_id,
                0,
                "Neurocat",
                "assistant",
                web_summary,
                source="web",
            )

        except asyncio.TimeoutError:
            print("⚠️ Поиск превысил лимит времени")
            web_summary = "⚠️ Источники не ответили вовремя."
        except Exception as e:
            print(f"❌ Ошибка веб-поиска: {e}")
            web_summary = None

    # --- 10. Отчёт админу ---
    try:
        report_lines = [
            "🔎 RAW GPT ANSWER:",
            f"{result}",
            "",
            "✨ РЕЗУЛЬТАТ АНАЛИЗА СООБЩЕНИЯ",
            f"Группа: {chat_id}",
            f"Отправитель: {username} (ID: {user_id})",
            f"Текст: {text or '[без текста]'}",
            f"Статус: {'РЕПЛАЙ КОТУ — ответ (если интересное) ✅' if must_answer else ('ИНТЕРЕСНО ✅' if interesting else 'НЕИНТЕРЕСНО ❌')}",
            f"🟢 Реакция: {result.get('REACTION')}",
            f"🌍 Поиск: {result.get('SEARCH')} | Запрос: {result.get('QUERY') or '—'}",
            f"🤖 Модель: {result.get('MODEL')}",
        ]

        if web_summary:
            report_lines.append("\n🌍 РЕЗУЛЬТАТ ПОИСКА:")
            report_lines.append(web_summary)

        report_text = "\n".join(report_lines)

        # Telegram ограничение = 4096 символов → режем по 3500
        MAX_LEN = 3500
        for i in range(0, len(report_text), MAX_LEN):
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=report_text[i:i+MAX_LEN]
            )

    except Exception as e:
        print(f"⚠️ Ошибка при отправке отчёта админу: {e}")

    # --- 11. Генерация ответа от Claude ---
    answer = generate_response(
        chat_id,
        current_user=username,
        user_id=user_id,
        text=text,
        image_path=image_path,
        msg=msg,
        web_summary=web_summary,
        forced_model=result.get("MODEL"),
    )
    if answer:
        await msg.reply_text(answer, reply_to_message_id=msg.message_id)

        # ✅ Сохраняем ответ кота в историю
        try:
            save_message(
                chat_id,
                msg.message_id,
                0,
                "Neurocat",
                "assistant",
                answer,
                reply_to_user_id=user_id,
                source="claude",
            )
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении ответа кота: {e}")
