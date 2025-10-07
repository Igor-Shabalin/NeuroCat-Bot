#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import datetime

# 🔹 Часовой пояс (смещение в часах от времени сервера)
TIMEZONE_OFFSET = 0  # например, если сервер на час отстаёт → ставим +1

def get_current_time(fmt: str = "%d.%m.%Y %H:%M") -> str:
    """
    Возвращает локальное время бота (с учётом смещения).
    По умолчанию: '13.09.2025 09:45'
    """
    now = datetime.datetime.now() + datetime.timedelta(hours=TIMEZONE_OFFSET)
    return now.strftime(fmt)


"""
Конфиг для НейроКота 🐾
Все лимиты и параметры вынесены сюда, чтобы легко настраивать.
"""

# 🔑 API-ключи (заполни вручную или используй переменные окружения .env)
OPENAI_API_KEY = "your_openai_api_key_here"
ANTHROPIC_API_KEY = "your_anthropic_api_key_here"
BOT_TOKEN = "your_telegram_bot_token_here"

# 🔹 Лимиты сообщений
USER_DAILY_LIMIT = 30      # макс. ответов Кота одному пользователю в сутки
BOT_DAILY_LIMIT = 10       # макс. сообщений Кота в сутки (перед переключением модели)

# 🔹 Задержка ответа
MIN_DELAY = 1              # минимальная пауза перед ответом (сек)
MAX_DELAY = 2              # максимальная пауза (сек)

# 🔹 Разрешённые группы (укажи ID своих групп)
ALLOWED_GROUPS = [
    -1001234567890,
    -1002345678901,
]

# 🔹 ID владельца (для апдейта промпта и админ-команд)
OWNER_ID = 123456789

# 🔹 Системные пользователи Telegram (для них лимиты не считаем)
SYSTEM_USER_IDS = [
    777000,        # Telegram Service
    1087968824,    # GroupAnonymousBot (анонимные админы в группах)
]

# 🔹 Доверенные каналы (ChannelBot = 136817688 → проверяем sender_chat.id)
TRUSTED_CHANNELS = [
    -1001234567890,  # пример канала
    # сюда можно добавить свои
]

# 🔹 Основной канал (опционально)
CHANNEL_ID = -1001234567890
