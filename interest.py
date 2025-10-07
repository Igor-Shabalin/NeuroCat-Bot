#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sqlite3
import json
import asyncio
from openai import AsyncOpenAI
from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_ID, OPENAI_API_KEY, get_current_time

# Подключение OpenAI
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

DB_PATH = os.path.join(os.getcwd(), "group_history.db")
PROMPT_FILE = os.path.join("data", "interest_prompt.txt")

# ✅ Разрешённые реакции (Telegram)
ALLOWED_REACTIONS = ["👍","👎","❤️","🔥","🥰","😁","🤔","😢","😱","🤬","🎉","🙏"]


def load_prompt():
    with open(PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read()


def get_db_connection():
    return sqlite3.connect(DB_PATH)


def get_recent_messages(chat_id: int, limit: int = 3):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT user_id, role, content, created
        FROM history
        WHERE chat_id = ?
        ORDER BY created DESC
        LIMIT ?
    """, (chat_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows[::-1]


def _is_channel_message(msg) -> bool:
    """Определяем, что сообщение связано с каналом (написано от имени канала или переслано)."""
    try:
        if getattr(msg, "is_automatic_forward", False):
            return True
        if getattr(msg, "forward_origin", None) and getattr(msg.forward_origin, "chat", None):
            return True
        if getattr(msg, "forward_from_chat", None):
            return True
        if getattr(msg, "sender_chat", None):
            sc = msg.sender_chat
            if sc and getattr(sc, "type", None) == "channel":
                return True
    except Exception:
        pass
    return False


def _strip_photo_prefix(text: str) -> str:
    return re.sub(r"^📷\s*Фото\.\s*Подпись:\s*", "", text or "", flags=re.IGNORECASE).strip()


def _pick_model_heuristic(text: str) -> str:
    """
    Эвристика выбора модели по стилю/сложности.
    Возвращает "FUN" или "SMART".
    Используется ТОЛЬКО как fallback, если GPT не вернул MODEL или JSON сломан.
    """
    if not text:
        return "FUN"

    t = _strip_photo_prefix(text)
    low = t.lower()

    humour_markers = ["))", ")))", "😂", "🤣", "😅", "ахах", "лол", "кек", "шутк", "дурач"]
    if any(m in low for m in humour_markers):
        return "FUN"

    words = re.findall(r"\w+", low, flags=re.UNICODE)
    if len(words) <= 6:
        return "FUN"

    complex_kw = [
        "почему", "как работает", "объясни", "докаж", "теория", "алгоритм", "архитектур",
        "оптимизац", "регресс", "градиент", "инференс", "обучен", "распознава", "генерац",
        "nlp", "llm", "байес", "энтроп", "корреляц", "каузаль", "причин", "следств",
        "сравни", "оцен", "план", "стратег", "дизайн", "proof", "theorem", "complexit",
        "np-", "p=", "асимптот", "математ"
    ]
    has_complex_kw = any(k in low for k in complex_kw)
    has_question = "?" in t

    if len(words) > 20 and (has_complex_kw or has_question):
        return "SMART"

    code_markers = ["```", "def ", "class ", "SELECT ", "INSERT ", "http://", "https://"]
    if any(m in t for m in code_markers):
        return "SMART"

    return "FUN"


async def analyze_message(message_text: str, chat_id: int = None, msg=None):
    """
    Анализирует сообщение: INTEREST, REACTION, SEARCH, QUERY, MODEL
    GPT — главный источник решения; эвристика применяется только как fallback.
    """
    channel_hint = bool(msg and _is_channel_message(msg))

    system_prompt = load_prompt()
    system_prompt = f"{system_prompt}\n\n⚡️ Сейчас {get_current_time()} (локальное время НейроКота)."

    history_text = ""
    if chat_id:
        history = get_recent_messages(chat_id, limit=3)
        history_text = "\n".join([f"[{row[3]}] user_id={row[0]} role={row[1]}: {row[2]}" for row in history])

    resp = await client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0,
        messages=[
            {"role":"system","content":system_prompt},
            {"role":"system","content":f"История последних сообщений:\n{history_text}"},
            {"role":"user","content":message_text},
        ]
    )

    raw = resp.choices[0].message.content.strip()
    if os.environ.get("SHOW_RAW", "").strip() == "1":
        print("\n🔎 RAW GPT ANSWER:", raw)

    # Значения по умолчанию
    result = {"INTEREST":"NO","REACTION":["🤔"],"SEARCH":"NO","QUERY":"","MODEL":"FUN"}

    # Снимаем возможную Markdown-обёртку
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()

    parsed = None
    try:
        parsed = json.loads(clean)
        if isinstance(parsed, dict):
            # ✅ доверяем GPT, только чуть приводим к норме
            reactions = parsed.get("REACTION", [])
            clean_reactions = [r for r in reactions if r in ALLOWED_REACTIONS] or ["🤔"]
            parsed["REACTION"] = clean_reactions[:1]

            if parsed.get("SEARCH") == "YES" and not parsed.get("QUERY"):
                parsed["QUERY"] = _strip_photo_prefix(message_text)

            # Если модель отсутствует или некорректна — решим эвристикой
            if parsed.get("MODEL") not in ("SMART", "FUN"):
                parsed["MODEL"] = _pick_model_heuristic(message_text or "")

            result.update(parsed)
        else:
            # не словарь → fallback
            result["MODEL"] = _pick_model_heuristic(message_text or "")
    except Exception as e:
        print(f"⚠️ Ошибка парсинга JSON: {e}")
        # полностью fallback
        result["MODEL"] = _pick_model_heuristic(message_text or "")

    if channel_hint:
        result["INTEREST"] = "YES"

    return result


def format_author_info(msg):
    if msg and msg.sender_chat:
        title = msg.sender_chat.title or "Без названия"
        cid = msg.sender_chat.id
        uname = f"@{msg.sender_chat.username}" if msg.sender_chat.username else "@None"
        return f"Канал: {title} ({uname}, ID: {cid})"
    elif msg and msg.from_user:
        name = msg.from_user.first_name or "?"
        uname = f"@{msg.from_user.username}" if msg.from_user.username else "@None"
        return f"Пользователь: {name} ({uname}, ID: {msg.from_user.id})"
    else:
        return "❓ Неизвестный отправитель"


async def report_interest(update: Update, context: ContextTypes.DEFAULT_TYPE, result: dict):
    """Шлёт админу отчёт о проверке интересности + сохраняет оценку в БД."""
    msg = update.message
    if not msg:
        return

    chat_id = msg.chat.id
    message_id = msg.message_id
    text = msg.text or msg.caption or "[без текста]"

    interesting = (result.get("INTEREST") == "YES")
    reactions = result.get("REACTION", [])

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE history
        SET is_interesting = ?, reaction = ?
        WHERE chat_id = ? AND message_id = ?
    """, (1 if interesting else 0, ",".join(reactions), chat_id, message_id))
    conn.commit()
    conn.close()

    status = "✨ ИНТЕРЕСНОЕ" if interesting else "😴 НЕИНТЕРЕСНОЕ"
    preview = text if len(text) <= 400 else text[:400] + "…"
    msg_info = (
        f"{status} сообщение в группе {chat_id}\n"
        f"Отправитель: {format_author_info(msg)}\n\n"
        f"Текст: {preview}\n"
        f"🟢 Реакция: {reactions}\n"
        f"🌍 Поиск: {result.get('SEARCH')} | Запрос: {result.get('QUERY') or '—'}\n"
        f"🤖 Модель: {result.get('MODEL')}"
    )

    if not interesting:
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=msg_info)
        except Exception as e:
            print(f"⚠️ Ошибка при отправке отчёта админу: {e}")


