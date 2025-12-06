from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from sqlalchemy import delete, select

from db import MenuItem, Order, Restaurant, User, get_limit, get_session, set_limit
from keyboards import kb_cancel, kb_manager
from reports import send_daily_reports
from states import ManagerStates
from utils import generate_token

router = Router()


@router.callback_query(F.data == "cancel_action")
async def cancel_action(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Действие отменено.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await cb.answer()


@router.message(F.text == "👥 Управление сотрудниками")
async def m_emp_menu(message: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить нового", callback_data="add_emp_start")],
            [InlineKeyboardButton(text="🔍 Найти, Редактировать, Удалить", callback_data="search_emp_start")],
        ]
    )
    await message.answer("Управление базой сотрудников:", reply_markup=kb)


@router.callback_query(F.data == "add_emp_start")
async def m_add_emp_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите ФИО сотрудника. (Для отмены нажмите 'Отмена')", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.add_employee_name)
    await cb.answer()


@router.message(
    F.text == "❌ Отмена",
    F.state.in_(
        [
            ManagerStates.add_employee_office,
            ManagerStates.change_limit,
            ManagerStates.emp_edit_name,
            ManagerStates.emp_edit_office,
            ManagerStates.dish_name,
            ManagerStates.dish_desc,
            ManagerStates.dish_price,
            ManagerStates.dish_id_to_delete,
        ]
    ),
)
async def m_cancel_reply(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=kb_manager())


@router.message(ManagerStates.add_employee_name)
async def m_add_emp_office(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)

    await state.update_data(name=message.text)
    with get_session() as session:
        offices = session.execute(select(User.office).where(User.office.is_not(None)).distinct()).all()

    buttons = [[KeyboardButton(text=row[0])] for row in offices]
    kb_reply = ReplyKeyboardMarkup(
        keyboard=buttons + [[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True, one_time_keyboard=True
    )
    await message.answer("Введите название офиса (или выберите):", reply_markup=kb_reply)
    await state.set_state(ManagerStates.add_employee_office)


@router.message(ManagerStates.add_employee_office)
async def m_add_emp_finish(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)

    data = await state.get_data()
    token = generate_token()
    with get_session() as session:
        session.add(User(full_name=data["name"], office=message.text, auth_token=token))
        session.commit()

    await message.answer(
        f"✅ Сотрудник создан!\nФИО: {data['name']}\nОфис: {message.text}\n🔑 Код доступа: `{token}`",
        parse_mode="Markdown",
        reply_markup=kb_manager(),
    )
    await state.clear()


@router.callback_query(F.data == "search_emp_start")
async def m_search_emp_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите часть ФИО для поиска (fuzzy search):", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_search)
    await cb.answer()


@router.message(ManagerStates.emp_search)
async def m_search_emp_process(message: types.Message, state: FSMContext):
    search_term = f"%{message.text}%"
    with get_session() as session:
        users = session.execute(
            select(User.id, User.full_name, User.office).where(User.full_name.like(search_term), User.role == "employee")
        ).all()

    if not users:
        await message.answer("Сотрудники не найдены. Попробуйте снова или нажмите 'Отмена'.", reply_markup=kb_cancel())
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{u.full_name} ({u.office})", callback_data=f"emp_id_{u.id}")] for u in users
        ]
    )
    await message.answer("Выберите сотрудника для действий:", reply_markup=kb)
    await state.set_state(ManagerStates.emp_action_select)


@router.callback_query(F.data.startswith("emp_id_"))
async def m_emp_action_select(cb: types.CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split("_")[2])
    with get_session() as session:
        user = session.get(User, user_id)

    await state.update_data(target_user_id=user_id, original_message_id=cb.message.message_id)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Изменить ФИО/Офис", callback_data="emp_edit")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data="emp_delete_confirm")],
            [InlineKeyboardButton(text="🔙 Назад к поиску", callback_data="search_emp_start")],
        ]
    )
    status = "Связан с Telegram ID" if user.tg_id else f"Ожидает активации (Токен: {user.auth_token})"
    await cb.message.edit_text(
        f"Выбран: {user.full_name} ({user.office})\nБаланс: {user.balance} руб.\nСтатус: {status}",
        reply_markup=kb,
    )
    await cb.answer()


