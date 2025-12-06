from datetime import datetime

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ORDER_DEADLINE_HOUR, PAYMENT_PLACEHOLDER_MESSAGE, REFUND_PLACEHOLDER_MESSAGE
from db import get_db, get_limit, today_str
from keyboards import kb_employee
from states import OrderStates
from utils import available_dates, deadline_passed

router = Router()


def _order_summary(cart):
    return "\n".join([f"- {i['name']} ({i['price']}р)" for i in cart]) or "Корзина пуста"


@router.message(F.text == "👤 Мой профиль / Баланс")
async def e_profile(message: types.Message):
    with get_db() as conn:
        user = conn.execute("SELECT id, full_name, balance FROM users WHERE tg_id=?", (message.from_user.id,)).fetchone()
        today = today_str()
        current_limit = get_limit()
        order_today = conn.execute(
            "SELECT total_price FROM orders WHERE user_id=? AND order_date=?", (user["id"], today)
        ).fetchone()
        future_orders = conn.execute(
            '''SELECT o.order_date, r.name, o.total_price
               FROM orders o
               JOIN restaurants r ON o.restaurant_id = r.id
               WHERE user_id = ? AND order_date > ?
               ORDER BY order_date''',
            (user["id"], today),
        ).fetchall()

    if order_today:
        daily_status = f"✅ Заказ на сегодня ({order_today['total_price']} руб.) уже оформлен."
    elif datetime.now().hour >= ORDER_DEADLINE_HOUR:
        daily_status = f"❌ Заказ на сегодня уже недоступен (дедлайн {ORDER_DEADLINE_HOUR}:00)."
    else:
        daily_status = f"✅ Сегодня до {ORDER_DEADLINE_HOUR}:00 доступен лимит *{current_limit} руб.*"

    order_txt = "\n".join(
        [f"📅 {o['order_date']}: {o['name']} ({o['total_price']}р)" for o in future_orders]
    ) or "Нет заказов на будущее"

    await message.answer(
        f"👤 *{user['full_name']}*\n"
        f"💰 Личный Баланс (переплаты/возвраты): *{user['balance']} руб.*\n"
        f"--- Дневной лимит ({current_limit} руб.) ---\n"
        f"{daily_status}\n\n"
        f"📋 Заказы на будущее:\n{order_txt}",
        parse_mode="Markdown",
        reply_markup=kb_employee(),
    )


@router.message(F.text == "🍱 Сделать заказ")
async def e_order_start(message: types.Message, state: FSMContext):
    now = datetime.now()
    dates = available_dates(now)
    if not dates:
        await message.answer("На ближайшее время заказы закрыты.")
        return

    kb_rows = [[InlineKeyboardButton(text=label, callback_data=f"date_{value}")] for value, label in dates]
    await message.answer("Выберите дату доставки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.set_state(OrderStates.choose_date)


@router.callback_query(F.data.startswith("date_"))
async def e_date_sel(cb: types.CallbackQuery, state: FSMContext):
    date_str = cb.data.split("_")[1]
    now = datetime.now()
    if deadline_passed(date_str, now):
        await cb.answer("Дедлайн для этой даты истек", show_alert=True)
        return

    with get_db() as conn:
        user = conn.execute("SELECT id, balance FROM users WHERE tg_id=?", (cb.from_user.id,)).fetchone()
        if not user:
            await cb.message.answer("Учетная запись не найдена. Отправьте /start для входа.")
            await state.clear()
            await cb.answer()
            return
        existing = conn.execute(
            "SELECT id, paid_extra FROM orders WHERE user_id=? AND order_date=?",
            (user["id"], date_str),
        ).fetchone()
        rests = conn.execute("SELECT id, name FROM restaurants").fetchall()

    refund_potential = existing["paid_extra"] if existing else 0
    await state.update_data(
        date=date_str,
        user_db_id=user["id"],
        user_balance=user["balance"],
        existing_order_id=existing["id"] if existing else None,
        refund_potential=refund_potential,
        cart=[],
        cart_total=0,
    )

    msg_text = f"Заказ на {date_str}."
    if existing:
        msg_text += f"\n⚠️ У вас уже есть заказ. При изменении {refund_potential} руб. вернутся на баланс."

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=r["name"], callback_data=f"rest_{r['id']}")] for r in rests]
    )
    await cb.message.edit_text(f"{msg_text}\nВыберите ресторан:", reply_markup=kb)
    await state.set_state(OrderStates.choose_rest)
    await cb.answer()


@router.callback_query(F.data.startswith("rest_"))
async def e_rest_sel(cb: types.CallbackQuery, state: FSMContext):
    try:
        rest_id = int(cb.data.split("_")[1])
    except ValueError:
        await cb.answer("Ошибка в данных ресторана.", show_alert=True)
        return

    await state.update_data(rest_id=rest_id)
    await render_menu(cb.message, rest_id, state)
    await cb.answer()


