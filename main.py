import asyncio
import logging
import sqlite3
import os
import random
import string
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command  # StateFilter удален, так как он не нужен для F.state
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= КОНФИГУРАЦИЯ ПРОЕКТА =================

BOT_TOKEN = "8568838231:AAGKoCcI7HbuifkKdhwroizMlDhRe1bGbW0"  # <--- ВСТАВЬТЕ ТОКЕН
DB_NAME = "lunch_mvp.db"
ADMIN_PASSWORD = "admin"  # Пароль для первого входа менеджера

# Настройки лимитов
DEFAULT_LIMIT = 400

# ВРЕМЯ ОТПРАВКИ ОТЧЕТА (Часы и минуты)
REPORT_HOUR = 12
REPORT_MINUTE = 00

# ЧАС ДЕДЛАЙНА ДЛЯ ЗАКАЗА НА ТЕКУЩИЙ ДЕНЬ
ORDER_DEADLINE_HOUR = 19

# =======================================================

logging.basicConfig(level=logging.INFO)


# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    cursor = conn.cursor()

    # 1. Пользователи
    cursor.execute('''CREATE TABLE IF NOT EXISTS users
                      (
                          id
                          INTEGER
                          PRIMARY
                          KEY
                          AUTOINCREMENT,
                          tg_id
                          INTEGER
                          UNIQUE,
                          full_name
                          TEXT,
                          office
                          TEXT,
                          role
                          TEXT
                          DEFAULT
                          'employee',
                          balance
                          INTEGER
                          DEFAULT
                          0,
                          auth_token
                          TEXT
                      )''')

    # 2. Рестораны
    cursor.execute('''CREATE TABLE IF NOT EXISTS restaurants
                      (
                          id
                          INTEGER
                          PRIMARY
                          KEY
                          AUTOINCREMENT,
                          name
                          TEXT,
                          is_active
                          BOOLEAN
                          DEFAULT
                          1
                      )''')

    # 3. Меню
    cursor.execute('''CREATE TABLE IF NOT EXISTS menu
    (
        id
        INTEGER
        PRIMARY
        KEY
        AUTOINCREMENT,
        restaurant_id
        INTEGER,
        name
        TEXT,
        description
        TEXT,
        price
        INTEGER,
        FOREIGN
        KEY
                      (
        restaurant_id
                      ) REFERENCES restaurants
                      (
                          id
                      ) ON DELETE CASCADE
        )''')

    # 4. Заказы
    cursor.execute('''CREATE TABLE IF NOT EXISTS orders
    (
        id
        INTEGER
        PRIMARY
        KEY
        AUTOINCREMENT,
        user_id
        INTEGER,
        restaurant_id
        INTEGER,
        order_date
        TEXT,
        items_json
        TEXT,
        total_price
        INTEGER,
        paid_extra
        INTEGER,
        created_at
        TIMESTAMP
        DEFAULT
        CURRENT_TIMESTAMP,
        FOREIGN
        KEY
                      (
        user_id
                      ) REFERENCES users
                      (
                          id
                      ),
        UNIQUE
                      (
                          user_id,
                          order_date
                      )
        )''')

    # 5. Конфиг
    cursor.execute('''CREATE TABLE IF NOT EXISTS config
                      (
                          key
                          TEXT
                          PRIMARY
                          KEY,
                          value
                          TEXT
                      )''')
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('daily_limit', ?)", (str(DEFAULT_LIMIT),))
    conn.commit()
    conn.close()


# --- FSM (Машина состояний) ---
class AuthStates(StatesGroup):
    waiting_for_password = State()


class ManagerStates(StatesGroup):
    # Добавление сотрудника
    add_employee_name = State()
    add_employee_office = State()
    # Управление сотрудниками
    emp_search = State()
    emp_action_select = State()
    emp_edit_name = State()
    emp_edit_office = State()
    # Управление ресторанами
    add_rest_name = State()
    rest_action_select = State()
    rest_delete_confirm = State()
    dish_name = State()
    dish_desc = State()
    dish_price = State()
    dish_id_to_delete = State()
    # Прочее
    change_limit = State()


class OrderStates(StatesGroup):
    choose_date = State()
    choose_rest = State()
    choose_dish = State()


# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
scheduler = AsyncIOScheduler()