@router.callback_query(F.data == "emp_edit")
async def m_emp_edit_start(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    with get_session() as session:
        user = session.get(User, data["target_user_id"])

    await cb.message.edit_text(f"Текущее ФИО: {user.full_name}. Введите новое:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_edit_name)
    await cb.answer()


@router.message(ManagerStates.emp_edit_name)
async def m_emp_edit_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)

    await state.update_data(new_name=message.text)
    data = await state.get_data()
    with get_session() as session:
        user = session.get(User, data["target_user_id"])

    await message.answer(f"Текущий офис: {user.office}. Введите новый:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_edit_office)


@router.message(ManagerStates.emp_edit_office)
async def m_emp_edit_finish(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)

    data = await state.get_data()
    with get_session() as session:
        user = session.get(User, data["target_user_id"])
        if user:
            user.full_name = data["new_name"]
            user.office = message.text
            session.commit()

    await message.answer(f"✅ Сотрудник {data['new_name']} обновлен.", reply_markup=kb_manager())
    await state.clear()


@router.callback_query(F.data == "emp_delete_confirm")
async def m_emp_delete_confirm(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Подтвердить удаление", callback_data="emp_delete_execute")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="search_emp_start")],
        ]
    )
    await cb.message.edit_text("Внимание! Это удалит сотрудника и все его заказы. Подтвердите:", reply_markup=kb)
    await cb.answer()


@router.callback_query(F.data == "emp_delete_execute")
async def m_emp_delete_execute(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data["target_user_id"]
    with get_session() as session:
        session.execute(delete(Order).where(Order.user_id == user_id))
        user = session.get(User, user_id)
        if user:
            session.delete(user)
        session.commit()

    await cb.message.edit_text("✅ Сотрудник и все его заказы удалены.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await state.clear()
    await cb.answer()


@router.message(F.text == "🥗 Управление меню")
async def m_rest_menu(message: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Новый ресторан", callback_data="new_rest")],
            [InlineKeyboardButton(text="🔍 Список/Редактировать", callback_data="list_rest")],
        ]
    )
    await message.answer("Управление ресторанами и меню:", reply_markup=kb)


@router.callback_query(F.data == "new_rest")
async def m_new_rest_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название нового ресторана:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.add_rest_name)
    await cb.answer()


@router.message(ManagerStates.add_rest_name)
async def m_save_rest(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)

    with get_session() as session:
        session.add(Restaurant(name=message.text))
        session.commit()

    await message.answer(f"Ресторан '{message.text}' добавлен.", reply_markup=kb_manager())
    await state.clear()


@router.callback_query(F.data == "list_rest")
async def m_list_rest(cb: types.CallbackQuery, state: FSMContext):
    with get_session() as session:
        rests = session.execute(select(Restaurant.id, Restaurant.name)).all()

    if not rests:
        await cb.message.edit_text("Пока нет ни одного ресторана.", reply_markup=None)
        await cb.message.answer("Добавить новый?", reply_markup=kb_manager())
        await cb.answer()
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=r.name, callback_data=f"rest_edit_{r.id}")] for r in rests]
    )
    await cb.message.edit_text("Выберите ресторан для редактирования:", reply_markup=kb)
    await state.set_state(ManagerStates.rest_action_select)
    await state.update_data(rest_keyboard_message=cb.message.message_id)
    await cb.answer()


async def _render_restaurant_actions(message: types.Message, rest_id: int, state: FSMContext):
    with get_session() as session:
        dishes = session.execute(
            select(MenuItem.id, MenuItem.name, MenuItem.price).where(MenuItem.restaurant_id == rest_id)
        ).all()
        rest = session.get(Restaurant, rest_id)

    dishes_txt = "\n".join([f"- {d.name} ({d.price}р)" for d in dishes]) or "Меню пустое"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить блюдо", callback_data="dish_add")],
            [InlineKeyboardButton(text="🗑 Удалить блюдо", callback_data="dish_delete")],
            [InlineKeyboardButton(text="❌ Удалить ресторан", callback_data="delete_rest_confirm")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="list_rest")],
        ]
    )
    await state.update_data(target_rest_id=rest_id)
    await message.edit_text(f"Ресторан: {rest.name}\nМеню:\n{dishes_txt}", reply_markup=kb)


@router.callback_query(F.data.startswith("rest_edit_"))
async def m_rest_edit_menu(cb: types.CallbackQuery, state: FSMContext):
    rest_id = int(cb.data.split("_")[2])
    await _render_restaurant_actions(cb.message, rest_id, state)
    await cb.answer()


@router.callback_query(F.data == "dish_add")
async def m_dish_name(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название блюда:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.dish_name)
    await cb.answer()


