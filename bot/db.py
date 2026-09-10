import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS contacts (address TEXT PRIMARY KEY, name TEXT)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS processed_tx (tx_id TEXT PRIMARY KEY)"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS deposits ("
                "tx_id TEXT PRIMARY KEY, "
                "address TEXT, "
                "amount TEXT, "
                "created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS pending_unknown ("
                "tx_id TEXT PRIMARY KEY, "
                "address TEXT, "
                "amount TEXT"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS chat_log ("
                "chat_id INTEGER, "
                "message_id INTEGER, "
                "PRIMARY KEY (chat_id, message_id)"
                ")"
            )
            await db.commit()

    async def _get_setting(self, key: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = await cur.fetchone()
            return row[0] if row else None

    async def _set_setting(self, key: str, value: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def get_wallet(self) -> str | None:
        return await self._get_setting("wallet")

    async def set_wallet(self, address: str) -> None:
        await self._set_setting("wallet", address)

    async def get_owner(self) -> int | None:
        value = await self._get_setting("owner_id")
        return int(value) if value else None

    async def set_owner(self, user_id: int) -> None:
        await self._set_setting("owner_id", str(user_id))

    async def add_contact(self, address: str, name: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO contacts(address, name) VALUES (?, ?) "
                "ON CONFLICT(address) DO UPDATE SET name=excluded.name",
                (address, name),
            )
            await db.commit()

    async def get_contact_name(self, address: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT name FROM contacts WHERE address = ?", (address,)
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def list_contacts(self) -> list[tuple[str, str]]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT address, name FROM contacts ORDER BY name")
            return list(await cur.fetchall())

    async def is_tx_processed(self, tx_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT 1 FROM processed_tx WHERE tx_id = ?", (tx_id,)
            )
            row = await cur.fetchone()
            return row is not None

    async def mark_tx_processed(self, tx_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO processed_tx(tx_id) VALUES (?)", (tx_id,)
            )
            await db.commit()

    async def add_deposit(self, tx_id: str, address: str, amount: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO deposits(tx_id, address, amount) VALUES (?, ?, ?)",
                (tx_id, address, amount),
            )
            await db.commit()

    async def list_deposits(self, limit: int, offset: int) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT d.address, d.amount, d.created_at, c.name "
                "FROM deposits d LEFT JOIN contacts c ON c.address = d.address "
                "ORDER BY d.rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cur.fetchall()
        return [
            {"address": row[0], "amount": row[1], "created_at": row[2], "name": row[3]}
            for row in rows
        ]

    async def add_pending_unknown(self, tx_id: str, address: str, amount: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO pending_unknown(tx_id, address, amount) VALUES (?, ?, ?)",
                (tx_id, address, amount),
            )
            await db.commit()

    async def get_next_pending_unknown(self) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT tx_id, address, amount FROM pending_unknown ORDER BY rowid ASC LIMIT 1"
            )
            row = await cur.fetchone()
        if not row:
            return None
        return {"tx_id": row[0], "address": row[1], "amount": row[2]}

    async def delete_pending_unknown(self, tx_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM pending_unknown WHERE tx_id = ?", (tx_id,))
            await db.commit()

    async def log_chat_message(self, chat_id: int, message_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO chat_log(chat_id, message_id) VALUES (?, ?)",
                (chat_id, message_id),
            )
            await db.commit()

    async def list_chat_messages(self, chat_id: int) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT message_id FROM chat_log WHERE chat_id = ? ORDER BY message_id ASC",
                (chat_id,),
            )
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def clear_chat_messages(self, chat_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM chat_log WHERE chat_id = ?", (chat_id,))
            await db.commit()