# --- УТИЛИТЫ ---
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_limit():
    with get_db() as conn:
        val = conn.execute("SELECT value FROM config WHERE key='daily_limit'").fetchone()[0]
    return int(val)


def generate_token(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


# ================== КЛАВИАТУРЫ И НАВИГАЦИЯ ==================

def kb_manager():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="👥 Управление сотрудниками"), KeyboardButton(text="🥗 Управление меню")],
        [KeyboardButton(text="⚙️ Лимит бюджета"), KeyboardButton(text="📊 Отчет сейчас")]
    ], resize_keyboard=True)


def kb_employee():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🍱 Сделать заказ")],
        [KeyboardButton(text="👤 Мой профиль / Баланс")]
    ], resize_keyboard=True)


def kb_cancel():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]])


@dp.callback_query(F.data == "cancel_action")
async def cancel_action(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Действие отменено.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await cb.answer()


# ================== ХЕНДЛЕРЫ: АВТОРИЗАЦИЯ ==================

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        if user['role'] == 'manager':
            await message.answer(f"👨‍💼 Панель менеджера. Отчеты настроены на {REPORT_HOUR}:{REPORT_MINUTE:02d}",
                                 reply_markup=kb_manager())
        else:
            await message.answer(f"👋 Привет, {user['full_name']}! Ваш баланс: {user['balance']} руб.",
                                 reply_markup=kb_employee())
    else:
        await message.answer("🔒 Введите пароль доступа (admin) или токен, выданный менеджером:")
        await state.set_state(AuthStates.waiting_for_password)


@dp.message(AuthStates.waiting_for_password)
async def process_auth(message: types.Message, state: FSMContext):
    text = message.text.strip()
    conn = get_db()

    if text == ADMIN_PASSWORD:
        role, name = 'manager', "Главный Менеджер"
        conn.execute("INSERT OR REPLACE INTO users (tg_id, full_name, role) VALUES (?, ?, ?)",
                     (message.from_user.id, name, role))
        conn.commit()
    else:
        user_invite = conn.execute("SELECT id, full_name, office FROM users WHERE auth_token = ? AND tg_id IS NULL",
                                   (text,)).fetchone()
        if user_invite:
            role, name = 'employee', user_invite['full_name']
            conn.execute("UPDATE users SET tg_id = ?, auth_token = NULL, role = ? WHERE id = ?",
                         (message.from_user.id, role, user_invite['id']))
            conn.commit()
        else:
            await message.answer("⛔ Неверный пароль или токен уже использован.")
            conn.close()
            return

    await message.answer(f"✅ Успешно! Вы вошли как {name} ({role.upper()}).",
                         reply_markup=kb_manager() if role == 'manager' else kb_employee())
    await state.clear()
    conn.close()


# ================== ЛОГИКА МЕНЕДЖЕРА: СОТРУДНИКИ (CRUD) ==================

@dp.message(F.text == "👥 Управление сотрудниками")
async def m_emp_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить нового", callback_data="add_emp_start")],
        [InlineKeyboardButton(text="🔍 Найти, Редактировать, Удалить", callback_data="search_emp_start")],
    ])
    await message.answer("Управление базой сотрудников:", reply_markup=kb)


@dp.callback_query(F.data == "add_emp_start")
async def m_add_emp_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите ФИО сотрудника. (Для отмены нажмите 'Отмена')", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.add_employee_name)
    await cb.answer()


# *** ИСПРАВЛЕННЫЙ ХЕНДЛЕР: ИСПОЛЬЗУЕМ F.state.in_([Состояние1, Состояние2]) ***
@dp.message(F.text == "❌ Отмена", F.state.in_([
    ManagerStates.add_employee_office,
    ManagerStates.change_limit,
    ManagerStates.emp_edit_name,  # Добавлено для полной отмены, если пользователь начал вводить ФИО
    ManagerStates.emp_edit_office,  # Добавлено для полной отмены
    ManagerStates.dish_name,
    ManagerStates.dish_desc,
    ManagerStates.dish_price,
    ManagerStates.dish_id_to_delete
]))
async def m_cancel_reply(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=kb_manager())


