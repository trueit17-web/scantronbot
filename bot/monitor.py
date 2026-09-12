import asyncio
import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from .db import Database
from .handlers import try_prompt_pending_unknown
from .tron import TronClient
from .utils import format_amount

logger = logging.getLogger(__name__)


async def monitor_loop(
    bot: Bot, db: Database, tron: TronClient, storage: BaseStorage, poll_interval: int
) -> None:
    while True:
        try:
            wallet = await db.get_wallet()
            owner = await db.get_owner()
            if wallet and owner:
                transfers = await tron.get_incoming_transfers(wallet)
                for transfer in reversed(transfers):
                    tx_id = transfer.get("transaction_id")
                    if not tx_id or await db.is_tx_processed(tx_id):
                        continue
                    await db.mark_tx_processed(tx_id)

                    sender = transfer["from"]
                    amount = format_amount(transfer["amount"])
                    await db.add_deposit(tx_id, sender, amount)

                    name = await db.get_contact_name(sender)
                    if name:
                        text = f"+{amount} на {name}."
                        try:
                            await bot.send_message(owner, text)
                        except Exception:
                            logger.exception("Failed to send notification")
                    else:
                        await db.add_pending_unknown(tx_id, sender, amount)

                state = FSMContext(
                    storage=storage,
                    key=StorageKey(bot_id=bot.id, chat_id=owner, user_id=owner),
                )
                try:
                    await try_prompt_pending_unknown(bot, state, db)
                except Exception:
                    logger.exception("Failed to prompt for unknown sender")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop iteration failed")

        await asyncio.sleep(poll_interval)
