import aiosqlite
import asyncio
import os
from datetime import datetime
from typing import Optional, List, Dict
from config import DB_PATH
from utils.logger import logger


class Database:
    def __init__(self):
        self.db_path = DB_PATH
        self._lock = asyncio.Lock()

    async def init(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT DEFAULT '',
                    balance REAL DEFAULT 0.0,
                    referral_id INTEGER DEFAULT NULL,
                    referral_earnings REAL DEFAULT 0.0,
                    total_wagered REAL DEFAULT 0.0,
                    join_date TEXT DEFAULT '',
                    bonus_eligible INTEGER DEFAULT 0,
                    bonus_warned INTEGER DEFAULT 0,
                    warn_time TEXT DEFAULT NULL,
                    last_weekly TEXT DEFAULT NULL,
                    last_monthly TEXT DEFAULT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'completed',
                    date TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS withdrawals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    upi_id TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    amount REAL NOT NULL,
                    txn_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'pending',
                    date TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS balance_locks (
                    user_id INTEGER PRIMARY KEY,
                    locked_amount REAL DEFAULT 0.0
                )
            """)

            defaults = [
                ("min_withdrawal", "100"),
                ("withdraw_enabled", "1"),
                ("weekly_bonus", "50"),
                ("monthly_bonus", "200"),
                ("bonus_mode", "fixed"),
                ("upi_id", "notset@upi"),
                ("upi_qr", ""),
                ("star_payment_id", ""),
                ("bot_username_tag", ""),   # admin sets this e.g. @CasinoBot
            ]
            for key, value in defaults:
                await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

            await db.commit()
        logger.info("Database initialized.")

    async def get_user(self, user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def create_user(self, user_id: int, username: str, referral_id: Optional[int] = None) -> bool:
        try:
            async with self._lock:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute(
                        """INSERT OR IGNORE INTO users
                        (user_id, username, balance, referral_id, referral_earnings,
                         total_wagered, join_date, bonus_eligible, bonus_warned, warn_time,
                         last_weekly, last_monthly)
                        VALUES (?, ?, 0.0, ?, 0.0, 0.0, ?, 0, 0, NULL, NULL, NULL)""",
                        (user_id, username or "", referral_id, datetime.now().isoformat())
                    )
                    await db.commit()
            return True
        except Exception as e:
            logger.error(f"create_user error: {e}")
            return False

    async def update_balance(self, user_id: int, amount: float) -> bool:
        try:
            async with self._lock:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    await db.commit()
            return True
        except Exception as e:
            logger.error(f"update_balance error: {e}")
            return False

    async def set_balance(self, user_id: int, amount: float) -> bool:
        try:
            async with self._lock:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id))
                    await db.commit()
            return True
        except Exception as e:
            logger.error(f"set_balance error: {e}")
            return False

    async def update_wagered(self, user_id: int, amount: float):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET total_wagered = total_wagered + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()

    async def update_username(self, user_id: int, username: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET username = ? WHERE user_id = ?", (username or "", user_id))
            await db.commit()

    async def add_transaction(self, user_id: int, type_: str, amount: float, status: str = "completed"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO transactions (user_id, type, amount, status, date) VALUES (?, ?, ?, ?, ?)",
                (user_id, type_, amount, status, datetime.now().isoformat())
            )
            await db.commit()

    async def get_transactions(self, user_id: int, limit: int = 10) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC LIMIT ?", (user_id, limit)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def create_withdrawal(self, user_id: int, amount: float, upi_id: str) -> int:
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(
                    "INSERT INTO withdrawals (user_id, amount, upi_id, status, date) VALUES (?, ?, ?, 'pending', ?)",
                    (user_id, amount, upi_id, datetime.now().isoformat())
                )
                await db.commit()
                return cur.lastrowid

    async def get_pending_withdrawals(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY date ASC") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def update_withdrawal_status(self, wid: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE withdrawals SET status=? WHERE id=?", (status, wid))
            await db.commit()

    async def get_withdrawal(self, wid: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def create_deposit(self, user_id: int, method: str, amount: float, txn_id: str = "") -> int:
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                cur = await db.execute(
                    "INSERT INTO deposits (user_id, method, amount, txn_id, status, date) VALUES (?, ?, ?, ?, 'pending', ?)",
                    (user_id, method, amount, txn_id, datetime.now().isoformat())
                )
                await db.commit()
                return cur.lastrowid

    async def get_pending_deposits(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM deposits WHERE status='pending' ORDER BY date ASC") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def update_deposit_status(self, did: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE deposits SET status=? WHERE id=?", (status, did))
            await db.commit()

    async def get_deposit(self, did: int) -> Optional[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM deposits WHERE id=?", (did,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_setting(self, key: str) -> Optional[str]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
                row = await cur.fetchone()
                return row["value"] if row else None

    async def set_setting(self, key: str, value: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
            await db.commit()

    async def get_all_users(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users") as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def lock_balance(self, user_id: int, amount: float) -> bool:
        try:
            async with self._lock:
                async with aiosqlite.connect(self.db_path) as db:
                    await db.execute("INSERT OR REPLACE INTO balance_locks (user_id, locked_amount) VALUES (?, ?)", (user_id, amount))
                    await db.commit()
            return True
        except Exception as e:
            logger.error(f"lock_balance error: {e}")
            return False

    async def unlock_balance(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM balance_locks WHERE user_id=?", (user_id,))
            await db.commit()

    async def is_balance_locked(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM balance_locks WHERE user_id=?", (user_id,)) as cur:
                return await cur.fetchone() is not None

    async def update_referral_earnings(self, referral_id: int, amount: float):
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET referral_earnings=referral_earnings+?, balance=balance+? WHERE user_id=?",
                    (amount, amount, referral_id)
                )
                await db.commit()

    async def get_referral_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users WHERE referral_id=?", (user_id,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def set_bonus_eligible(self, user_id: int, value: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET bonus_eligible=? WHERE user_id=?", (value, user_id))
            await db.commit()

    async def set_warn(self, user_id: int, warned: int, warn_time: Optional[str]):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE users SET bonus_warned=?, warn_time=? WHERE user_id=?", (warned, warn_time, user_id))
            await db.commit()

    async def reset_bonus_progress(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET bonus_eligible=0, bonus_warned=0, warn_time=NULL, join_date=?, last_weekly=NULL, last_monthly=NULL WHERE user_id=?",
                (datetime.now().isoformat(), user_id)
            )
            await db.commit()

    async def update_last_bonus(self, user_id: int, bonus_type: str):
        col = "last_weekly" if bonus_type == "weekly" else "last_monthly"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE users SET {col}=? WHERE user_id=?", (datetime.now().isoformat(), user_id))
            await db.commit()


db = Database()
