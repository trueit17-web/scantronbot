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
                "wallet TEXT, "
                "address TEXT, "
                "amount TEXT, "
                "created_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await db.execute(
                "CREATE TABLE IF NOT EXISTS pending_unknown ("
                "tx_id TEXT PRIMARY KEY, "
                "wallet TEXT, "
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
            await db.execute(
                "CREATE TABLE IF NOT EXISTS wallets ("
                "address TEXT PRIMARY KEY, "
                "added_at TEXT DEFAULT (datetime('now'))"
                ")"
            )
            await self._migrate_add_column(db, "deposits", "wallet", "TEXT")
            await self._migrate_add_column(db, "pending_unknown", "wallet", "TEXT")
            await db.commit()

            # Legacy single-wallet installs stored the watched address in
            # settings("wallet") — fold it into the wallets table once.
            cur = await db.execute("SELECT value FROM settings WHERE key = 'wallet'")
            legacy_wallet = await cur.fetchone()
            if legacy_wallet and legacy_wallet[0]:
                await db.execute(
                    "INSERT OR IGNORE INTO wallets(address) VALUES (?)",
                    (legacy_wallet[0],),
                )
                await db.commit()

    @staticmethod
    async def _migrate_add_column(
        db: aiosqlite.Connection, table: str, column: str, coltype: str
    ) -> None:
        cur = await db.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cur.fetchall()}
        if column not in columns:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")

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

    async def get_owner(self) -> int | None:
        value = await self._get_setting("owner_id")
        return int(value) if value else None

    async def set_owner(self, user_id: int) -> None:
        await self._set_setting("owner_id", str(user_id))

    async def get_last_poll_at(self) -> str | None:
        return await self._get_setting("last_poll_at")

    async def set_last_poll_status(self, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO settings(key, value) VALUES ('last_poll_at', datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=datetime('now')"
            )
            await db.commit()
        await self._set_setting("last_poll_status", status)

    async def get_last_poll_status(self) -> str | None:
        return await self._get_setting("last_poll_status")

    async def get_last_digest_at(self) -> str | None:
        return await self._get_setting("last_digest_at")

    async def set_last_digest_at(self, value: str) -> None:
        await self._set_setting("last_digest_at", value)

    async def get_last_weekly_digest_at(self) -> str | None:
        return await self._get_setting("last_weekly_digest_at")

    async def set_last_weekly_digest_at(self, value: str) -> None:
        await self._set_setting("last_weekly_digest_at", value)

    # --- wallets -----------------------------------------------------

    async def add_wallet(self, address: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO wallets(address) VALUES (?)", (address,)
            )
            await db.commit()

    async def remove_wallet(self, address: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM wallets WHERE address = ?", (address,))
            await db.commit()

    async def list_wallets(self) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT address FROM wallets ORDER BY rowid ASC")
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    # --- contacts ------------------------------------------------------

    async def add_contact(self, address: str, name: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO contacts(address, name) VALUES (?, ?) "
                "ON CONFLICT(address) DO UPDATE SET name=excluded.name",
                (address, name),
            )
            await db.commit()

    async def remove_contact(self, address: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM contacts WHERE address = ?", (address,))
            await db.commit()

    async def get_contact_name(self, address: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT name FROM contacts WHERE address = ?", (address,)
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def get_contacts_by_name(self, name: str) -> list[str]:
        # SQLite's COLLATE NOCASE only folds ASCII, so match case-insensitively
        # in Python instead (needed for Cyrillic and other non-ASCII names).
        target = name.casefold()
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT address, name FROM contacts")
            rows = await cur.fetchall()
        return [address for address, contact_name in rows if contact_name.casefold() == target]

    async def list_contacts(self) -> list[tuple[str, str]]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT address, name FROM contacts ORDER BY name")
            return list(await cur.fetchall())

    async def count_contacts(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM contacts")
            row = await cur.fetchone()
        return row[0] if row else 0

    # --- processed tx dedup ---------------------------------------------

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

    # --- deposits / journal ---------------------------------------------

    async def add_deposit(self, tx_id: str, wallet: str, address: str, amount: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO deposits(tx_id, wallet, address, amount) "
                "VALUES (?, ?, ?, ?)",
                (tx_id, wallet, address, amount),
            )
            await db.commit()

    async def list_deposits(self, limit: int, offset: int) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT d.wallet, d.address, d.amount, d.created_at, c.name "
                "FROM deposits d LEFT JOIN contacts c ON c.address = d.address "
                "ORDER BY d.rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            rows = await cur.fetchall()
        return [
            {
                "wallet": row[0],
                "address": row[1],
                "amount": row[2],
                "created_at": row[3],
                "name": row[4],
            }
            for row in rows
        ]

    async def list_all_deposits(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT d.tx_id, d.wallet, d.address, d.amount, d.created_at, c.name "
                "FROM deposits d LEFT JOIN contacts c ON c.address = d.address "
                "ORDER BY d.rowid ASC"
            )
            rows = await cur.fetchall()
        return [
            {
                "tx_id": row[0],
                "wallet": row[1],
                "address": row[2],
                "amount": row[3],
                "created_at": row[4],
                "name": row[5],
            }
            for row in rows
        ]

    async def count_deposits(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM deposits")
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_deposits_summary_since(self, since: str) -> tuple[int, float]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT COUNT(*), COALESCE(SUM(CAST(amount AS REAL)), 0) "
                "FROM deposits WHERE created_at >= ?",
                (since,),
            )
            row = await cur.fetchone()
        return (row[0], row[1]) if row else (0, 0.0)

    # --- unknown-sender queue --------------------------------------------

    async def add_pending_unknown(
        self, tx_id: str, wallet: str, address: str, amount: str
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO pending_unknown(tx_id, wallet, address, amount) "
                "VALUES (?, ?, ?, ?)",
                (tx_id, wallet, address, amount),
            )
            await db.commit()

    async def get_next_pending_unknown(self) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT tx_id, wallet, address, amount "
                "FROM pending_unknown ORDER BY rowid ASC LIMIT 1"
            )
            row = await cur.fetchone()
        if not row:
            return None
        return {"tx_id": row[0], "wallet": row[1], "address": row[2], "amount": row[3]}

    async def delete_pending_unknown(self, tx_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM pending_unknown WHERE tx_id = ?", (tx_id,))
            await db.commit()

    async def count_pending_unknown(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("SELECT COUNT(*) FROM pending_unknown")
            row = await cur.fetchone()
        return row[0] if row else 0

    # --- chat message log (for the midnight cleanup) ---------------------

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
