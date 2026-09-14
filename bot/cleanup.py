import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.types import Message as TelegramMessage

from .db import Database
from .utils import format_amount

logger = logging.getLogger(__name__)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


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


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime(_TS_FORMAT)


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


def backup_database(db_path: str, backup_dir: str, retention_days: int) -> None:
    if not os.path.exists(db_path):
        return
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dest = os.path.join(backup_dir, f"bot-{stamp}.db")
    shutil.copyfile(db_path, dest)

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for fname in os.listdir(backup_dir):
        if not (fname.startswith("bot-") and fname.endswith(".db")):
            continue
        date_part = fname[len("bot-") : -len(".db")]
        try:
            file_date = datetime.strptime(date_part, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                os.remove(os.path.join(backup_dir, fname))
            except OSError:
                logger.exception("Failed to remove old backup %s", fname)


async def _digest_text(db: Database, since: str, label: str) -> str:
    count, total = await db.get_deposits_summary_since(since)
    if count == 0:
        return f"📊 {label}: поступлений не было."
    return f"📊 {label}: {count} поступ. на сумму {format_amount(total)} USDT."


async def _run_midnight_tasks(
    bot: Bot,
    db: Database,
    db_path: str,
    backup_dir: str,
    backup_retention_days: int,
) -> None:
    try:
        await asyncio.to_thread(backup_database, db_path, backup_dir, backup_retention_days)
    except Exception:
        logger.exception("Database backup failed")

    owner = await db.get_owner()
    digest_lines: list[str] = []

    if owner:
        now = _utc_now_str()

        last_daily = await db.get_last_digest_at()
        since_daily = last_daily or (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).strftime(_TS_FORMAT)
        digest_lines.append(await _digest_text(db, since_daily, "За сутки"))
        await db.set_last_digest_at(now)

        last_weekly = await db.get_last_weekly_digest_at()
        if not last_weekly:
            await db.set_last_weekly_digest_at(now)
        else:
            last_weekly_dt = datetime.strptime(last_weekly, _TS_FORMAT).replace(
                tzinfo=timezone.utc
            )
            if datetime.now(timezone.utc) - last_weekly_dt >= timedelta(days=7):
                digest_lines.append(await _digest_text(db, last_weekly, "За неделю"))
                await db.set_last_weekly_digest_at(now)

    await clear_owner_chat(bot, db)

    if owner and digest_lines:
        try:
            await bot.send_message(owner, "\n".join(digest_lines))
        except Exception:
            logger.exception("Failed to send digest")


async def midnight_tasks_loop(
    bot: Bot,
    db: Database,
    timezone_name: str,
    db_path: str,
    backup_dir: str,
    backup_retention_days: int,
) -> None:
    tz = ZoneInfo(timezone_name)
    while True:
        await asyncio.sleep(_seconds_until_next_midnight(tz))
        try:
            await _run_midnight_tasks(bot, db, db_path, backup_dir, backup_retention_days)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Midnight tasks failed")
