from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_ADD = "➕ Добавить"
BTN_WALLET = "👛 Кошелек"
BTN_CANCEL = "❌ Отмена"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_WALLET)]],
        resize_keyboard=True,
    )


def cancel_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_CANCEL)]],
        resize_keyboard=True,
    )
