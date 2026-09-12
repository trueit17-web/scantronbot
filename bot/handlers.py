from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .db import Database
from .keyboards import (
    BTN_ADD,
    BTN_CANCEL,
    BTN_LOG,
    BTN_LOG_BACK,
    BTN_LOG_MORE,
    BTN_WALLET,
    cancel_menu,
    log_menu,
    main_menu,
)
from .cleanup import log_incoming_message
from .tron import TronClient
from .utils import is_valid_address, short_address

router = Router()
router.message.outer_middleware(log_incoming_message)

LOG_PAGE_SIZE = 10


class WalletStates(StatesGroup):
    waiting_address = State()


class ContactStates(StatesGroup):
    waiting_address = State()
    waiting_name = State()


class UnknownSenderStates(StatesGroup):
    waiting_name = State()


class LogStates(StatesGroup):
    viewing = State()


async def _is_authorized(db: Database, user_id: int) -> bool:
    owner = await db.get_owner()
    return owner is None or owner == user_id


async def _ask_unknown_sender(bot, state: FSMContext, pending: dict) -> None:
    await state.set_state(UnknownSenderStates.waiting_name)
    await state.update_data(
        pending_tx_id=pending["tx_id"],
        address=pending["address"],
        amount=pending["amount"],
    )
    await bot.send_message(
        state.key.chat_id,
        f"+{pending['amount']} USDT от кого?\n"
        f"Адрес: {short_address(pending['address'])}\n"
        "Пришлите имя отправителя.",
        reply_markup=cancel_menu(),
    )


async def try_prompt_pending_unknown(bot, state: FSMContext, db: Database) -> bool:
    if await state.get_state() is not None:
        return False
    pending = await db.get_next_pending_unknown()
    if not pending:
        return False
    await _ask_unknown_sender(bot, state, pending)
    return True


async def _return_to_menu_or_prompt(message: Message, state: FSMContext, db: Database) -> None:
    if not await try_prompt_pending_unknown(message.bot, state, db):
        await message.answer("Главное меню:", reply_markup=main_menu())


def _format_deposit_line(idx: int, entry: dict) -> str:
    label = entry["name"] or short_address(entry["address"])
    return f"{idx}. {entry['amount']} USDT — {label} ({entry['created_at']})"


async def _render_log_page(db: Database, offset: int) -> tuple[str, list[dict]]:
    entries = await db.list_deposits(limit=LOG_PAGE_SIZE, offset=offset)
    if not entries:
        text = "Пополнений пока нет." if offset == 0 else "Больше пополнений нет."
        return text, entries
    lines = [_format_deposit_line(offset + i + 1, e) for i, e in enumerate(entries)]
    return "\n".join(lines), entries


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await message.answer("Этот бот уже настроен для другого пользователя.")
        return

    wallet = await db.get_wallet()
    if wallet is None:
        await state.set_state(WalletStates.waiting_address)
        await message.answer(
            "Здравствуйте! Пришлите адрес USDT TRC20-кошелька, за которым нужно наблюдать."
        )
        return

    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext, db: Database):
    current_state = await state.get_state()
    if current_state == UnknownSenderStates.waiting_name.state:
        data = await state.get_data()
        tx_id = data.get("pending_tx_id")
        if tx_id:
            await db.delete_pending_unknown(tx_id)
    await state.clear()
    await message.answer("Отменено.")
    await _return_to_menu_or_prompt(message, state, db)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    if await db.get_wallet() is None:
        await state.set_state(WalletStates.waiting_address)
        await message.answer(
            "Сначала пришлите адрес USDT TRC20-кошелька, за которым нужно наблюдать."
        )
        return
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


