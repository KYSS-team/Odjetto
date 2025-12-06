from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from config import ADMIN_PASSWORD, REPORT_TIME
from db import User, get_session
from keyboards import kb_employee, kb_manager
from states import AuthStates

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    with get_session() as session:
        user = session.scalars(select(User).where(User.tg_id == message.from_user.id)).first()

    if user:
        if user.role == "manager":
            await message.answer(
                f"👨‍💼 Панель менеджера. Отчеты настроены на {REPORT_TIME.hour}:{REPORT_TIME.minute:02d}",
                reply_markup=kb_manager(),
            )
        else:
            await message.answer(
                f"👋 Привет, {user.full_name}! Ваш баланс: {user.balance} руб.", reply_markup=kb_employee()
            )
    else:
        await message.answer("🔒 Введите пароль доступа (admin) или токен, выданный менеджером:")
        await state.set_state(AuthStates.waiting_for_password)


@router.message(AuthStates.waiting_for_password)
async def process_auth(message: types.Message, state: FSMContext):
    text = message.text.strip()
    with get_session() as session:
        if text == ADMIN_PASSWORD:
            role, name = "manager", "Главный Менеджер"
            user = session.scalars(select(User).where(User.tg_id == message.from_user.id)).first()
            if user:
                user.full_name = name
                user.role = role
            else:
                session.add(User(tg_id=message.from_user.id, full_name=name, role=role))
            session.commit()
        else:
            user_invite = session.scalars(
                select(User).where(User.auth_token == text, User.tg_id.is_(None))
            ).first()
            if user_invite:
                role, name = "employee", user_invite.full_name
                user_invite.tg_id = message.from_user.id
                user_invite.auth_token = None
                user_invite.role = role
                session.commit()
            else:
                await message.answer("⛔ Неверный пароль или токен уже использован.")
                return

    await message.answer(
        f"✅ Успешно! Вы вошли как {name} ({role.upper()}).",
        reply_markup=kb_manager() if role == "manager" else kb_employee(),
    )
    await state.clear()