@router.message(ManagerStates.dish_name)
async def m_dish_desc(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)
    await state.update_data(dish_name=message.text)
    await message.answer("Введите описание блюда:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.dish_desc)


@router.message(ManagerStates.dish_desc)
async def m_dish_price(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)
    await state.update_data(dish_desc=message.text)
    await message.answer("Введите цену блюда (число):", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.dish_price)


@router.message(ManagerStates.dish_price)
async def m_dish_save(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена":
        return await m_cancel_reply(message, state)
    if not message.text.isdigit():
        await message.answer("Нужно число. Попробуйте снова или нажмите 'Отмена'.")
        return

    data = await state.get_data()
    with get_session() as session:
        session.add(
            MenuItem(
                restaurant_id=data["target_rest_id"],
                name=data["dish_name"],
                description=data["dish_desc"],
                price=int(message.text),
            )
        )
        session.commit()

    await message.answer("Блюдо добавлено.", reply_markup=kb_manager())
    await state.clear()


@router.callback_query(F.data == "dish_delete")
async def m_dish_delete_ask(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rest_id = data.get("target_rest_id")
    with get_session() as session:
        dishes = session.execute(select(MenuItem.id, MenuItem.name).where(MenuItem.restaurant_id == rest_id)).all()

    if not dishes:
        await cb.answer("В меню нет блюд", show_alert=True)
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=d.name, callback_data=f"dish_del_{d.id}")] for d in dishes]
    )
    await cb.message.edit_text("Выберите блюдо для удаления:", reply_markup=kb)
    await state.set_state(ManagerStates.dish_id_to_delete)
    await cb.answer()


@router.callback_query(F.data.startswith("dish_del_"), ManagerStates.dish_id_to_delete)
async def m_dish_delete(cb: types.CallbackQuery, state: FSMContext):
    dish_id = int(cb.data.split("_")[2])
    with get_session() as session:
        dish = session.get(MenuItem, dish_id)
        if dish:
            session.delete(dish)
            session.commit()

    await cb.message.edit_text("Блюдо удалено.", reply_markup=None)
    await cb.message.answer("Возврат в меню ресторана", reply_markup=kb_manager())
    await state.clear()
    await cb.answer()


@router.callback_query(F.data == "delete_rest_confirm")
async def m_delete_rest_confirm(cb: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔥 Подтвердить (Удалить безвозвратно)", callback_data="delete_rest_execute")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="list_rest")],
        ]
    )
    await cb.message.edit_text(
        "⚠️ **УДАЛИТЬ РЕСТОРАН?** Это удалит все блюда и заказы, связанные с ним!",
        parse_mode="Markdown",
        reply_markup=kb,
    )
    await state.set_state(ManagerStates.rest_delete_confirm)
    await cb.answer()


@router.callback_query(F.data == "delete_rest_execute", ManagerStates.rest_delete_confirm)
async def m_delete_rest_execute(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rest_id = data["target_rest_id"]
    with get_session() as session:
        session.execute(delete(Order).where(Order.restaurant_id == rest_id))
        session.execute(delete(MenuItem).where(MenuItem.restaurant_id == rest_id))
        rest = session.get(Restaurant, rest_id)
        if rest:
            session.delete(rest)
        session.commit()

    await cb.message.edit_text("✅ Ресторан, его меню и все связанные заказы удалены.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await state.clear()
    await cb.answer()


@router.message(F.text == "⚙️ Лимит бюджета")
async def m_limit(msg: types.Message, state: FSMContext):
    curr = get_limit()
    kb_reply = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True, one_time_keyboard=True
    )
    await msg.answer(
        f"Текущий лимит на сотрудника: {curr} руб. Введите новый (или Отмена):", reply_markup=kb_reply
    )
    await state.set_state(ManagerStates.change_limit)


@router.message(ManagerStates.change_limit)
async def m_limit_save(msg: types.Message, state: FSMContext):
    if msg.text == "❌ Отмена":
        return await m_cancel_reply(msg, state)

    if msg.text.isdigit():
        set_limit(int(msg.text))
        await msg.answer(f"Лимит обновлен до {msg.text} руб.", reply_markup=kb_manager())
        await state.clear()
    else:
        await msg.answer("Нужно число. Попробуйте снова или нажмите 'Отмена'.")


@router.message(F.text == "📊 Отчет сейчас")
async def manual_report(message: types.Message):
    await message.answer("Формирую отчеты...")
    await send_daily_reports(message.bot)
