from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_ADD = "➕ Добавить"
BTN_WALLET = "👛 Кошелек"
BTN_LOG = "📒 Журнал"
BTN_CANCEL = "❌ Отмена"
BTN_LOG_MORE = "➕ Еще"
BTN_LOG_BACK = "⬅️ Назад"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_WALLET)],
            [KeyboardButton(text=BTN_LOG)],
        ],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )


def log_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_LOG_MORE), KeyboardButton(text=BTN_LOG_BACK)]],
        resize_keyboard=True,
    )