@dp.message(ManagerStates.add_employee_name)
async def m_add_emp_office(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await m_cancel_reply(message, state)
    await state.update_data(name=message.text)
    conn = get_db()
    offices = conn.execute("SELECT DISTINCT office FROM users WHERE office IS NOT NULL").fetchall()
    conn.close()

    buttons = [[KeyboardButton(text=row[0])] for row in offices]
    kb_reply = ReplyKeyboardMarkup(keyboard=buttons + [[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True,
                                   one_time_keyboard=True)

    await message.answer("Введите название офиса (или выберите):", reply_markup=kb_reply)
    await state.set_state(ManagerStates.add_employee_office)


@dp.message(ManagerStates.add_employee_office)
async def m_add_emp_finish(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await m_cancel_reply(message, state)

    data = await state.get_data()
    token = generate_token()

    with get_db() as conn:
        conn.execute("INSERT INTO users (full_name, office, auth_token) VALUES (?, ?, ?)",
                     (data['name'], message.text, token))
        conn.commit()

    await message.answer(
        f"✅ Сотрудник создан!\nФИО: {data['name']}\nОфис: {message.text}\n🔑 Код доступа: `{token}`",
        parse_mode="Markdown",
        reply_markup=kb_manager()
    )
    await state.clear()


# --- Поиск, Редактирование, Удаление ---
@dp.callback_query(F.data == "search_emp_start")
async def m_search_emp_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите часть ФИО для поиска (fuzzy search):", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_search)
    await cb.answer()


@dp.message(ManagerStates.emp_search)
async def m_search_emp_process(message: types.Message, state: FSMContext):
    search_term = f"%{message.text}%"
    conn = get_db()
    users = conn.execute("SELECT id, full_name, office FROM users WHERE full_name LIKE ? AND role='employee'",
                         (search_term,)).fetchall()
    conn.close()

    if not users:
        await message.answer("Сотрудники не найдены. Попробуйте снова или нажмите 'Отмена'.", reply_markup=kb_cancel())
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{u['full_name']} ({u['office']})", callback_data=f"emp_id_{u['id']}")] for u in
        users
    ])
    await message.answer("Выберите сотрудника для действий:", reply_markup=kb)
    await state.set_state(ManagerStates.emp_action_select)


@dp.callback_query(F.data.startswith("emp_id_"))
async def m_emp_action_select(cb: types.CallbackQuery, state: FSMContext):
    user_id = int(cb.data.split("_")[2])
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()

    await state.update_data(target_user_id=user_id, original_message_id=cb.message.message_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить ФИО/Офис", callback_data="emp_edit")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="emp_delete_confirm")],
        [InlineKeyboardButton(text="🔙 Назад к поиску", callback_data="search_emp_start")]
    ])

    status = "Связан с Telegram ID" if user['tg_id'] else f"Ожидает активации (Токен: {user['auth_token']})"

    await cb.message.edit_text(
        f"Выбран: {user['full_name']} ({user['office']})\nБаланс: {user['balance']} руб.\nСтатус: {status}",
        reply_markup=kb
    )
    await cb.answer()


@dp.callback_query(F.data == "emp_edit")
async def m_emp_edit_start(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    conn = get_db()
    user = conn.execute("SELECT full_name, office FROM users WHERE id=?", (data['target_user_id'],)).fetchone()
    conn.close()

    await cb.message.edit_text(f"Текущее ФИО: {user['full_name']}. Введите новое:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_edit_name)
    await cb.answer()


@dp.message(ManagerStates.emp_edit_name)
async def m_emp_edit_name(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await m_cancel_reply(message, state)
    await state.update_data(new_name=message.text)
    data = await state.get_data()
    conn = get_db()
    user = conn.execute("SELECT office FROM users WHERE id=?", (data['target_user_id'],)).fetchone()
    conn.close()

    await message.answer(f"Текущий офис: {user['office']}. Введите новый:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.emp_edit_office)


@dp.message(ManagerStates.emp_edit_office)
async def m_emp_edit_finish(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await m_cancel_reply(message, state)
    data = await state.get_data()

    with get_db() as conn:
        conn.execute("UPDATE users SET full_name=?, office=? WHERE id=?",
                     (data['new_name'], message.text, data['target_user_id']))
        conn.commit()

    await message.answer(f"✅ Сотрудник {data['new_name']} обновлен.", reply_markup=kb_manager())
    await state.clear()


@dp.callback_query(F.data == "emp_delete_confirm")
async def m_emp_delete_confirm(cb: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Подтвердить удаление", callback_data="emp_delete_execute")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="search_emp_start")]
    ])
    await cb.message.edit_text("Внимание! Это удалит сотрудника и все его заказы. Подтвердите:", reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data == "emp_delete_execute")
async def m_emp_delete_execute(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = data['target_user_id']

    with get_db() as conn:
        conn.execute("DELETE FROM orders WHERE user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()

    await cb.message.edit_text("✅ Сотрудник и все его заказы удалены.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await state.clear()
    await cb.answer()


# ================== ЛОГИКА МЕНЕДЖЕРА: РЕСТОРАНЫ/МЕНЮ (CRUD) ==================

@dp.message(F.text == "🥗 Управление меню")
async def m_rest_menu(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый ресторан", callback_data="new_rest")],
        [InlineKeyboardButton(text="🔍 Список/Редактировать", callback_data="list_rest")],
    ])
    await message.answer("Управление ресторанами и меню:", reply_markup=kb)


# Добавление нового ресторана
@dp.callback_query(F.data == "new_rest")
async def m_new_rest_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название нового ресторана:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.add_rest_name)
    await cb.answer()


@dp.message(ManagerStates.add_rest_name)
async def m_save_rest(message: types.Message, state: FSMContext):
    if message.text == "❌ Отмена": return await m_cancel_reply(message, state)
    with get_db() as conn:
        conn.execute("INSERT INTO restaurants (name) VALUES (?)", (message.text,))
        conn.commit()
    await message.answer(f"Ресторан '{message.text}' добавлен.", reply_markup=kb_manager())
    await state.clear()


# Список ресторанов для редактирования
@dp.callback_query(F.data == "list_rest")
async def m_list_rest(cb: types.CallbackQuery, state: FSMContext):
    conn = get_db()
    rests = conn.execute("SELECT id, name FROM restaurants").fetchall()
    conn.close()

    if not rests:
        await cb.message.edit_text("Нет активных ресторанов.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data="new_rest")]
        ]))
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
                                                  [InlineKeyboardButton(text=r['name'],
                                                                        callback_data=f"rest_edit_{r['id']}")] for r in
                                                  rests
                                              ] + [
                                                  [InlineKeyboardButton(text="🔙 Назад в меню",
                                                                        callback_data="back_to_m_menu_btn")]
                                              ])

    await cb.message.edit_text("Выберите ресторан для редактирования:", reply_markup=kb)
    await state.set_state(ManagerStates.rest_action_select)
    await cb.answer()


@dp.callback_query(F.data == "back_to_m_menu_btn")
async def m_back_to_main_menu(cb: types.CallbackQuery):
    await cb.message.edit_text("Выберите действие:", reply_markup=None)
    await m_rest_menu(cb.message)
    await cb.answer()


# *** ИСПРАВЛЕННЫЙ ХЕНДЛЕР: Обрабатывает только rest_edit_ и back_to_rest_menu ***
@dp.callback_query(F.data.startswith("rest_edit_") | F.data == "back_to_rest_menu")
async def m_rest_edit_menu(cb: types.CallbackQuery, state: FSMContext):
    if cb.data.startswith("rest_edit_"):
        # Извлекаем ID корректно
        rest_id = int(cb.data.split("_")[2])
        await state.update_data(target_rest_id=rest_id)
    else:  # back_to_rest_menu
        data = await state.get_data()
        rest_id = data.get('target_rest_id')
        if not rest_id:
            await cb.message.edit_text("Ошибка контекста. Вернитесь в главное меню.", reply_markup=None)
            await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
            await state.clear()
            return await cb.answer()

    conn = get_db()
    menu_items = conn.execute("SELECT id, name, price FROM menu WHERE restaurant_id=?", (rest_id,)).fetchall()
    rest_name = conn.execute("SELECT name FROM restaurants WHERE id=?", (rest_id,)).fetchone()['name']
    conn.close()

    menu_txt = "\n".join(
        [f"• ID {item['id']}: {item['name']} ({item['price']}р)" for item in menu_items]) or "Меню пусто."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить блюдо", callback_data="add_dish_to_rest")],
        [InlineKeyboardButton(text="🗑 Удалить блюдо по ID", callback_data="delete_dish_start")],
        [InlineKeyboardButton(text="❌ Удалить ресторан (ОПАСНО)", callback_data="delete_rest_confirm")],
        [InlineKeyboardButton(text="🔙 К списку ресторанов", callback_data="list_rest")]
    ])

    await cb.message.edit_text(f"Ресторан: **{rest_name}**\n\nМеню:\n{menu_txt}", parse_mode="Markdown",
                               reply_markup=kb)
    await cb.answer()


