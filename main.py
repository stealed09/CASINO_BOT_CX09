import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS, REFERRAL_PERCENT
from database import db
from utils.logger import logger
from utils.decorators import cooldown, registered_only
from utils.helpers import validate_amount, format_balance, calculate_win_reward
from ui.keyboards import (
    main_menu_kb, games_menu_kb, wallet_menu_kb, deposit_menu_kb,
    back_to_main_kb, back_kb, coinflip_choice_kb,
    admin_panel_kb, admin_settings_kb,
    approve_reject_deposit_kb, approve_reject_withdraw_kb,
    paid_confirm_kb, bonus_claim_kb
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
    cmd_add_balance, cmd_remove_balance, cmd_set_balance, cmd_broadcast
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# ─── FSM ──────────────────────────────────────────────────────────────────────

class DepositFlow(StatesGroup):
    stars_amount = State()
    upi_info = State()

class WithdrawFlow(StatesGroup):
    combined = State()

class SupportState(StatesGroup):
    waiting_message = State()

class AdminSetState(StatesGroup):
    waiting_value = State()


# ─── BONUS LOGIC ──────────────────────────────────────────────────────────────

async def check_and_warn_user(user_id: int, username: str, first_name: str):
    """Check if user removed bio markers, warn and potentially reset."""
    user = await db.get_user(user_id)
    if not user or not user.get("bonus_eligible"):
        return

    # Check if username or name contains bot handle (simplified check)
    has_marker = bool(username)  # User has a username set

    if not has_marker:
        if not user.get("bonus_warned"):
            # First offence — warn, set 1hr timer
            warn_time = (datetime.now() + timedelta(hours=1)).isoformat()
            await db.set_warn(user_id, 1, warn_time)
            try:
                await bot.send_message(
                    user_id,
                    f"⚠️ *WARNING*\n{SEP}\n"
                    f"You've removed your username!\n\n"
                    f"To keep your bonus eligibility, please set your Telegram username within *1 hour*.\n\n"
                    f"If not restored, your bonus progress will reset from Day 1! ⏳",
                    parse_mode="Markdown"
                )
            except:
                pass
        else:
            # Already warned — check if 1hr passed
            warn_time_str = user.get("warn_time")
            if warn_time_str:
                warn_time = datetime.fromisoformat(warn_time_str)
                if datetime.now() > warn_time:
                    # Reset bonus progress
                    await db.reset_bonus_progress(user_id)
                    try:
                        await bot.send_message(
                            user_id,
                            f"❌ *BONUS RESET*\n{SEP}\n"
                            f"Your bonus progress has been reset because you didn't restore your username in time.\n"
                            f"Start fresh from Day 1! 📅",
                            parse_mode="Markdown"
                        )
                    except:
                        pass
    else:
        # Username restored — clear warning
        if user.get("bonus_warned"):
            await db.set_warn(user_id, 0, None)


async def calculate_bonus_amount(user: dict, bonus_type: str) -> float:
    mode = await db.get_setting("bonus_mode") or "wagered"
    if mode == "wagered":
        # 1% of total wagered
        return round(user["total_wagered"] * 0.01, 2)
    else:
        # Fixed admin-set amount
        key = "weekly_bonus" if bonus_type == "weekly" else "monthly_bonus"
        val = await db.get_setting(key) or "0"
        return float(val)


async def can_claim_bonus(user: dict, bonus_type: str) -> bool:
    if not user.get("bonus_eligible"):
        return False

    # Must be 7+ days old
    try:
        join_date = datetime.fromisoformat(user["join_date"])
        if (datetime.now() - join_date).days < 7:
            return False
    except:
        return False

    now = datetime.now()
    if bonus_type == "weekly":
        last = user.get("last_weekly")
        if last:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).days < 7:
                return False
    else:
        last = user.get("last_monthly")
        if last:
            last_dt = datetime.fromisoformat(last)
            if (now - last_dt).days < 30:
                return False
    return True


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or str(user_id)

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
            try:
                await bot.send_message(referral_id, f"🎉 New referral joined!\n👤 @{username or first_name} used your link!")
            except:
                pass
    else:
        await db.update_username(user_id, username)

    await check_and_warn_user(user_id, username, first_name)

    user = await db.get_user(user_id)
    await message.answer(
        main_menu_text(username or first_name, user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_kb()
    )


# ─── GAME HANDLER ─────────────────────────────────────────────────────────────

async def _game_handler(message: Message, game_fn, game_name: str):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await message.answer("❌ Please /start first.")
        return

    # Check and warn on every action
    await check_and_warn_user(user_id, message.from_user.username or "", message.from_user.first_name or "")

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(f"Usage: `/{game_name} <amount>`", parse_mode="Markdown")
        return

    amount, err = validate_amount(parts[1])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return

    if user["balance"] < amount:
        await message.answer(
            error_text(f"Insufficient balance!\nYour balance: {format_balance(user['balance'])}"),
            parse_mode="Markdown", reply_markup=back_kb("wallet_deposit")
        )
        return

    if await db.is_balance_locked(user_id):
        await message.answer(error_text("⏳ Game in progress!"), parse_mode="Markdown")
        return

    await game_fn(message, bot, amount)

    # After game — pay referral bonus (fixed: direct call after game)
    updated_user = await db.get_user(user_id)
    if updated_user and updated_user.get("referral_id"):
        bonus = round(amount * REFERRAL_PERCENT, 4)
        if bonus > 0:
            await db.update_referral_earnings(updated_user["referral_id"], bonus)
            await db.add_transaction(updated_user["referral_id"], "referral", bonus)
            logger.info(f"Referral bonus ₹{bonus} sent to {updated_user['referral_id']} from {user_id}'s bet of ₹{amount}")


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
        await message.answer("Usage: `/coinflip <amount>`", parse_mode="Markdown")
        return
    amount, err = validate_amount(parts[1])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    if user["balance"] < amount:
        await message.answer(error_text(f"Insufficient balance!"), parse_mode="Markdown")
        return
    if await db.is_balance_locked(user_id):
        await message.answer(error_text("⏳ Game in progress!"), parse_mode="Markdown")
        return
    await prompt_coinflip(message, amount)


# ─── WITHDRAW ─────────────────────────────────────────────────────────────────

@dp.message(Command("withdraw"))
@registered_only
async def cmd_withdraw(message: Message):
    parts = message.text.split()
    if len(parts) >= 3:
        amount, err = validate_amount(parts[1])
        if err:
            await message.answer(error_text(err), parse_mode="Markdown")
            return
        await process_withdrawal(message, bot, amount, parts[2])
        return
    await message.answer(
        f"💸 Format: `/withdraw <amount> <upi_id>`",
        parse_mode="Markdown", reply_markup=back_kb("menu_wallet")
    )

@dp.message(Command("deposit"))
@registered_only
async def cmd_deposit(message: Message):
    await message.answer(f"💳 *DEPOSIT*\n{SEP}\nChoose method:", parse_mode="Markdown", reply_markup=deposit_menu_kb())

@dp.message(Command("balance"))
@registered_only
async def cmd_balance(message: Message):
    user = await db.get_user(message.from_user.id)
    await message.answer(wallet_text(user), parse_mode="Markdown", reply_markup=wallet_menu_kb())


# ─── ADMIN COMMANDS ───────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await show_admin_panel(message)

@dp.message(Command("addbalance"))
async def cmd_addbal(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await cmd_add_balance(message, bot)

@dp.message(Command("removebalance"))
async def cmd_removebal(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await cmd_remove_balance(message, bot)

@dp.message(Command("setbalance"))
async def cmd_setbal(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await cmd_set_balance(message, bot)

@dp.message(Command("broadcast"))
async def cmd_bcast(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    await cmd_broadcast(message, bot)

@dp.message(Command("reply"))
async def cmd_reply(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split(None, 2)
    if len(parts) < 3:
        await message.answer("Usage: `/reply user_id message`", parse_mode="Markdown")
        return
    try:
        await bot.send_message(int(parts[1]), f"💬 *ADMIN REPLY*\n{SEP}\n{parts[2]}", parse_mode="Markdown")
        await message.answer(success_text(f"Reply sent to `{parts[1]}`"), parse_mode="Markdown")
    except Exception as e:
        await message.answer(error_text(str(e)), parse_mode="Markdown")


# ─── SUPPORT ──────────────────────────────────────────────────────────────────

@dp.message(Command("support"))
@registered_only
async def cmd_support(message: Message, state: FSMContext):
    await message.answer(f"🆘 Send your message:", reply_markup=back_kb())
    await state.set_state(SupportState.waiting_message)

@dp.message(SupportState.waiting_message)
async def support_msg(message: Message, state: FSMContext):
    user_id = message.from_user.id
    uname = message.from_user.username or str(user_id)
    await state.clear()
    await message.answer(success_text("Message sent to support!"), parse_mode="Markdown", reply_markup=back_kb())
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🆘 *SUPPORT*\n{SEP}\n👤 @{uname} (`{user_id}`)\n\n{message.text or '[media]'}\n\nReply: `/reply {user_id} msg`",
                parse_mode="Markdown"
            )
        except:
            pass


# ─── DEPOSIT FSM ──────────────────────────────────────────────────────────────

class DepositFSM(StatesGroup):
    stars_amount = State()
    upi_info = State()

@dp.message(DepositFSM.stars_amount)
async def deposit_stars_amount(message: Message, state: FSMContext):
    amount, err = validate_amount(message.text)
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await process_stars_deposit(message, bot, amount)

@dp.message(DepositFSM.upi_info)
async def deposit_upi_info(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(error_text("Send: `amount txn_id`"), parse_mode="Markdown")
        return
    amount, err = validate_amount(parts[0])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await process_upi_deposit(message, bot, amount, parts[1])

class WithdrawFSM(StatesGroup):
    combined = State()

@dp.message(WithdrawFSM.combined)
async def withdraw_combined(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(error_text("Send: `amount upi_id`"), parse_mode="Markdown")
        return
    amount, err = validate_amount(parts[0])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await process_withdrawal(message, bot, amount, parts[1])


# ─── ADMIN SETTINGS FSM ───────────────────────────────────────────────────────

class AdminFSM(StatesGroup):
    waiting_value = State()

@dp.message(AdminFSM.waiting_value)
async def admin_setting_value(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()

    if key == "upi_qr":
        # Expect photo
        if not message.photo:
            await message.answer(error_text("Please send a photo/image for QR code."), parse_mode="Markdown")
            return
        file_id = message.photo[-1].file_id
        await db.set_setting("upi_qr", file_id)
        await message.answer(success_text("UPI QR image saved!"), parse_mode="Markdown", reply_markup=back_kb("admin_settings"))
        return

    value = message.text.strip()
    if key in ("min_withdrawal", "weekly_bonus", "monthly_bonus"):
        try:
            float(value)
        except:
            await message.answer(error_text("Invalid number."), parse_mode="Markdown")
            return
    elif key == "withdraw_enabled":
        value = "1" if value.lower() in ("on", "1", "yes") else "0"
    elif key == "bonus_mode":
        if value.lower() not in ("wagered", "fixed"):
            await message.answer(error_text("Send 'wagered' or 'fixed'"), parse_mode="Markdown")
            return
        value = value.lower()

    await db.set_setting(key, value)
    await message.answer(success_text(f"Setting updated: `{key}` = `{value}`"), parse_mode="Markdown", reply_markup=back_kb("admin_settings"))


# ─── CALLBACKS ────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    uname = callback.from_user.username or callback.from_user.first_name or str(callback.from_user.id)
    await callback.message.edit_text(
        main_menu_text(uname, user["balance"] if user else 0),
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_games")
async def cb_games(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        f"🎮 *GAMES*\n{SEP}\n"
        f"🎲 `/dice <amt>` | 🏀 `/bask <amt>`\n"
        f"⚽ `/ball <amt>` | 🎳 `/bowl <amt>`\n"
        f"🎯 `/darts <amt>` | 🚀 `/limbo <amt>`\n"
        f"🪙 `/coinflip <amt>`",
        parse_mode="Markdown", reply_markup=games_menu_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_wallet")
async def cb_wallet(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(wallet_text(user), parse_mode="Markdown", reply_markup=wallet_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "menu_referral")
async def cb_referral(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    bot_info = await bot.get_me()
    ref_count = await db.get_referral_count(callback.from_user.id)
    await callback.message.edit_text(
        referral_text(user, ref_count, bot_info.username),
        parse_mode="Markdown", reply_markup=back_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_bonus")
async def cb_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    weekly = await db.get_setting("weekly_bonus")
    monthly = await db.get_setting("monthly_bonus")
    mode = await db.get_setting("bonus_mode") or "fixed"

    can_weekly = await can_claim_bonus(user, "weekly")
    can_monthly = await can_claim_bonus(user, "monthly")

    # Calculate amounts to show
    if mode == "wagered":
        w_amt = round(user["total_wagered"] * 0.01, 2)
        m_amt = round(user["total_wagered"] * 0.01, 2)
    else:
        w_amt = float(weekly)
        m_amt = float(monthly)

    join_date = user.get("join_date", "")
    try:
        days_old = (datetime.now() - datetime.fromisoformat(join_date)).days
    except:
        days_old = 0

    last_w = user.get("last_weekly")
    last_m = user.get("last_monthly")
    next_weekly = "Available now!" if can_weekly else (
        f"In {7 - (datetime.now() - datetime.fromisoformat(last_w)).days}d" if last_w else f"After 7 days (day {days_old}/7)"
    )
    next_monthly = "Available now!" if can_monthly else (
        f"In {30 - (datetime.now() - datetime.fromisoformat(last_m)).days}d" if last_m else f"After 7 days (day {days_old}/7)"
    )

    text = (
        f"🎁 *BONUS CENTER*\n{SEP}\n"
        f"📊 Status: {'✅ Eligible' if user['bonus_eligible'] else '❌ Not Eligible'}\n"
        f"🎰 Mode: *{mode}*\n\n"
        f"🗓️ Weekly Bonus: *₹{w_amt:,.2f}* — {next_weekly}\n"
        f"📅 Monthly Bonus: *₹{m_amt:,.2f}* — {next_monthly}\n"
        f"{SEP}\n"
        f"📋 Eligibility: Set username + 7 days old account"
    )

    kb = bonus_claim_kb(can_weekly, can_monthly)
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "bonus_claim_weekly")
async def cb_claim_weekly(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not await can_claim_bonus(user, "weekly"):
        await callback.answer("Not eligible yet!", show_alert=True)
        return
    amount = await calculate_bonus_amount(user, "weekly")
    await db.update_balance(callback.from_user.id, amount)
    await db.add_transaction(callback.from_user.id, "deposit", amount, "weekly_bonus")
    await db.update_last_bonus(callback.from_user.id, "weekly")
    await callback.answer(f"✅ Weekly bonus ₹{amount:,.2f} credited!", show_alert=True)

@dp.callback_query(F.data == "bonus_claim_monthly")
async def cb_claim_monthly(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not await can_claim_bonus(user, "monthly"):
        await callback.answer("Not eligible yet!", show_alert=True)
        return
    amount = await calculate_bonus_amount(user, "monthly")
    await db.update_balance(callback.from_user.id, amount)
    await db.add_transaction(callback.from_user.id, "deposit", amount, "monthly_bonus")
    await db.update_last_bonus(callback.from_user.id, "monthly")
    await callback.answer(f"✅ Monthly bonus ₹{amount:,.2f} credited!", show_alert=True)

@dp.callback_query(F.data == "menu_support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(f"🆘 *SUPPORT*\n{SEP}\nType your message:", parse_mode="Markdown", reply_markup=back_kb())
    await state.set_state(SupportState.waiting_message)
    await callback.answer()

@dp.callback_query(F.data == "menu_history")
async def cb_history(callback: CallbackQuery):
    txns = await db.get_transactions(callback.from_user.id)
    await callback.message.edit_text(history_text(txns), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("game_"))
async def cb_game(callback: CallbackQuery):
    cmd = callback.data[5:]
    await callback.message.edit_text(
        f"Use: `/{cmd} <amount>`\nExample: `/{cmd} 100`",
        parse_mode="Markdown", reply_markup=back_kb("menu_games")
    )
    await callback.answer()

@dp.callback_query(F.data == "wallet_deposit")
async def cb_deposit(callback: CallbackQuery):
    await callback.message.edit_text(f"💳 *DEPOSIT*\n{SEP}\nChoose method:", parse_mode="Markdown", reply_markup=deposit_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "wallet_withdraw")
async def cb_withdraw(callback: CallbackQuery, state: FSMContext):
    min_wd = await db.get_setting("min_withdrawal")
    user = await db.get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"💸 *WITHDRAW*\n{SEP}\n"
        f"💰 Balance: *{format_balance(user['balance'])}*\n"
        f"📉 Min: *₹{min_wd}*\n\n"
        f"Send: `amount upi_id`",
        parse_mode="Markdown", reply_markup=back_kb("menu_wallet")
    )
    await state.set_state(WithdrawFSM.combined)
    await callback.answer()

@dp.callback_query(F.data == "deposit_stars")
async def cb_dep_stars(callback: CallbackQuery, state: FSMContext):
    await show_deposit_stars(callback)
    await state.set_state(DepositFSM.stars_amount)

@dp.callback_query(F.data == "deposit_upi")
async def cb_dep_upi(callback: CallbackQuery, state: FSMContext):
    await show_deposit_upi(callback, bot)
    await state.set_state(DepositFSM.upi_info)

@dp.callback_query(F.data.startswith("deposit_confirm_"))
async def cb_dep_confirm(callback: CallbackQuery):
    await callback.answer("✅ Admin notified! Awaiting approval.", show_alert=True)

@dp.callback_query(F.data.startswith("dep_approve_"))
async def cb_dep_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await approve_deposit(callback, bot, int(callback.data.split("_")[-1]))

@dp.callback_query(F.data.startswith("dep_reject_"))
async def cb_dep_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await reject_deposit(callback, bot, int(callback.data.split("_")[-1]))

@dp.callback_query(F.data.startswith("wd_approve_"))
async def cb_wd_approve(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await approve_withdrawal(callback, bot, int(callback.data.split("_")[-1]))

@dp.callback_query(F.data.startswith("wd_reject_"))
async def cb_wd_reject(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await reject_withdrawal(callback, bot, int(callback.data.split("_")[-1]))

# ─── ADMIN CALLBACKS ──────────────────────────────────────────────────────────

@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    users = await db.get_all_users()
    await callback.message.edit_text(
        f"🔐 *ADMIN PANEL*\n{SEP}\n👥 Users: *{len(users)}*",
        parse_mode="Markdown", reply_markup=admin_panel_kb()
    )
    await callback.answer()

@dp.callback_query(F.data == "admin_deposits")
async def cb_adm_deposits(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await show_pending_deposits(callback)

@dp.callback_query(F.data == "admin_withdrawals")
async def cb_adm_wds(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await show_pending_withdrawals(callback)

@dp.callback_query(F.data == "admin_stats")
async def cb_adm_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await show_admin_stats(callback)

@dp.callback_query(F.data == "admin_settings")
async def cb_adm_settings(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await show_admin_settings(callback)

@dp.callback_query(F.data == "admin_broadcast")
async def cb_adm_broadcast(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    await callback.message.edit_text(
        f"📢 Use: `/broadcast your message`", parse_mode="Markdown", reply_markup=back_kb("admin_panel")
    )
    await callback.answer()

# Admin settings inline buttons
SETTING_PROMPTS = {
    "aset_minwd": ("min_withdrawal", "Send new minimum withdrawal amount (number):"),
    "aset_weekly": ("weekly_bonus", "Send new weekly bonus amount (number):"),
    "aset_monthly": ("monthly_bonus", "Send new monthly bonus amount (number):"),
    "aset_bonusmode": ("bonus_mode", "Send bonus mode: `wagered` or `fixed`"),
    "aset_upi": ("upi_id", "Send new UPI ID:"),
    "aset_qr": ("upi_qr", "Send UPI QR code image (photo):"),
    "aset_star": ("star_payment_id", "Send new Telegram Star Payment ID:"),
    "aset_wdtoggle": ("withdraw_enabled", "Send `on` or `off`:"),
}

@dp.callback_query(F.data.startswith("aset_"))
async def cb_admin_set(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    key_data = SETTING_PROMPTS.get(callback.data)
    if not key_data:
        await callback.answer(); return
    db_key, prompt = key_data
    await state.set_state(AdminFSM.waiting_value)
    await state.update_data(setting_key=db_key)
    await callback.message.edit_text(
        f"⚙️ *SETTING: {db_key}*\n{SEP}\n{prompt}",
        parse_mode="Markdown", reply_markup=back_kb("admin_settings")
    )
    await callback.answer()

# Coinflip
@dp.callback_query(F.data.startswith("cf_"))
async def cb_cf(callback: CallbackQuery):
    parts = callback.data.split("_")
    choice, amount = parts[1], float(parts[2])

    user = await db.get_user(callback.from_user.id)
    if not user or user["balance"] < amount:
        await callback.answer("❌ Insufficient balance!", show_alert=True); return
    if await db.is_balance_locked(callback.from_user.id):
        await callback.answer("⏳ Game in progress!", show_alert=True); return

    await play_coinflip(callback, bot, amount, choice)

    # Referral bonus for coinflip
    updated = await db.get_user(callback.from_user.id)
    if updated and updated.get("referral_id"):
        bonus = round(amount * REFERRAL_PERCENT, 4)
        if bonus > 0:
            await db.update_referral_earnings(updated["referral_id"], bonus)
            await db.add_transaction(updated["referral_id"], "referral", bonus)

    await callback.answer()


# ─── STARTUP ──────────────────────────────────────────────────────────────────

async def main():
    await db.init()

    # Clear stale locks
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as _db:
        await _db.execute("DELETE FROM balance_locks")
        await _db.commit()

    logger.info("🎰 Casino Bot started!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
