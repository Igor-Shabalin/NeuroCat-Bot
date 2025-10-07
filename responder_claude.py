#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sqlite3
import base64
import anthropic

from config import (
    USER_DAILY_LIMIT,
    BOT_DAILY_LIMIT,
    ANTHROPIC_API_KEY,
    OWNER_ID,
    SYSTEM_USER_IDS,
    TRUSTED_CHANNELS,
    get_current_time,
)

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

DB_PATH = os.path.join(os.getcwd(), "group_history.db")
PROMPT_PATH = os.path.join("data", "claude_prompt.txt")

# 🔹 Карта ярлыков interest.py → реальные модели Anthropic
MODEL_MAP = {
    "FUN": "claude-3-5-haiku-20241022",
    "SMART": "claude-sonnet-4-5-20250929",
}

# fallback для старой логики
MODEL_MAIN = "claude-sonnet-4-20250514"
MODEL_FALLBACK = "claude-3-5-haiku-20241022"


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def user_daily_count(user_id, chat_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM history
        WHERE chat_id = ?
          AND role = 'assistant'
          AND date(created) = date('now')
          AND reply_to_user_id = ?
        """,
        (chat_id, user_id),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def get_total_daily_count():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM history
        WHERE role = 'assistant'
          AND date(created) = date('now')
        """
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def load_system_prompt():
    with open(PROMPT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def get_chat_history(chat_id, limit=15):
    """Берём последние сообщения чата для контекста (до 15)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT role, first_name, content, is_interesting, source
        FROM history
        WHERE chat_id = ?
        ORDER BY created DESC
        LIMIT ?
        """,
        (chat_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()

    history = []
    for role, name, content, is_interesting, source in reversed(rows):
        if not content:
            continue

        if is_interesting == 1:
            interest_text = "(✨ помечено как интересное)"
        elif is_interesting == 0:
            interest_text = "(😴 помечено как неинтересное)"
        else:
            interest_text = "(без оценки)"

        if role == "assistant":
            history.append({"role": "assistant", "content": content})
        else:
            history.append({
                "role": "user",
                "content": f"{name}: {content} {interest_text}"
            })

    return history


def is_exempt_from_limits(user_id, msg=None):
    if not user_id:
        return False
    if user_id in SYSTEM_USER_IDS:
        return True
    if user_id == 136817688 and msg and msg.sender_chat:
        return msg.sender_chat.id in TRUSTED_CHANNELS
    return False


def choose_model(image_path=None):
    if image_path:
        return MODEL_MAIN
    return MODEL_FALLBACK


def encode_image(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def generate_response(
    chat_id,
    current_user=None,
    user_id=None,
    text=None,
    image_path=None,
    msg=None,
    web_summary=None,
    forced_model=None
):
    # --- лимиты ---
    if user_id and not is_exempt_from_limits(user_id, msg) and user_id != OWNER_ID:
        if user_daily_count(user_id, chat_id) >= USER_DAILY_LIMIT:
            print(f"⛔ Лимит {USER_DAILY_LIMIT} ответов/сутки для user_id={user_id}")
            return None

    # --- системный промпт ---
    system_prompt = load_system_prompt()
    system_prompt = (
        f"{system_prompt}\n\n"
        f"⚡️ Сейчас {get_current_time()} (локальное время НейроКота).\n\n"
        "‼️ ВАЖНО: всегда отвечай именно на последнее сообщение в истории. "
        "Предыдущие реплики учитывай только как фон."
    )

    history = get_chat_history(chat_id)

    # 🔹 web_summary всегда идёт отдельным блоком
    if web_summary:
        system_prompt += (
            "\n\n📌 ВНИМАНИЕ: Ниже приведены результаты веб-поиска по запросу пользователя. "
            "Это уже готовая информация из интернета, используй её для ответа. "
            "Не говори, что у тебя нет доступа к сети.\n"
            f"{web_summary.strip()}"
        )

    # 📷 если фото
    if image_path:
        base64_img = encode_image(image_path)
        user_content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg", "data": base64_img},
            }
        ]
        if text:
            user_content.append({"type": "text", "text": f"‼️ Вот последнее сообщение, на которое нужно ответить: {text}"})
        else:
            user_content.append({"type": "text", "text": f"‼️ Вот последнее сообщение, на которое нужно ответить: [Фото]"})
        history.append({"role": "user", "content": user_content})
    else:
        if current_user and text:
            history.append({
                "role": "user",
                "content": f"‼️ Вот последнее сообщение, на которое нужно ответить: {current_user}: {text}"
            })

    # --- выбор модели ---
    if forced_model and forced_model in MODEL_MAP:
        model = MODEL_MAP[forced_model]
    else:
        model = choose_model(image_path)

    try:
        print("=== PROMPT TO CLAUDE ===")
        print("SYSTEM:", system_prompt[:400], "...\n")
        for h in history[-10:]:
            print(f"{h['role'].upper()}: {str(h['content'])[:200]} ...")

        response = client.messages.create(
            model=model,
            max_tokens=800,
            temperature=0.7,
            system=system_prompt,
            messages=history,
        )
        answer = "".join([block.text for block in response.content if block.type == "text"]).strip()
        print(f"=== RAW CLAUDE RESPONSE ({model}) ===\n{answer}\n")
        return answer
    except Exception as e:
        print(f"❌ Ошибка при вызове Claude API: {e}")
        return None