# --- CRUD блюд ---
@dp.callback_query(F.data == "add_dish_to_rest")
async def m_add_dish_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Введите название блюда:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.dish_name)
    await cb.answer()


@dp.message(ManagerStates.dish_name)
async def m_dish_name(msg: types.Message, state: FSMContext):
    if msg.text == "❌ Отмена": return await m_cancel_reply(msg, state)
    await state.update_data(d_name=msg.text)
    await msg.answer("Описание/Состав:")
    await state.set_state(ManagerStates.dish_desc)


@dp.message(ManagerStates.dish_desc)
async def m_dish_desc(msg: types.Message, state: FSMContext):
    if msg.text == "❌ Отмена": return await m_cancel_reply(msg, state)
    await state.update_data(d_desc=msg.text)
    await msg.answer("Цена (просто число):")
    await state.set_state(ManagerStates.dish_price)


@dp.message(ManagerStates.dish_price)
async def m_dish_fin(msg: types.Message, state: FSMContext):
    if not msg.text.isdigit():
        return await msg.answer("Нужно ввести число.", reply_markup=kb_cancel())

    data = await state.get_data()

    with get_db() as conn:
        conn.execute("INSERT INTO menu (restaurant_id, name, description, price) VALUES (?, ?, ?, ?)",
                     (data['target_rest_id'], data['d_name'], data['d_desc'], int(msg.text)))
        conn.commit()

    await msg.answer("✅ Блюдо добавлено.", reply_markup=kb_manager())
    await state.clear()

    # Имитируем коллбэк для возврата к меню ресторана
    class DummyCallback:
        def __init__(self, message, data):
            self.message = message
            self.data = data
            self.from_user = message.from_user

        async def answer(self, text=''): pass

    await m_rest_edit_menu(DummyCallback(msg, 'back_to_rest_menu'), state)