@router.message(Command("contacts"))
async def cmd_contacts(message: Message, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    contacts = await db.list_contacts()
    if not contacts:
        await message.answer("Список связок пуст.")
        return
    lines = [f"{name} — {short_address(address)}" for address, name in contacts]
    await message.answer("\n".join(lines))


@router.message(F.text == BTN_WALLET)
async def btn_wallet(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    current = await db.get_wallet()
    await state.set_state(WalletStates.waiting_address)
    await message.answer(
        f"Текущий кошелек: {current}\n"
        "Пришлите новый адрес USDT TRC20 или нажмите «Отмена».",
        reply_markup=cancel_menu(),
    )


@router.message(WalletStates.waiting_address)
async def set_wallet_address(
    message: Message, state: FSMContext, db: Database, tron: TronClient
):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    address = (message.text or "").strip()
    if not is_valid_address(address):
        await message.answer(
            "Некорректный адрес. Пришлите корректный адрес USDT TRC20 "
            "(начинается с T, 34 символа)."
        )
        return

    is_first_setup = await db.get_wallet() is None
    await db.set_wallet(address)
    if is_first_setup:
        await db.set_owner(message.from_user.id)

    try:
        recent = await tron.get_incoming_transfers(address)
        for transfer in recent:
            tx_id = transfer.get("transaction_id")
            if tx_id:
                await db.mark_tx_processed(tx_id)
    except Exception:
        pass

    await state.clear()
    await message.answer(f"Кошелек для наблюдения установлен:\n{address}")
    await _return_to_menu_or_prompt(message, state, db)


@router.message(F.text == BTN_ADD)
async def btn_add_contact(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    if await db.get_wallet() is None:
        await message.answer("Сначала укажите кошелек для наблюдения.")
        return
    await state.set_state(ContactStates.waiting_address)
    await message.answer(
        "Пришлите адрес отправителя (TRC20), который нужно связать с именем.",
        reply_markup=cancel_menu(),
    )


@router.message(ContactStates.waiting_address)
async def add_contact_address(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    address = (message.text or "").strip()
    if not is_valid_address(address):
        await message.answer("Некорректный адрес. Пришлите корректный адрес USDT TRC20.")
        return

    await state.update_data(address=address)
    await state.set_state(ContactStates.waiting_name)
    await message.answer("Теперь пришлите имя для этого адреса.")


@router.message(ContactStates.waiting_name)
async def add_contact_name(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не может быть пустым. Пришлите имя.")
        return

    data = await state.get_data()
    address = data.get("address")
    if not address:
        await state.clear()
        await _return_to_menu_or_prompt(message, state, db)
        return

    name = name[:64]
    await db.add_contact(address, name)
    await state.clear()
    await message.answer(f"Сохранено: {short_address(address)} → {name}")
    await _return_to_menu_or_prompt(message, state, db)


@router.message(UnknownSenderStates.waiting_name)
async def set_unknown_sender_name(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    name = (message.text or "").strip()
    if not name:
        await message.answer("Имя не может быть пустым. Пришлите имя.")
        return

    data = await state.get_data()
    address = data.get("address")
    tx_id = data.get("pending_tx_id")
    amount = data.get("amount")
    if not address:
        await state.clear()
        await _return_to_menu_or_prompt(message, state, db)
        return

    name = name[:64]
    await db.add_contact(address, name)
    if tx_id:
        await db.delete_pending_unknown(tx_id)
    await state.clear()
    await message.answer(f"+{amount} на {name}.")
    await _return_to_menu_or_prompt(message, state, db)


@router.message(F.text == BTN_LOG)
async def btn_log(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    text, entries = await _render_log_page(db, 0)
    await state.set_state(LogStates.viewing)
    await state.update_data(offset=len(entries))
    await message.answer(text, reply_markup=log_menu())


@router.message(LogStates.viewing, F.text == BTN_LOG_MORE)
async def btn_log_more(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    data = await state.get_data()
    offset = data.get("offset", 0)
    text, entries = await _render_log_page(db, offset)
    if entries:
        await state.update_data(offset=offset + len(entries))
    await message.answer(text, reply_markup=log_menu())


@router.message(LogStates.viewing, F.text == BTN_LOG_BACK)
async def btn_log_back(message: Message, state: FSMContext, db: Database):
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)
