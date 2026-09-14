from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_ADD = "➕ Добавить"
BTN_WALLET = "👛 Кошельки"
BTN_LOG = "📒 Журнал"
BTN_CONTACTS = "📇 Контакты"
BTN_BALANCE = "💰 Баланс"
BTN_CANCEL = "❌ Отмена"

BTN_LOG_MORE = "➕ Еще"
BTN_LOG_EXPORT = "📤 Экспорт"
BTN_BACK = "⬅️ Назад"

BTN_WALLET_ADD = "➕ Добавить кошелек"
BTN_WALLET_DEL = "🗑 Удалить кошелек"

BTN_CONTACTS_DEL = "🗑 Удалить связку"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADD), KeyboardButton(text=BTN_WALLET)],
            [KeyboardButton(text=BTN_LOG), KeyboardButton(text=BTN_CONTACTS)],
            [KeyboardButton(text=BTN_BALANCE)],
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
        keyboard=[
            [KeyboardButton(text=BTN_LOG_MORE), KeyboardButton(text=BTN_LOG_EXPORT)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def wallets_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_WALLET_ADD), KeyboardButton(text=BTN_WALLET_DEL)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
    )


def contacts_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CONTACTS_DEL)],
            [KeyboardButton(text=BTN_BACK)],
        ],
        resize_keyboard=True,
    )
