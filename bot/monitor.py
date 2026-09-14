import asyncio
import logging

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from . import config
from .db import Database
from .handlers import try_prompt_pending_unknown
from .tron import TronClient
from .utils import format_amount

logger = logging.getLogger(__name__)


def _is_large(raw_amount: float) -> bool:
    threshold = config.LARGE_DEPOSIT_THRESHOLD
    return threshold is not None and raw_amount >= threshold


async def monitor_loop(
    bot: Bot, db: Database, tron: TronClient, storage: BaseStorage, poll_interval: int
) -> None:
    while True:
        try:
            wallets = await db.list_wallets()
            owner = await db.get_owner()
            had_error = False

            if wallets and owner:
                for wallet in wallets:
                    try:
                        transfers = await tron.get_incoming_transfers(wallet)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Failed to fetch transfers for %s", wallet)
                        had_error = True
                        continue

                    for transfer in reversed(transfers):
                        tx_id = transfer.get("transaction_id")
                        if not tx_id or await db.is_tx_processed(tx_id):
                            continue
                        await db.mark_tx_processed(tx_id)

                        sender = transfer["from"]
                        raw_amount = transfer["amount"]
                        amount = format_amount(raw_amount)
                        await db.add_deposit(tx_id, wallet, sender, amount)

                        name = await db.get_contact_name(sender)
                        if name:
                            prefix = "🚨 " if _is_large(raw_amount) else ""
                            text = f"{prefix}+{amount} на {name}."
                            try:
                                await bot.send_message(owner, text)
                            except Exception:
                                logger.exception("Failed to send notification")
                        else:
                            await db.add_pending_unknown(tx_id, wallet, sender, amount)

                state = FSMContext(
                    storage=storage,
                    key=StorageKey(bot_id=bot.id, chat_id=owner, user_id=owner),
                )
                try:
                    await try_prompt_pending_unknown(bot, state, db)
                except Exception:
                    logger.exception("Failed to prompt for unknown sender")

                await db.set_last_poll_status("error" if had_error else "ok")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop iteration failed")
            try:
                await db.set_last_poll_status("error")
            except Exception:
                pass

        await asyncio.sleep(poll_interval)
