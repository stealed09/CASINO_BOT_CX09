import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, REFERRAL_PERCENT
from database import db
from utils.logger import logger
from utils.decorators import cooldown, admin_only, registered_only
from utils.helpers import validate_amount, format_balance
from ui.keyboards import (
    main_menu_kb, games_menu_kb, wallet_menu_kb, deposit_menu_kb,
    back_to_main_kb, back_kb
)
from ui.messages import (
    main_menu_text, wallet_text, referral_text, bonus_text,
    history_text, error_text, success_text, SEP
)
from games.dice import play_dice
from games.basketball import play_basketball
from games.soccer import play_soccer
from games.bowling import play_bowling
from games.darts import play_darts
from games.limbo import play_limbo
from games.coinflip import prompt_coinflip, play_coinflip
from payments.deposit import (
    show_deposit_stars, show_deposit_upi,
    process_stars_deposit, process_upi_deposit,
    approve_deposit, reject_deposit
)
from payments.withdraw import process_withdrawal, approve_withdrawal, reject_withdrawal
from admin.panel import (
    show_admin_panel, show_pending_deposits, show_pending_withdrawals,
    show_admin_stats, show_admin_settings,
    cmd_set_min_withdraw, cmd_withdraw_toggle,
    cmd_add_balance, cmd_remove_balance, cmd_set_balance,
    cmd_set_bonus, cmd_broadcast, cmd_set_bonus_eligible
)


# ─── FSM States ───────────────────────────────────────────────────────────────

class GameState(StatesGroup):
    waiting_bet = State()
    waiting_game_type = State()


class DepositState(StatesGroup):
    waiting_stars_amount = State()
    waiting_upi_info = State()


class WithdrawState(StatesGroup):
    waiting_amount = State()
    waiting_upi = State()
    waiting_upi_combined = State()


class SupportState(StatesGroup):
    waiting_message = State()


class BroadcastState(StatesGroup):
    waiting_message = State()


