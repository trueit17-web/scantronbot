import asyncio
import logging
import os

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from . import config
from .db import Database
from .handlers import router
from .monitor import monitor_loop
from .tron import TronClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    db_dir = os.path.dirname(config.DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    db = Database(config.DB_PATH)
    await db.init()

    if config.OWNER_ID and await db.get_owner() is None:
        await db.set_owner(config.OWNER_ID)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    dp.include_router(router)

    await bot.set_my_commands(
        [
            {"command": "start", "description": "Запуск / настройка"},
            {"command": "menu", "description": "Главное меню"},
            {"command": "contacts", "description": "Список связок кошелек-имя"},
            {"command": "cancel", "description": "Отменить текущее действие"},
        ]
    )

    async with aiohttp.ClientSession() as session:
        tron = TronClient(session, api_key=config.TRON_API_KEY)
        monitor_task = asyncio.create_task(
            monitor_loop(bot, db, tron, storage, config.POLL_INTERVAL)
        )
        try:
            await dp.start_polling(bot, db=db, tron=tron)
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
