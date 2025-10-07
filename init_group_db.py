#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sqlite3
import os

DB_PATH = os.path.join(os.getcwd(), "group_history.db")


def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица истории сообщений
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            first_name TEXT,
            role TEXT,
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            content TEXT,
            reply_to_user_id INTEGER,
            reaction TEXT,
            is_interesting INTEGER DEFAULT NULL,
            source TEXT DEFAULT 'chat'
        )
    """)

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована:", DB_PATH)


if __name__ == "__main__":
    init_db()