# ==============================
# 🚀 Тестовый режим с МНОГОСТРОЧНЫМ вводом
# ==============================
def _read_multiline() -> str:
    """
    Читает многострочное сообщение из stdin.
    Завершение:
      • ДВЕ пустые строки подряд, или
      • строка 'END' / 'EOF', или
      • EOF (Ctrl+D/Ctrl+Z).
    Пустые строки внутри текста допускаются.
    """
    print(
        "\n(вводи текст, завершить: две пустые строки подряд, или строка END/EOF, или Ctrl+D)\n"
    )
    lines = []
    empty_streak = 0
    try:
        while True:
            line = input()
            if line in ("END", "EOF"):
                break
            if line == "":
                empty_streak += 1
                if empty_streak >= 2:
                    break
                # одиночная пустая строка — это абзац внутри текста
                lines.append("")
                continue
            empty_streak = 0
            lines.append(line)
    except EOFError:
        pass
    # убираем завершающие пустые строки
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines).strip()


if __name__ == "__main__":
    async def main():
        print("😼 Тестовый режим НейроКота. Напиши сообщение (или 'exit' одной строкой, чтобы выйти).")
        while True:
            head = input("\n💬 Начни ввод (пусто = начать многострочный режим, 'exit' = выйти): ").strip()
            if head.lower() == "exit":
                print("🐾 Выход.")
                break
            if head == "":
                text = _read_multiline()
            else:
                text = head

            if not text:
                # ничего не ввели — снова приглашаем
                continue

            result = await analyze_message(text)
            print("\n✨ РЕЗУЛЬТАТ АНАЛИЗА:")
            print(json.dumps(result, ensure_ascii=False, indent=2))

    asyncio.run(main())