async def render_menu(message: types.Message, rest_id: int, state: FSMContext):
    with get_db() as conn:
        items = conn.execute("SELECT id, name, price FROM menu WHERE restaurant_id=?", (rest_id,)).fetchall()

    data = await state.get_data()
    cart_txt = _order_summary(data["cart"])
    info = f"🛒 Корзина ({data['cart_total']} руб):\n{cart_txt}" if data["cart"] else "Корзина пуста"

    kb_rows = [
        [
            InlineKeyboardButton(
                text=f"{item['name']} - {item['price']}р",
                callback_data=f"add_{item['id']}_{item['price']}_{item['name']}",
            )
        ]
        for item in items
    ]

    ctrl_row = []
    if data["cart"]:
        ctrl_row.append(InlineKeyboardButton(text="🗑 Сброс", callback_data="clear_cart"))
        ctrl_row.append(InlineKeyboardButton(text="✅ Оформить", callback_data="checkout"))

    kb_rows.append(ctrl_row)
    kb_rows.append([InlineKeyboardButton(text="🔙 К выбору ресторана", callback_data="back_rests")])

    await message.edit_text(f"{info}\n\nМеню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.set_state(OrderStates.choose_dish)


@router.callback_query(OrderStates.choose_dish, F.data.startswith(("add_", "clear_", "back_", "checkout")))
async def e_menu_actions(cb: types.CallbackQuery, state: FSMContext):
    action = cb.data.split("_")[0]
    data = await state.get_data()

    if action == "add":
        _, i_id, price, name = cb.data.split("_")
        price = int(price)
        new_cart = data["cart"] + [{"id": i_id, "name": name, "price": price}]
        await state.update_data(cart=new_cart, cart_total=data["cart_total"] + price)
        await render_menu(cb.message, data["rest_id"], state)
        await cb.answer(f"Добавлено: {name}")
    elif action == "clear":
        await state.update_data(cart=[], cart_total=0)
        await render_menu(cb.message, data["rest_id"], state)
        await cb.answer("Корзина очищена")
    elif action == "back":
        with get_db() as conn:
            rests = conn.execute("SELECT id, name FROM restaurants").fetchall()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=r["name"], callback_data=f"rest_{r['id']}")] for r in rests]
        )
        await cb.message.edit_text("Выберите ресторан:", reply_markup=kb)
        await state.set_state(OrderStates.choose_rest)
    elif action == "checkout":
        await process_checkout(cb.message, state)


async def process_checkout(message: types.Message, state: FSMContext):
    data = await state.get_data()
    now = datetime.now()
    if deadline_passed(data["date"], now):
        await message.edit_text("Дедлайн для оформления заказа на эту дату истек.")
        await state.clear()
        return

    limit = get_limit()
    total = data["cart_total"]
    covered_by_firm = min(total, limit)
    need_to_pay = max(0, total - limit)
    user_balance = data["user_balance"] + data["refund_potential"]
    pay_from_balance = min(user_balance, need_to_pay)
    pay_real_money = need_to_pay - pay_from_balance

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="topup_balance")],
            [InlineKeyboardButton(text="✅ Подтвердить и Сохранить", callback_data="finish_order")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order")],
        ]
    )

    txt = (
        f"🧾 **Итого:** {total} руб.\n"
        f"🏢 Фирма платит: {covered_by_firm} руб.\n"
        f"👤 Ваш вклад: {need_to_pay} руб.\n\n"
        f"💳 С вашего баланса: {pay_from_balance} руб.\n"
        f"💸 **К доплате (заглушка): {pay_real_money} руб.**"
    )

    await state.update_data(pay_real_money=pay_real_money, pay_from_balance=pay_from_balance)
    await message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)
    await state.set_state(OrderStates.checkout)


@router.callback_query(OrderStates.checkout, F.data == "topup_balance")
async def e_topup_placeholder(cb: types.CallbackQuery):
    await cb.message.answer(PAYMENT_PLACEHOLDER_MESSAGE)
    await cb.answer()


@router.callback_query(OrderStates.checkout, F.data == "finish_order")
async def e_finish(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    now = datetime.now()
    if deadline_passed(data["date"], now):
        await cb.message.edit_text("Дедлайн для оформления заказа на эту дату истек.")
        await state.clear()
        await cb.answer()
        return

    with get_db() as conn:
        if data["existing_order_id"]:
            conn.execute("DELETE FROM orders WHERE id=?", (data["existing_order_id"],))

        limit = get_limit()
        total = data["cart_total"]
        need_to_pay_total = max(0, total - limit)
        avail_balance = data["user_balance"] + data["refund_potential"]

        if need_to_pay_total > avail_balance:
            new_balance = 0
            real_payment = need_to_pay_total - avail_balance
            msg_extra = f"Вы пополнили и оплатили {real_payment} руб."
        else:
            new_balance = avail_balance - need_to_pay_total
            real_payment = 0
            msg_extra = f"Списано с баланса. Остаток: {new_balance} руб."

        conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, data["user_db_id"]))
        items_str = ", ".join([i["name"] for i in data["cart"]])
        conn.execute(
            '''INSERT INTO orders (user_id, restaurant_id, order_date, items_json, total_price, paid_extra)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (data["user_db_id"], data["rest_id"], data["date"], items_str, total, need_to_pay_total),
        )
        conn.commit()

    if data.get("refund_potential"):
        await cb.message.answer(REFUND_PLACEHOLDER_MESSAGE.format(amount=data["refund_potential"]))

    await cb.message.edit_text(f"✅ Заказ на {data['date']} оформлен!\n{msg_extra}")
    await state.clear()
    await cb.answer()


@router.callback_query(OrderStates.checkout, F.data == "cancel_order")
async def e_cancel(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Оформление заказа отменено.")
    await state.clear()
    await cb.answer()
