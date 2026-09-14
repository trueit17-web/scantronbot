import csv
import io

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, Message

from . import config
from .cleanup import log_incoming_message
from .db import Database
from .keyboards import (
    BTN_ADD,
    BTN_BACK,
    BTN_BALANCE,
    BTN_CANCEL,
    BTN_CONTACTS,
    BTN_CONTACTS_DEL,
    BTN_LOG,
    BTN_LOG_EXPORT,
    BTN_LOG_MORE,
    BTN_WALLET,
    BTN_WALLET_ADD,
    BTN_WALLET_DEL,
    cancel_menu,
    contacts_menu,
    log_menu,
    main_menu,
    wallets_menu,
)
from .tron import TronClient
from .utils import format_amount, is_valid_address, short_address

router = Router()
router.message.outer_middleware(log_incoming_message)

LOG_PAGE_SIZE = 10


class WalletStates(StatesGroup):
    waiting_address = State()
    menu = State()
    waiting_delete_address = State()


class ContactStates(StatesGroup):
    waiting_address = State()
    waiting_name = State()
    menu = State()
    waiting_delete_target = State()


class UnknownSenderStates(StatesGroup):
    waiting_name = State()


class LogStates(StatesGroup):
    viewing = State()


async def _is_authorized(db: Database, user_id: int) -> bool:
    owner = await db.get_owner()
    return owner is None or owner == user_id


def _is_large(amount) -> bool:
    threshold = config.LARGE_DEPOSIT_THRESHOLD
    if threshold is None:
        return False
    try:
        return float(amount) >= threshold
    except (TypeError, ValueError):
        return False


