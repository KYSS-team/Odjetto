import os
from datetime import time

BOT_TOKEN = os.getenv("BOT_TOKEN", "8568838231:AAGKoCcI7HbuifkKdhwroizMlDhRe1bGbW0")
DB_NAME = os.getenv("DB_NAME", "lunch_mvp.db")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
DEFAULT_LIMIT = int(os.getenv("DEFAULT_LIMIT", 400))
REPORT_TIME = time(hour=int(os.getenv("REPORT_HOUR", 12)), minute=int(os.getenv("REPORT_MINUTE", 0)))
ORDER_DEADLINE_HOUR = int(os.getenv("ORDER_DEADLINE_HOUR", 12))

# В одном месте держим сообщения-заглушки для платежей
PAYMENT_PLACEHOLDER_MESSAGE = (
    "💳 Для оплаты используйте корпоративный канал. После подтверждения нажмите \"Подтвердить оплату\"."
)
REFUND_PLACEHOLDER_MESSAGE = "Возврат {amount} руб. за переплату оформлен на ваш баланс."