@dp.callback_query(F.data == "delete_dish_start")
async def m_delete_dish_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.answer("Введите ID блюда, которое хотите удалить:", reply_markup=kb_cancel())
    await state.set_state(ManagerStates.dish_id_to_delete)
    await cb.answer()


@dp.message(ManagerStates.dish_id_to_delete)
async def m_delete_dish_execute(msg: types.Message, state: FSMContext):
    if msg.text == "❌ Отмена": return await m_cancel_reply(msg, state)
    if not msg.text.isdigit():
        await msg.answer("ID должен быть числом.", reply_markup=kb_cancel())
        return

    dish_id = int(msg.text)
    data = await state.get_data()
    rest_id = data['target_rest_id']
    success = False

    with get_db() as conn:
        cursor = conn.execute("SELECT name FROM menu WHERE id=? AND restaurant_id=?", (dish_id, rest_id))
        dish_name = cursor.fetchone()

        if dish_name:
            conn.execute("DELETE FROM menu WHERE id=?", (dish_id,))
            conn.commit()
            await msg.answer(f"✅ Блюдо '{dish_name['name']}' удалено.", reply_markup=kb_manager())
            success = True
        else:
            await msg.answer("❌ Блюдо с таким ID не найдено в этом ресторане.", reply_markup=kb_cancel())
            return

    await state.clear()

    if success:
        class DummyCallback:
            def __init__(self, message, data):
                self.message = message
                self.data = data
                self.from_user = message.from_user

            async def answer(self, text=''): pass

        await m_rest_edit_menu(DummyCallback(msg, 'back_to_rest_menu'), state)


@dp.callback_query(F.data == "delete_rest_confirm")
async def m_delete_rest_confirm(cb: types.CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔥 Подтвердить (Удалить безвозвратно)", callback_data="delete_rest_execute")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_rest_menu")]
    ])
    await cb.message.edit_text("⚠️ **УДАЛИТЬ РЕСТОРАН?** Это удалит все блюда и заказы, связанные с ним!",
                               parse_mode="Markdown", reply_markup=kb)
    await state.set_state(ManagerStates.rest_delete_confirm)
    await cb.answer()