async def _ask_unknown_sender(bot, state: FSMContext, pending: dict) -> None:
    await state.set_state(UnknownSenderStates.waiting_name)
    await state.update_data(
        pending_tx_id=pending["tx_id"],
        address=pending["address"],
        amount=pending["amount"],
    )
    prefix = "🚨 " if _is_large(pending["amount"]) else ""
    await bot.send_message(
        state.key.chat_id,
        f"{prefix}+{pending['amount']} USDT от кого?\n"
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


def _build_export_file(entries: list[dict]) -> BufferedInputFile:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Дата", "Сумма USDT", "Отправитель", "Адрес отправителя", "Кошелек", "Tx"])
    for e in entries:
        writer.writerow(
            [e["created_at"], e["amount"], e["name"] or "", e["address"], e["wallet"] or "", e["tx_id"]]
        )
    data = buf.getvalue().encode("utf-8-sig")
    return BufferedInputFile(data, filename="deposits.csv")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await message.answer("Этот бот уже настроен для другого пользователя.")
        return

    wallets = await db.list_wallets()
    if not wallets:
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
    if not await db.list_wallets():
        await state.set_state(WalletStates.waiting_address)
        await message.answer(
            "Сначала пришлите адрес USDT TRC20-кошелька, за которым нужно наблюдать."
        )
        return
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


@router.message(Command("status"))
async def cmd_status(message: Message, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    wallets = await db.list_wallets()
    last_poll = await db.get_last_poll_at()
    last_status = await db.get_last_poll_status()
    pending = await db.count_pending_unknown()
    contacts = await db.count_contacts()
    deposits = await db.count_deposits()
    lines = [
        "Кошельки ({}): {}".format(
            len(wallets),
            ", ".join(short_address(w) for w in wallets) if wallets else "нет",
        ),
        f"Последний опрос: {last_poll or 'ещё не было'} ({last_status or '—'})",
        f"Неопознанных ждут имени: {pending}",
        f"Связок кошелек → имя: {contacts}",
        f"Всего пополнений в журнале: {deposits}",
    ]
    await message.answer("\n".join(lines))


# --- wallets --------------------------------------------------------------


@router.message(F.text == BTN_WALLET)
async def btn_wallet(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    wallets = await db.list_wallets()
    text = (
        "Отслеживаемые кошельки:\n" + "\n".join(wallets)
        if wallets
        else "Кошельков пока нет."
    )
    await state.set_state(WalletStates.menu)
    await message.answer(text, reply_markup=wallets_menu())


@router.message(WalletStates.menu, F.text == BTN_WALLET_ADD)
async def btn_wallet_add(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    await state.set_state(WalletStates.waiting_address)
    await message.answer(
        "Пришлите адрес нового USDT TRC20-кошелька для наблюдения.",
        reply_markup=cancel_menu(),
    )


@router.message(WalletStates.menu, F.text == BTN_WALLET_DEL)
async def btn_wallet_del(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    wallets = await db.list_wallets()
    if not wallets:
        await message.answer("Нет кошельков для удаления.")
        return
    await state.set_state(WalletStates.waiting_delete_address)
    await message.answer(
        "Отслеживаемые кошельки:\n" + "\n".join(wallets) + "\n\nПришлите адрес кошелька для удаления.",
        reply_markup=cancel_menu(),
    )


@router.message(WalletStates.menu, F.text == BTN_BACK)
async def btn_wallet_back(message: Message, state: FSMContext, db: Database):
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


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

    existing = await db.list_wallets()
    if address in existing:
        await message.answer("Этот кошелек уже отслеживается.")
        return

    is_first_setup = not existing
    await db.add_wallet(address)
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
    await message.answer(f"Кошелек добавлен для наблюдения:\n{address}")
    await _return_to_menu_or_prompt(message, state, db)


@router.message(WalletStates.waiting_delete_address)
async def delete_wallet_address(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    address = (message.text or "").strip()
    if not is_valid_address(address):
        await message.answer("Некорректный адрес. Пришлите корректный адрес USDT TRC20.")
        return

    wallets = await db.list_wallets()
    if address not in wallets:
        await message.answer("Такой кошелек не отслеживается.")
        return

    await db.remove_wallet(address)
    await state.clear()
    text = f"Кошелек удалён из наблюдения:\n{address}"
    if len(wallets) == 1:
        text += "\n\nОтслеживаемых кошельков не осталось — добавьте новый через «➕ Добавить кошелек»."
    await message.answer(text)
    await _return_to_menu_or_prompt(message, state, db)


# --- adding a wallet→name contact ------------------------------------------


@router.message(F.text == BTN_ADD)
async def btn_add_contact(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    if not await db.list_wallets():
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


# --- browsing / deleting contacts ------------------------------------------


async def _show_contacts(message: Message, state: FSMContext, db: Database) -> None:
    contacts = await db.list_contacts()
    text = (
        "\n".join(f"{name} — {short_address(address)}" for address, name in contacts)
        if contacts
        else "Список связок пуст."
    )
    await state.set_state(ContactStates.menu)
    await message.answer(text, reply_markup=contacts_menu())


@router.message(Command("contacts"))
async def cmd_contacts(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    await _show_contacts(message, state, db)


@router.message(F.text == BTN_CONTACTS)
async def btn_contacts(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    await _show_contacts(message, state, db)


@router.message(ContactStates.menu, F.text == BTN_CONTACTS_DEL)
async def btn_contacts_del(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    if not await db.list_contacts():
        await message.answer("Список связок пуст.")
        return
    await state.set_state(ContactStates.waiting_delete_target)
    await message.answer(
        "Пришлите имя или адрес связки, которую нужно удалить.",
        reply_markup=cancel_menu(),
    )


@router.message(ContactStates.menu, F.text == BTN_BACK)
async def btn_contacts_back(message: Message, state: FSMContext, db: Database):
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


@router.message(ContactStates.waiting_delete_target)
async def delete_contact_target(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        await state.clear()
        return

    target = (message.text or "").strip()
    if not target:
        await message.answer("Пришлите имя или адрес связки.")
        return

    if is_valid_address(target):
        name = await db.get_contact_name(target)
        if name is None:
            await message.answer("Такая связка не найдена.")
            return
        await db.remove_contact(target)
        await state.clear()
        await message.answer(f"Связка удалена: {name} — {short_address(target)}")
        await _return_to_menu_or_prompt(message, state, db)
        return

    matches = await db.get_contacts_by_name(target)
    if not matches:
        await message.answer("Связка с таким именем не найдена. Пришлите имя или адрес.")
        return
    if len(matches) > 1:
        lines = "\n".join(short_address(a) for a in matches)
        await message.answer(
            f"Найдено несколько связок с именем «{target}», пришлите точный адрес:\n{lines}"
        )
        return

    address = matches[0]
    await db.remove_contact(address)
    await state.clear()
    await message.answer(f"Связка удалена: {target} — {short_address(address)}")
    await _return_to_menu_or_prompt(message, state, db)


# --- unknown sender ---------------------------------------------------------


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
    prefix = "🚨 " if _is_large(amount) else ""
    await message.answer(f"{prefix}+{amount} на {name}.")
    await _return_to_menu_or_prompt(message, state, db)


# --- journal / log -----------------------------------------------------------


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


@router.message(LogStates.viewing, F.text == BTN_LOG_EXPORT)
async def btn_log_export(message: Message, state: FSMContext, db: Database):
    if not await _is_authorized(db, message.from_user.id):
        return
    entries = await db.list_all_deposits()
    if not entries:
        await message.answer("Пополнений пока нет.")
        return
    document = _build_export_file(entries)
    await message.answer_document(document, caption=f"Экспорт журнала: {len(entries)} записей")


@router.message(LogStates.viewing, F.text == BTN_BACK)
async def btn_log_back(message: Message, state: FSMContext, db: Database):
    await state.clear()
    await _return_to_menu_or_prompt(message, state, db)


# --- balance -----------------------------------------------------------------


@router.message(Command("balance"))
@router.message(F.text == BTN_BALANCE)
async def cmd_balance(message: Message, db: Database, tron: TronClient):
    if not await _is_authorized(db, message.from_user.id):
        return
    wallets = await db.list_wallets()
    if not wallets:
        await message.answer("Нет кошельков для наблюдения.")
        return

    lines = []
    for wallet in wallets:
        try:
            balance = await tron.get_usdt_balance(wallet)
            lines.append(f"{short_address(wallet)}: {format_amount(balance)} USDT")
        except Exception:
            lines.append(f"{short_address(wallet)}: не удалось получить баланс")
    await message.answer("\n".join(lines))
