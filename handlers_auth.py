from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from config import ADMIN_PASSWORD, REPORT_TIME
from db import get_db
from keyboards import kb_employee, kb_manager
from states import AuthStates

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE tg_id = ?", (message.from_user.id,)).fetchone()

    if user:
        if user["role"] == "manager":
            await message.answer(
                f"👨‍💼 Панель менеджера. Отчеты настроены на {REPORT_TIME.hour}:{REPORT_TIME.minute:02d}",
                reply_markup=kb_manager(),
            )
        else:
            await message.answer(
                f"👋 Привет, {user['full_name']}! Ваш баланс: {user['balance']} руб.", reply_markup=kb_employee()
            )
    else:
        await message.answer("🔒 Введите пароль доступа (admin) или токен, выданный менеджером:")
        await state.set_state(AuthStates.waiting_for_password)


@router.message(AuthStates.waiting_for_password)
async def process_auth(message: types.Message, state: FSMContext):
    text = message.text.strip()
    with get_db() as conn:
        if text == ADMIN_PASSWORD:
            role, name = "manager", "Главный Менеджер"
            conn.execute(
                "INSERT OR REPLACE INTO users (tg_id, full_name, role) VALUES (?, ?, ?)",
                (message.from_user.id, name, role),
            )
            conn.commit()
        else:
            user_invite = conn.execute(
                "SELECT id, full_name, office FROM users WHERE auth_token = ? AND tg_id IS NULL", (text,)
            ).fetchone()
            if user_invite:
                role, name = "employee", user_invite["full_name"]
                conn.execute(
                    "UPDATE users SET tg_id = ?, auth_token = NULL, role = ? WHERE id = ?",
                    (message.from_user.id, role, user_invite["id"]),
                )
                conn.commit()
            else:
                await message.answer("⛔ Неверный пароль или токен уже использован.")
                return

    await message.answer(
        f"✅ Успешно! Вы вошли как {name} ({role.upper()}).",
        reply_markup=kb_manager() if role == "manager" else kb_employee(),
    )
    await state.clear()