@dp.callback_query(F.data == "delete_rest_execute", ManagerStates.rest_delete_confirm)
async def m_delete_rest_execute(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    rest_id = data['target_rest_id']

    with get_db() as conn:
        conn.execute("DELETE FROM restaurants WHERE id=?", (rest_id,))
        conn.commit()

    await cb.message.edit_text("✅ Ресторан, его меню и все связанные заказы удалены.", reply_markup=None)
    await cb.message.answer("Выберите действие:", reply_markup=kb_manager())
    await state.clear()
    await cb.answer()


# --- Изменение лимита с отменой ---
@dp.message(F.text == "⚙️ Лимит бюджета")
async def m_limit(msg: types.Message, state: FSMContext):
    curr = get_limit()
    kb_reply = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Отмена")]], resize_keyboard=True,
                                   one_time_keyboard=True)
    await msg.answer(f"Текущий лимит на сотрудника: {curr} руб. Введите новый (или Отмена):", reply_markup=kb_reply)
    await state.set_state(ManagerStates.change_limit)


@dp.message(ManagerStates.change_limit)
async def m_limit_save(msg: types.Message, state: FSMContext):
    if msg.text == "❌ Отмена": return await m_cancel_reply(msg, state)

    if msg.text.isdigit():
        with get_db() as conn:
            conn.execute("UPDATE config SET value = ? WHERE key='daily_limit'", (msg.text,))
            conn.commit()
        await msg.answer(f"Лимит обновлен до {msg.text} руб.", reply_markup=kb_manager())
        await state.clear()
    else:
        await msg.answer("Нужно число. Попробуйте снова или нажмите 'Отмена'.")
        # Состояние не сбрасывается, чтобы дать пользователю шанс ввести число или отменить


# ================== ЛОГИКА СОТРУДНИКА (УЛУЧШЕННЫЙ ПРОФИЛЬ) ==================

@dp.message(F.text == "👤 Мой профиль / Баланс")
async def e_profile(message: types.Message):
    conn = get_db()
    user = conn.execute("SELECT id, full_name, balance FROM users WHERE tg_id=?", (message.from_user.id,)).fetchone()

    today = datetime.now().strftime("%Y-%m-%d")
    current_limit = get_limit()

    order_today = conn.execute("SELECT total_price FROM orders WHERE user_id=? AND order_date=?",
                               (user['id'], today)).fetchone()

    if order_today:
        daily_status = f"✅ Заказ на сегодня ({order_today['total_price']} руб.) уже оформлен."
    elif datetime.now().hour >= ORDER_DEADLINE_HOUR:  # Использование константы
        daily_status = f"❌ Заказ на сегодня уже недоступен (дедлайн {ORDER_DEADLINE_HOUR}:00)."
    else:
        daily_status = f"✅ Сегодня до {ORDER_DEADLINE_HOUR}:00 доступен лимит *{current_limit} руб.*"

    future_orders = conn.execute('''
                                 SELECT o.order_date, r.name, o.total_price
                                 FROM orders o
                                          JOIN restaurants r ON o.restaurant_id = r.id
                                 WHERE user_id = ?
                                   AND order_date > ?
                                 ORDER BY order_date
                                 ''', (user['id'], today)).fetchall()
    conn.close()

    order_txt = "\n".join(
        [f"📅 {o['order_date']}: {o['name']} ({o['total_price']}р)" for o in future_orders]) or "Нет заказов на будущее"

    await message.answer(
        f"👤 *{user['full_name']}*\n"
        f"💰 Личный Баланс (переплаты/возвраты): *{user['balance']} руб.*\n"
        f"--- Дневной лимит ({current_limit} руб.) ---\n"
        f"{daily_status}\n\n"
        f"📋 Заказы на будущее:\n{order_txt}",
        parse_mode="Markdown",
        reply_markup=kb_employee()
    )


# --- ЛОГИКА ЗАКАЗА ---

