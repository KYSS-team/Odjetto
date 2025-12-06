import os
from datetime import datetime

import pandas as pd
from aiogram import Bot
from aiogram.types import FSInputFile

from db import get_db


async def send_daily_reports(bot: Bot):
    with get_db() as conn:
        admin = conn.execute("SELECT tg_id FROM users WHERE role='manager' LIMIT 1").fetchone()
        if not admin:
            return

        today = datetime.now().strftime("%Y-%m-%d")
        df = pd.read_sql_query(
            '''SELECT r.name as Ресторан,
                      u.full_name as ФИО,
                      u.office as Офис,
                      o.items_json as Блюда,
                      o.total_price as Сумма
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN restaurants r ON o.restaurant_id = r.id
               WHERE o.order_date = ?''',
            conn,
            params=(today,),
        )

    if df.empty:
        await bot.send_message(admin[0], f"📅 Отчет за {today}: Заказов нет.")
        return

    for rest_name in df['Ресторан'].unique():
        rest_df = df[df['Ресторан'] == rest_name]
        total_sum = rest_df['Сумма'].sum()

        filename = f"Заказ_{rest_name}_{today}.xlsx"
        rest_df.to_excel(filename, index=False)

        caption = f"📄 Заказ для **{rest_name}** на {today}.\nИтого сумма: {total_sum} руб."
        file = FSInputFile(filename)
        await bot.send_document(admin[0], file, caption=caption, parse_mode="Markdown")
        os.remove(filename)
