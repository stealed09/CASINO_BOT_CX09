import time
import asyncio
from functools import wraps
from aiogram.types import Message, CallbackQuery
from database import db
from utils.logger import logger

cooldown_cache: dict = {}


def cooldown(seconds: int = 3):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            msg = None
            for a in args:
                if isinstance(a, (Message, CallbackQuery)):
                    msg = a
                    break
            if msg is None:
                return await func(*args, **kwargs)

            user_id = msg.from_user.id if msg.from_user else 0
            key = f"{user_id}:{func.__name__}"
            now = time.time()

            if key in cooldown_cache and (now - cooldown_cache[key]) < seconds:
                remaining = seconds - (now - cooldown_cache[key])
                try:
                    if isinstance(msg, Message):
                        await msg.answer(f"⏳ Please wait {remaining:.1f}s before using this again.")
                    else:
                        await msg.answer(f"⏳ Please wait {remaining:.1f}s before using this again.", show_alert=True)
                except:
                    pass
                return
            cooldown_cache[key] = now
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def admin_only(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        from config import ADMIN_IDS
        msg = None
        for a in args:
            if isinstance(a, (Message, CallbackQuery)):
                msg = a
                break
        if msg is None:
            return
        user_id = msg.from_user.id if msg.from_user else 0
        if user_id not in ADMIN_IDS:
            try:
                if isinstance(msg, Message):
                    await msg.answer("🚫 Admin only command.")
                else:
                    await msg.answer("🚫 Admin only.", show_alert=True)
            except:
                pass
            return
        return await func(*args, **kwargs)
    return wrapper


def registered_only(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        msg = None
        for a in args:
            if isinstance(a, (Message, CallbackQuery)):
                msg = a
                break
        if msg is None:
            return
        user_id = msg.from_user.id if msg.from_user else 0
        user = await db.get_user(user_id)
        if not user:
            try:
                if isinstance(msg, Message):
                    await msg.answer("❌ Please /start first to register.")
                else:
                    await msg.answer("❌ Please /start first.", show_alert=True)
            except:
                pass
            return
        return await func(*args, **kwargs)
    return wrapper