@dp.message(F.text == "🍱 Сделать заказ")
async def e_order_start(message: types.Message, state: FSMContext):
    now = datetime.now()
    dates_kb = []

    for i in range(7):
        d = now + timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        d_label = d.strftime("%d.%m (%a)")

        if i == 0:
            if now.hour >= ORDER_DEADLINE_HOUR:  # Использование константы
                continue
            d_label = f"Сегодня (до {ORDER_DEADLINE_HOUR}:00)"

        dates_kb.append([InlineKeyboardButton(text=d_label, callback_data=f"date_{d_str}")])

    if not dates_kb:
        await message.answer("На ближайшее время заказы закрыты.")
        return

    await message.answer("Выберите дату доставки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=dates_kb))
    await state.set_state(OrderStates.choose_date)


@dp.callback_query(F.data.startswith("date_"))
async def e_date_sel(cb: types.CallbackQuery, state: FSMContext):
    date_str = cb.data.split("_")[1]

    conn = get_db()
    user = conn.execute("SELECT id, balance FROM users WHERE tg_id=?", (cb.from_user.id,)).fetchone()

    existing = conn.execute("SELECT id, paid_extra FROM orders WHERE user_id=? AND order_date=?",
                            (user['id'], date_str)).fetchone()

    rests = conn.execute("SELECT id, name FROM restaurants").fetchall()
    conn.close()

    refund_potential = existing['paid_extra'] if existing else 0

    await state.update_data(
        date=date_str,
        user_db_id=user['id'],
        user_balance=user['balance'],
        existing_order_id=existing['id'] if existing else None,
        refund_potential=refund_potential,
        cart=[],
        cart_total=0
    )

    msg_text = f"Заказ на {date_str}."
    if existing:
        msg_text += f"\n⚠️ У вас уже есть заказ. При изменении {refund_potential} руб. вернутся на баланс."

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r['name'], callback_data=f"rest_{r['id']}")] for r in rests
    ])

    await cb.message.edit_text(f"{msg_text}\nВыберите ресторан:", reply_markup=kb)
    await state.set_state(OrderStates.choose_rest)


@dp.callback_query(F.data.startswith("rest_"))
async def e_rest_sel(cb: types.CallbackQuery, state: FSMContext):
    try:
        rest_id = int(cb.data.split("_")[1])
    except ValueError:
        # Теперь эта ветка не вызывается кнопкой 'rest_edit_', но оставлена для безопасности
        await cb.answer("Ошибка в данных ресторана.", show_alert=True)
        return

    await state.update_data(rest_id=rest_id)
    await render_menu(cb.message, rest_id, state)
    await cb.answer()


async def render_menu(message: types.Message, rest_id: int, state: FSMContext):
    conn = get_db()
    items = conn.execute("SELECT id, name, price FROM menu WHERE restaurant_id=?", (rest_id,)).fetchall()
    conn.close()

    data = await state.get_data()
    cart_txt = "\n".join([f"- {i['name']} ({i['price']}р)" for i in data['cart']])

    info = f"🛒 Корзина ({data['cart_total']} руб):\n{cart_txt}" if data['cart'] else "Корзина пуста"

    kb_rows = []
    for item in items:
        kb_rows.append([InlineKeyboardButton(text=f"{item['name']} - {item['price']}р",
                                             callback_data=f"add_{item['id']}_{item['price']}_{item['name']}")])

    ctrl_row = []
    if data['cart']:
        ctrl_row.append(InlineKeyboardButton(text="🗑 Сброс", callback_data="clear_cart"))
        ctrl_row.append(InlineKeyboardButton(text="✅ Оформить", callback_data="checkout"))

    kb_rows.append(ctrl_row)
    kb_rows.append([InlineKeyboardButton(text="🔙 К выбору ресторана", callback_data="back_rests")])

    await message.edit_text(f"{info}\n\nМеню:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await state.set_state(OrderStates.choose_dish)


@dp.callback_query(OrderStates.choose_dish)
async def e_menu_actions(cb: types.CallbackQuery, state: FSMContext):
    action = cb.data.split("_")[0]
    data = await state.get_data()

    if action == "add":
        _, i_id, price, name = cb.data.split("_")
        price = int(price)
        new_cart = data['cart'] + [{'id': i_id, 'name': name, 'price': price}]
        await state.update_data(cart=new_cart, cart_total=data['cart_total'] + price)
        await render_menu(cb.message, data['rest_id'], state)
        await cb.answer(f"Добавлено: {name}")

    elif action == "clear":
        await state.update_data(cart=[], cart_total=0)
        await render_menu(cb.message, data['rest_id'], state)
        await cb.answer("Корзина очищена")

    elif action == "back":
        conn = get_db()
        rests = conn.execute("SELECT id, name FROM restaurants").fetchall()
        conn.close()
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=r['name'], callback_data=f"rest_{r['id']}")] for r in rests])
        await cb.message.edit_text("Выберите ресторан:", reply_markup=kb)
        await state.set_state(OrderStates.choose_rest)

    elif action == "checkout":
        await process_checkout(cb.message, state)


