from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def kb_manager():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👥 Управление сотрудниками"), KeyboardButton(text="🥗 Управление меню")],
            [KeyboardButton(text="⚙️ Лимит бюджета"), KeyboardButton(text="📊 Отчет сейчас")],
        ],
        resize_keyboard=True,
    )


def kb_employee():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🍱 Сделать заказ")], [KeyboardButton(text="👤 Мой профиль / Баланс")]],
        resize_keyboard=True,
    )


def kb_cancel():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_action")]]
    )


def kb_payment_placeholder():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Подтвердить оплату", callback_data="confirm_topup")]]
    )
