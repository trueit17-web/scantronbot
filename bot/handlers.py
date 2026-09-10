from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .db import Database
from .keyboards import BTN_ADD, BTN_CANCEL, BTN_WALLET, cancel_menu, main_menu
from .tron import TronClient
from .utils import is_valid_address, short_address

router = Router()


class WalletStates(StatesGroup):
    waiting_address = State()


class ContactStates(StatesGroup):
    waiting_address = State()
    waiting_name = State()


async def _is_authorized(db: Database, user_id: int) -> bool:
    owner = await db.get_owner()
    return owner is None or owner == user_id


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
    await message.answer("Главное меню:", reply_markup=main_menu())


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu())


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
    await message.answer("Главное меню:", reply_markup=main_menu())


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
    await message.answer(
        f"Кошелек для наблюдения установлен:\n{address}", reply_markup=main_menu()
    )


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
        await message.answer("Что-то пошло не так, начните заново.", reply_markup=main_menu())
        return

    name = name[:64]
    await db.add_contact(address, name)
    await state.clear()
    await message.answer(
        f"Сохранено: {short_address(address)} → {name}", reply_markup=main_menu()
    )
