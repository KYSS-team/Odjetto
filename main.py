import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, REPORT_TIME
from db import init_db
from handlers_auth import router as auth_router
from handlers_manager import router as manager_router
from handlers_orders import router as orders_router
from reports import send_daily_reports

logging.basicConfig(level=logging.INFO)


async def main():
    init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(auth_router)
    dp.include_router(manager_router)
    dp.include_router(orders_router)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_daily_reports, "cron", hour=REPORT_TIME.hour, minute=REPORT_TIME.minute, args=[bot])
    scheduler.start()

    print(f"Bot started! Reports scheduled at {REPORT_TIME.hour}:{REPORT_TIME.minute:02d}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