# ─── Bot & Dispatcher ─────────────────────────────────────────────────────────

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(user_id)

    args = message.text.split()
    referral_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            ref = int(args[1][4:])
            if ref != user_id:
                referral_id = ref
        except:
            pass

    existing = await db.get_user(user_id)
    if not existing:
        await db.create_user(user_id, username, referral_id)
        if referral_id:
            ref_user = await db.get_user(referral_id)
            if ref_user:
                try:
                    await bot.send_message(
                        referral_id,
                        f"🎉 New referral joined!\n👤 @{username} used your link!",
                    )
                except:
                    pass
    else:
        await db.update_username(user_id, username)

    user = await db.get_user(user_id)
    await message.answer(
        main_menu_text(username, user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )


# ─── /balance ─────────────────────────────────────────────────────────────────

@dp.message(Command("balance"))
@registered_only
async def cmd_balance(message: Message):
    user = await db.get_user(message.from_user.id)
    await message.answer(
        wallet_text(user),
        parse_mode="Markdown",
        reply_markup=wallet_menu_kb()
    )


# ─── GAME COMMANDS ────────────────────────────────────────────────────────────

async def _game_handler(message: Message, game_fn, game_name: str):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await message.answer("❌ Please /start first.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            f"Usage: `/{game_name} <amount>`\nExample: `/{game_name} 100`",
            parse_mode="Markdown"
        )
        return

    amount, err = validate_amount(parts[1])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return

    if user["balance"] < amount:
        await message.answer(
            error_text(f"Insufficient balance!\nYour balance: {format_balance(user['balance'])}"),
            parse_mode="Markdown",
            reply_markup=back_kb("wallet_deposit")
        )
        return

    if await db.is_balance_locked(user_id):
        await message.answer(error_text("⏳ Game already in progress! Wait for it to finish."), parse_mode="Markdown")
        return

    await game_fn(message, bot, amount)


@dp.message(Command("dice"))
@cooldown(3)
@registered_only
async def cmd_dice(message: Message):
    await _game_handler(message, play_dice, "dice")


@dp.message(Command("bask"))
@cooldown(3)
@registered_only
async def cmd_bask(message: Message):
    await _game_handler(message, play_basketball, "bask")


@dp.message(Command("ball"))
@cooldown(3)
@registered_only
async def cmd_ball(message: Message):
    await _game_handler(message, play_soccer, "ball")


@dp.message(Command("bowl"))
@cooldown(3)
@registered_only
async def cmd_bowl(message: Message):
    await _game_handler(message, play_bowling, "bowl")


@dp.message(Command("darts"))
@cooldown(3)
@registered_only
async def cmd_darts(message: Message):
    await _game_handler(message, play_darts, "darts")


@dp.message(Command("limbo"))
@cooldown(3)
@registered_only
async def cmd_limbo(message: Message):
    await _game_handler(message, play_limbo, "limbo")


@dp.message(Command("coinflip"))
@cooldown(3)
@registered_only
async def cmd_coinflip(message: Message):
    user_id = message.from_user.id
    user = await db.get_user(user_id)

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: `/coinflip <amount>`\nExample: `/coinflip 100`", parse_mode="Markdown")
        return

    amount, err = validate_amount(parts[1])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return

    if user["balance"] < amount:
        await message.answer(
            error_text(f"Insufficient balance!\nYour balance: {format_balance(user['balance'])}"),
            parse_mode="Markdown"
        )
        return

    if await db.is_balance_locked(user_id):
        await message.answer(error_text("⏳ Game in progress!"), parse_mode="Markdown")
        return

    await prompt_coinflip(message, amount)


# ─── WITHDRAW COMMAND ─────────────────────────────────────────────────────────

@dp.message(Command("withdraw"))
@registered_only
async def cmd_withdraw(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) >= 3:
        amount, err = validate_amount(parts[1])
        if err:
            await message.answer(error_text(err), parse_mode="Markdown")
            return
        upi_id = parts[2]
        await process_withdrawal(message, bot, amount, upi_id)
        return

    await message.answer(
        f"💸 *WITHDRAW*\n{SEP}\n"
        f"Format: `/withdraw <amount> <upi_id>`\n"
        f"Example: `/withdraw 500 yourname@upi`",
        parse_mode="Markdown",
        reply_markup=back_kb("menu_wallet")
    )


# ─── DEPOSIT COMMAND ──────────────────────────────────────────────────────────

@dp.message(Command("deposit"))
@registered_only
async def cmd_deposit(message: Message):
    await message.answer(
        f"💳 *DEPOSIT*\n{SEP}\nChoose method:",
        parse_mode="Markdown",
        reply_markup=deposit_menu_kb()
    )


# ─── ADMIN COMMANDS ───────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("🚫 Admin only.")
        return
    await show_admin_panel(message)


@dp.message(Command("setminwithdraw"))
async def cmd_setminwithdraw(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_set_min_withdraw(message)


@dp.message(Command("withdrawtoggle"))
async def cmd_wdtoggle(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_withdraw_toggle(message)


@dp.message(Command("addbalance"))
async def cmd_addbal(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_add_balance(message, bot)


@dp.message(Command("removebalance"))
async def cmd_removebal(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_remove_balance(message, bot)


@dp.message(Command("setbalance"))
async def cmd_setbal(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_set_balance(message, bot)


@dp.message(Command("setbonus"))
async def cmd_setbonus(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_set_bonus(message)


@dp.message(Command("broadcast"))
async def cmd_bcast(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_broadcast(message, bot)


@dp.message(Command("seteligible"))
async def cmd_eligible(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await cmd_set_bonus_eligible(message)


# ─── SUPPORT COMMAND ──────────────────────────────────────────────────────────

@dp.message(Command("support"))
@registered_only
async def cmd_support(message: Message, state: FSMContext):
    await message.answer(
        f"🆘 *SUPPORT*\n{SEP}\n"
        f"Please type your message and we'll forward it to the admin.\n\n"
        f"Send your message now:",
        parse_mode="Markdown",
        reply_markup=back_kb()
    )
    await state.set_state(SupportState.waiting_message)


@dp.message(SupportState.waiting_message)
async def support_message_received(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    uname = user.get("username", str(user_id)) if user else str(user_id)

    await state.clear()
    await message.answer(
        success_text("Your message has been sent to support. We'll reply soon!"),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆘 *SUPPORT MESSAGE*\n{SEP}\n"
                f"👤 From: @{uname} (`{user_id}`)\n\n"
                f"📝 Message:\n{message.text or '[Non-text message]'}\n\n"
                f"Reply with: `/reply {user_id} your message`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Support notify failed: {e}")


@dp.message(Command("reply"))
async def cmd_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.answer("Usage: `/reply user_id your message`", parse_mode="Markdown")
        return
    try:
        target_id = int(parts[1])
        reply_text = parts[2]
        await bot.send_message(
            target_id,
            f"💬 *ADMIN REPLY*\n{SEP}\n{reply_text}",
            parse_mode="Markdown"
        )
        await message.answer(success_text(f"Reply sent to user `{target_id}`"), parse_mode="Markdown")
    except Exception as e:
        await message.answer(error_text(f"Failed: {e}"), parse_mode="Markdown")


# ─── DEPOSIT FLOW (FSM via state tracking) ────────────────────────────────────

class DepositFlow(StatesGroup):
    stars_amount = State()
    upi_info = State()


@dp.message(DepositFlow.stars_amount)
async def deposit_stars_amount(message: Message, state: FSMContext):
    amount, err = validate_amount(message.text)
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await process_stars_deposit(message, bot, amount)


@dp.message(DepositFlow.upi_info)
async def deposit_upi_info(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            error_text("Please send: `amount txn_id`\nExample: `500 TXN123456`"),
            parse_mode="Markdown"
        )
        return
    amount, err = validate_amount(parts[0])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    txn_id = parts[1]
    await state.clear()
    await process_upi_deposit(message, bot, amount, txn_id)


# ─── WITHDRAW FLOW ────────────────────────────────────────────────────────────

class WithdrawFlow(StatesGroup):
    combined = State()


@dp.message(WithdrawFlow.combined)
async def withdraw_combined(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(
            error_text("Please send: `amount upi_id`\nExample: `500 yourname@upi`"),
            parse_mode="Markdown"
        )
        return
    amount, err = validate_amount(parts[0])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    upi_id = parts[1]
    await state.clear()
    await process_withdrawal(message, bot, amount, upi_id)


# ─── CALLBACK HANDLERS ────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_main")
async def cb_menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    uname = callback.from_user.username or callback.from_user.first_name or str(callback.from_user.id)
    balance = user["balance"] if user else 0.0
    await callback.message.edit_text(
        main_menu_text(uname, balance),
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_games")
async def cb_menu_games(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        f"🎮 *GAMES*\n{SEP}\n"
        f"Choose a game and use the command:\n\n"
        f"🎲 `/dice <amount>`\n"
        f"🏀 `/bask <amount>`\n"
        f"⚽ `/ball <amount>`\n"
        f"🎳 `/bowl <amount>`\n"
        f"🎯 `/darts <amount>`\n"
        f"🚀 `/limbo <amount>`\n"
        f"🪙 `/coinflip <amount>`\n\n"
        f"Or tap a game button below:",
        parse_mode="Markdown",
        reply_markup=games_menu_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_wallet")
async def cb_menu_wallet(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        wallet_text(user),
        parse_mode="Markdown",
        reply_markup=wallet_menu_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_referral")
async def cb_menu_referral(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    bot_info = await bot.get_me()
    ref_count = await db.get_referral_count(callback.from_user.id)
    await callback.message.edit_text(
        referral_text(user, ref_count, bot_info.username),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_bonus")
async def cb_menu_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    weekly = await db.get_setting("weekly_bonus")
    monthly = await db.get_setting("monthly_bonus")
    await callback.message.edit_text(
        bonus_text(user, weekly, monthly),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_support")
async def cb_menu_support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"🆘 *SUPPORT*\n{SEP}\n"
        f"Type your message below and we'll forward it to admin.\n"
        f"Or use `/support` command.",
        parse_mode="Markdown",
        reply_markup=back_kb()
    )
    await state.set_state(SupportState.waiting_message)
    await callback.answer()


@dp.callback_query(F.data == "menu_history")
async def cb_menu_history(callback: CallbackQuery):
    txns = await db.get_transactions(callback.from_user.id, limit=10)
    await callback.message.edit_text(
        history_text(txns),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )
    await callback.answer()


# Game shortcuts from menu
@dp.callback_query(F.data.startswith("game_"))
async def cb_game_shortcut(callback: CallbackQuery):
    game = callback.data[5:]
    game_map = {
        "dice": "dice", "bask": "bask", "ball": "ball",
        "bowl": "bowl", "darts": "darts", "limbo": "limbo", "coinflip": "coinflip"
    }
    cmd = game_map.get(game, game)
    await callback.message.edit_text(
        f"🎮 Use command:\n`/{cmd} <amount>`\nExample: `/{cmd} 100`",
        parse_mode="Markdown",
        reply_markup=back_kb("menu_games")
    )
    await callback.answer()


# Wallet
@dp.callback_query(F.data == "wallet_deposit")
async def cb_wallet_deposit(callback: CallbackQuery):
    await callback.message.edit_text(
        f"💳 *DEPOSIT*\n{SEP}\nChoose method:",
        parse_mode="Markdown",
        reply_markup=deposit_menu_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "wallet_withdraw")
async def cb_wallet_withdraw(callback: CallbackQuery, state: FSMContext):
    min_wd = await db.get_setting("min_withdrawal")
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"💸 *WITHDRAW*\n{SEP}\n"
        f"💰 Your Balance: *{format_balance(user['balance'])}*\n"
        f"📉 Min Withdrawal: *₹{min_wd}*\n\n"
        f"Send: `amount upi_id`\nExample: `500 yourname@upi`",
        parse_mode="Markdown",
        reply_markup=back_kb("menu_wallet")
    )
    await state.set_state(WithdrawFlow.combined)
    await callback.answer()


# Deposit flows
@dp.callback_query(F.data == "deposit_stars")
async def cb_deposit_stars(callback: CallbackQuery, state: FSMContext):
    await show_deposit_stars(callback)
    await state.set_state(DepositFlow.stars_amount)


@dp.callback_query(F.data == "deposit_upi")
async def cb_deposit_upi(callback: CallbackQuery, state: FSMContext):
    await show_deposit_upi(callback)
    await state.set_state(DepositFlow.upi_info)


@dp.callback_query(F.data.startswith("deposit_confirm_"))
async def cb_deposit_confirm(callback: CallbackQuery):
    did = int(callback.data.split("_")[-1])
    deposit = await db.get_deposit(did)
    if not deposit or deposit["status"] != "pending":
        await callback.answer("This request is no longer valid.", show_alert=True)
        return
    await callback.answer("✅ Notified admin! Awaiting approval.", show_alert=True)


# Admin deposit approve/reject
@dp.callback_query(F.data.startswith("dep_approve_"))
async def cb_dep_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    did = int(callback.data.split("_")[-1])
    await approve_deposit(callback, bot, did)


@dp.callback_query(F.data.startswith("dep_reject_"))
async def cb_dep_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    did = int(callback.data.split("_")[-1])
    await reject_deposit(callback, bot, did)


# Admin withdrawal approve/reject
@dp.callback_query(F.data.startswith("wd_approve_"))
async def cb_wd_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    wid = int(callback.data.split("_")[-1])
    await approve_withdrawal(callback, bot, wid)


@dp.callback_query(F.data.startswith("wd_reject_"))
async def cb_wd_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    wid = int(callback.data.split("_")[-1])
    await reject_withdrawal(callback, bot, wid)


# Admin panel callbacks
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    total_users = len(await db.get_all_users())
    await callback.message.edit_text(
        f"🔐 *ADMIN PANEL*\n{SEP}\n👥 Total Users: *{total_users}*\n{SEP}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )
    await callback.answer()


@dp.callback_query(F.data == "admin_deposits")
async def cb_admin_deposits(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    await show_pending_deposits(callback)


@dp.callback_query(F.data == "admin_withdrawals")
async def cb_admin_withdrawals(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    await show_pending_withdrawals(callback)


@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    await show_admin_stats(callback)


@dp.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    await show_admin_settings(callback)


@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True)
        return
    await callback.message.edit_text(
        f"📢 *BROADCAST*\n{SEP}\nUse command:\n`/broadcast your message here`",
        parse_mode="Markdown",
        reply_markup=back_kb("admin_panel")
    )
    await callback.answer()


# Coin flip callback
@dp.callback_query(F.data.startswith("cf_"))
async def cb_coinflip(callback: CallbackQuery):
    parts = callback.data.split("_")
    choice = parts[1]
    amount = float(parts[2])
    await play_coinflip(callback, bot, amount, choice)
    await callback.answer()


# ─── STARTUP ──────────────────────────────────────────────────────────────────

async def main():
    await db.init()
    logger.info("🎰 Casino Bot starting...")

    # Clean up any stale balance locks from previous session
    async with __import__('aiosqlite').connect(__import__('config').DB_PATH) as _db:
        await _db.execute("DELETE FROM balance_locks")
        await _db.commit()
    logger.info("Cleared stale balance locks.")

    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
