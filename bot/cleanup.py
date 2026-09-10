import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import Message as TelegramMessage

from .db import Database

logger = logging.getLogger(__name__)


class LogSentMessagesMiddleware(BaseRequestMiddleware):
    def __init__(self, db: Database):
        self.db = db

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        if isinstance(result, TelegramMessage):
            try:
                await self.db.log_chat_message(result.chat.id, result.message_id)
            except Exception:
                logger.exception("Failed to log outgoing message")
        return result


async def log_incoming_message(handler, event, data):
    db: Database = data["db"]
    try:
        await db.log_chat_message(event.chat.id, event.message_id)
    except Exception:
        logger.exception("Failed to log incoming message")
    return await handler(event, data)


def _seconds_until_next_midnight(tz: ZoneInfo) -> float:
    now = datetime.now(tz)
    next_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (next_midnight - now).total_seconds()


async def clear_owner_chat(bot: Bot, db: Database) -> None:
    owner = await db.get_owner()
    if not owner:
        return
    message_ids = await db.list_chat_messages(owner)
    for message_id in message_ids:
        try:
            await bot.delete_message(owner, message_id)
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await db.clear_chat_messages(owner)


async def midnight_cleanup_loop(bot: Bot, db: Database, timezone: str) -> None:
    tz = ZoneInfo(timezone)
    while True:
        await asyncio.sleep(_seconds_until_next_midnight(tz))
        try:
            await clear_owner_chat(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Midnight chat cleanup failed")
