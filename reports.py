import os
from datetime import datetime

import pandas as pd
from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select, text

from db import User, engine, get_session


async def send_daily_reports(bot: Bot):
    with get_session() as session:
        admins = session.scalars(select(User.tg_id).where(User.role == "manager", User.tg_id.is_not(None))).all()
        if not admins:
            return

    today = datetime.now().strftime("%Y-%m-%d")
    df = pd.read_sql_query(
        text(
            '''SELECT r.name as Ресторан,
                      u.full_name as ФИО,
                      u.office as Офис,
                      o.items_json as Блюда,
                      o.total_price as Сумма
               FROM orders o
               JOIN users u ON o.user_id = u.id
               JOIN restaurants r ON o.restaurant_id = r.id
               WHERE o.order_date = :today'''
        ),
        engine,
        params={"today": today},
    )

    if df.empty:
        for admin in admins:
            await bot.send_message(admin, f"📅 Отчет за {today}: Заказов нет.")
        return

    for rest_name in df['Ресторан'].unique():
        rest_df = df[df['Ресторан'] == rest_name]
        total_sum = rest_df['Сумма'].sum()

        filename = f"Заказ_{rest_name}_{today}.xlsx"
        rest_df.to_excel(filename, index=False)

        caption = f"📄 Заказ для **{rest_name}** на {today}.\nИтого сумма: {total_sum} руб."
        for admin in admins:
            file = FSInputFile(filename)
            await bot.send_document(admin, file, caption=caption, parse_mode="Markdown")
        os.remove(filename)