async def process_checkout(message, state):
    data = await state.get_data()
    limit = get_limit()
    total = data['cart_total']

    covered_by_firm = min(total, limit)
    need_to_pay = max(0, total - limit)

    user_balance = data['user_balance'] + data['refund_potential']

    pay_from_balance = min(need_to_pay, user_balance)
    pay_real_money = need_to_pay - pay_from_balance

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и Сохранить", callback_data="finish_order")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_order")]
    ])

    txt = (f"🧾 **Итого:** {total} руб.\n"
           f"🏢 Фирма платит: {covered_by_firm} руб.\n"
           f"👤 Ваш вклад: {need_to_pay} руб.\n\n"
           f"💳 С вашего баланса: {pay_from_balance} руб.\n"
           f"💸 **К доплате (заглушка): {pay_real_money} руб.**")

    await message.edit_text(txt, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data == "finish_order")
async def e_finish(cb: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    conn = get_db()

    if data['existing_order_id']:
        conn.execute("DELETE FROM orders WHERE id=?", (data['existing_order_id'],))

    limit = get_limit()
    total = data['cart_total']
    need_to_pay_total = max(0, total - limit)

    avail_balance = data['user_balance'] + data['refund_potential']

    if need_to_pay_total > avail_balance:
        new_balance = 0
        real_payment = need_to_pay_total - avail_balance
        msg_extra = f"Вы пополнили и оплатили {real_payment} руб."
    else:
        new_balance = avail_balance - need_to_pay_total
        real_payment = 0
        msg_extra = f"Списано с баланса. Остаток: {new_balance} руб."

    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, data['user_db_id']))

    items_str = ", ".join([i['name'] for i in data['cart']])
    conn.execute('''INSERT INTO orders (user_id, restaurant_id, order_date, items_json, total_price, paid_extra)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                 (data['user_db_id'], data['rest_id'], data['date'], items_str, total, need_to_pay_total))

    conn.commit()
    conn.close()

    await cb.message.edit_text(f"✅ Заказ на {data['date']} оформлен!\n{msg_extra}")
    await state.clear()
    await cb.answer()


@dp.callback_query(F.data == "cancel_order")
async def e_cancel(cb: types.CallbackQuery, state: FSMContext):
    await cb.message.edit_text("Оформление заказа отменено.")
    await state.clear()
    await cb.answer()


# ================== ОТЧЕТЫ ==================

async def send_daily_reports():
    conn = get_db()
    admin = conn.execute("SELECT tg_id FROM users WHERE role='manager' LIMIT 1").fetchone()
    if not admin:
        conn.close()
        return

    today = datetime.now().strftime("%Y-%m-%d")

    df = pd.read_sql_query('''
                           SELECT r.name        as Ресторан,
                                  u.full_name   as ФИО,
                                  u.office      as Офис,
                                  o.items_json  as Блюда,
                                  o.total_price as Сумма
                           FROM orders o
                                    JOIN users u ON o.user_id = u.id
                                    JOIN restaurants r ON o.restaurant_id = r.id
                           WHERE o.order_date = ?
                           ''', conn, params=(today,))
    conn.close()

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


@dp.message(F.text == "📊 Отчет сейчас")
async def manual_report(message: types.Message):
    await message.answer("Формирую отчеты...")
    await send_daily_reports()


# ================== ЗАПУСК ==================

async def main():
    init_db()

    scheduler.add_job(send_daily_reports, 'cron', hour=REPORT_HOUR, minute=REPORT_MINUTE)
    scheduler.start()

    print(f"Bot started! Reports scheduled at {REPORT_HOUR}:{REPORT_MINUTE:02d}")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass