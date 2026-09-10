import asyncio
import logging

from aiogram import Bot

from .db import Database
from .tron import TronClient
from .utils import short_address

logger = logging.getLogger(__name__)


async def monitor_loop(bot: Bot, db: Database, tron: TronClient, poll_interval: int) -> None:
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
                    name = await db.get_contact_name(sender)
                    label = name if name else short_address(sender)
                    text = (
                        "💰 Новое поступление USDT (TRC20)\n"
                        f"Сумма: {transfer['amount']} USDT\n"
                        f"От: {label}\n"
                        f"Адрес: {sender}\n"
                        f"Tx: {tx_id}"
                    )
                    try:
                        await bot.send_message(owner, text)
                    except Exception:
                        logger.exception("Failed to send notification")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Monitor loop iteration failed")

        await asyncio.sleep(poll_interval)
