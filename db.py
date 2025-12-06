import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DB_NAME, DEFAULT_LIMIT


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id INTEGER UNIQUE,
                full_name TEXT,
                office TEXT,
                role TEXT DEFAULT 'employee',
                balance INTEGER DEFAULT 0,
                auth_token TEXT
            )'''
        )

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS restaurants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                is_active BOOLEAN DEFAULT 1
            )'''
        )

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS menu (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                restaurant_id INTEGER,
                name TEXT,
                description TEXT,
                price INTEGER,
                FOREIGN KEY (restaurant_id) REFERENCES restaurants(id) ON DELETE CASCADE
            )'''
        )

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                restaurant_id INTEGER,
                order_date TEXT,
                items_json TEXT,
                total_price INTEGER,
                paid_extra INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE (user_id, order_date)
            )'''
        )

        cursor.execute(
            '''CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )'''
        )
        cursor.execute(
            "INSERT OR IGNORE INTO config (key, value) VALUES ('daily_limit', ?)", (str(DEFAULT_LIMIT),)
        )
        conn.commit()


def get_limit() -> int:
    with get_db() as conn:
        val = conn.execute("SELECT value FROM config WHERE key='daily_limit'").fetchone()[0]
    return int(val)


def set_limit(value: int) -> None:
    with get_db() as conn:
        conn.execute("UPDATE config SET value = ? WHERE key='daily_limit'", (value,))
        conn.commit()


def upsert_user(tg_id: int, full_name: str, role: str = "employee"):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users (tg_id, full_name, role) VALUES (?, ?, ?)", (tg_id, full_name, role)
        )
        conn.commit()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
