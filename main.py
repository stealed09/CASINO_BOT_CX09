import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_IDS
from database import db
from utils.logger import logger
from utils.decorators import cooldown, registered_only
from utils.helpers import validate_amount, format_balance
from ui.keyboards import (
    main_menu_kb, games_menu_kb, wallet_menu_kb, deposit_menu_kb,
    back_to_main_kb, back_kb, coinflip_choice_kb,
    admin_panel_kb, admin_settings_kb,
    approve_reject_deposit_kb, approve_reject_withdraw_kb,
    bonus_claim_kb
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
    send_stars_invoice, process_upi_deposit,
    approve_deposit, reject_deposit,
    process_stars_payment, handle_successful_payment
)
from payments.withdraw import process_withdrawal, approve_withdrawal, reject_withdrawal
from admin.panel import (
    show_admin_panel, show_pending_deposits, show_pending_withdrawals,
    show_admin_stats, show_admin_settings,
    cmd_add_balance, cmd_remove_balance, cmd_set_balance, cmd_broadcast
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

REFERRAL_PERCENT = 0.01  # 1% of bet


# ─── FSM ──────────────────────────────────────────────────────────────────────

class DepositFSM(StatesGroup):
    stars_amount = State()
    upi_info = State()

class WithdrawFSM(StatesGroup):
    combined = State()

class SupportState(StatesGroup):
    waiting_message = State()

class AdminFSM(StatesGroup):
    waiting_value = State()


# ─── BONUS / USERNAME CHECK ───────────────────────────────────────────────────

async def check_username_tag(user_id: int, first_name: str, last_name: str, username: str, bio: str = "") -> bool:
    """Check if user has bot tag in their name or bio."""
    tag = await db.get_setting("bot_username_tag") or ""
    if not tag:
        return True  # No tag configured, skip check
    tag_lower = tag.lower().strip("@")
    full_name = f"{first_name} {last_name or ''}".lower()
    bio_lower = bio.lower()
    username_lower = (username or "").lower()
    return (
        tag_lower in full_name or
        f"@{tag_lower}" in bio_lower or
        tag_lower in bio_lower or
        tag_lower in username_lower
    )


async def check_and_process_bonus_eligibility(user_id: int, first_name: str, last_name: str, username: str):
    """On every user action: verify tag, warn if missing, reset if 1hr passed."""
    user = await db.get_user(user_id)
    if not user:
        return

    tag = await db.get_setting("bot_username_tag") or ""
    if not tag:
        return  # Admin hasn't set a tag yet

    has_tag = await check_username_tag(user_id, first_name, last_name or "", username or "")

    if has_tag:
        # Tag present
        if not user.get("bonus_eligible"):
            # Newly eligible
            await db.set_bonus_eligible(user_id, 1)
            await db.set_warn(user_id, 0, None)
            try:
                await bot.send_message(
                    user_id,
                    f"✅ *BONUS ELIGIBLE!*\n{SEP}\n"
                    f"Great! We found our tag in your profile.\n"
                    f"You are now eligible for weekly & monthly bonuses!\n\n"
                    f"⚠️ Don't remove it — removal will reset your progress!",
                    parse_mode="Markdown"
                )
            except:
                pass
        elif user.get("bonus_warned"):
            # Was warned but now restored — clear warning
            await db.set_warn(user_id, 0, None)
            try:
                await bot.send_message(
                    user_id,
                    f"✅ Tag restored! Your bonus progress is safe. Keep it there!",
                    parse_mode="Markdown"
                )
            except:
                pass
    else:
        # Tag missing
        if user.get("bonus_eligible"):
            if not user.get("bonus_warned"):
                # First offence — warn with 1hr deadline
                warn_time = (datetime.now() + timedelta(hours=1)).isoformat()
                await db.set_warn(user_id, 1, warn_time)
                tag_display = tag if tag.startswith("@") else f"@{tag}"
                try:
                    await bot.send_message(
                        user_id,
                        f"⚠️ *WARNING — Tag Removed!*\n{SEP}\n"
                        f"We noticed you removed our tag from your profile!\n\n"
                        f"Please add *{tag_display}* to your:\n"
                        f"• First name or Last name\n"
                        f"• Bio\n\n"
                        f"⏰ You have *1 hour* to restore it.\n"
                        f"After that, your bonus progress resets to Day 1!",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            else:
                # Already warned — check if 1hr has passed
                warn_time_str = user.get("warn_time")
                if warn_time_str:
                    warn_dt = datetime.fromisoformat(warn_time_str)
                    if datetime.now() > warn_dt:
                        await db.reset_bonus_progress(user_id)
                        try:
                            await bot.send_message(
                                user_id,
                                f"❌ *BONUS RESET*\n{SEP}\n"
                                f"You didn't restore the tag in time.\n"
                                f"Your bonus progress has been reset to Day 1.\n\n"
                                f"Add the tag back to start again!",
                                parse_mode="Markdown"
                            )
                        except:
                            pass


async def can_claim_bonus(user: dict, bonus_type: str) -> bool:
    if not user.get("bonus_eligible"):
        return False
    try:
        join_date = datetime.fromisoformat(user["join_date"])
        if (datetime.now() - join_date).days < 7:
            return False
    except:
        return False

    now = datetime.now()
    if bonus_type == "weekly":
        last = user.get("last_weekly")
        if last and (now - datetime.fromisoformat(last)).days < 7:
            return False
    else:
        last = user.get("last_monthly")
        if last and (now - datetime.fromisoformat(last)).days < 30:
            return False
    return True


async def calculate_bonus_amount(user: dict, bonus_type: str) -> float:
    mode = await db.get_setting("bonus_mode") or "fixed"
    if mode == "wagered":
        return round(user["total_wagered"] * 0.01, 2)
    key = "weekly_bonus" if bonus_type == "weekly" else "monthly_bonus"
    return float(await db.get_setting(key) or "0")


# ─── /start ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name or str(user_id)
    last_name = message.from_user.last_name or ""
    is_admin = user_id in ADMIN_IDS

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
                await bot.send_message(referral_id, f"🎉 New referral joined!\n👤 {first_name} used your link!")
            except:
                pass
    else:
        await db.update_username(user_id, username)

    await check_and_process_bonus_eligibility(user_id, first_name, last_name, username)

    user = await db.get_user(user_id)
    display_name = f"@{username}" if username else first_name
    await message.answer(
        main_menu_text(display_name, user["balance"]),
        parse_mode="Markdown",
        reply_markup=main_menu_kb(is_admin=is_admin)
    )


# ─── REFERRAL BONUS HELPER ────────────────────────────────────────────────────

async def pay_referral_bonus(user_id: int, bet_amount: float):
    """Pay 1% of bet_amount to the referrer."""
    user = await db.get_user(user_id)
    if not user or not user.get("referral_id"):
        return
    referrer_id = user["referral_id"]
    bonus = round(bet_amount * REFERRAL_PERCENT, 4)
    if bonus <= 0:
        return
    await db.update_referral_earnings(referrer_id, bonus)
    await db.add_transaction(referrer_id, "referral", bonus)
    logger.info(f"Referral bonus ₹{bonus} -> user {referrer_id} from {user_id} bet ₹{bet_amount}")
    try:
        await bot.send_message(
            referrer_id,
            f"🤝 *REFERRAL BONUS!*\n{SEP}\n"
            f"Your referral placed a bet of ₹{bet_amount:,.2f}\n"
            f"💰 You earned: *+₹{bonus:.4f}*",
            parse_mode="Markdown"
        )
    except:
        pass


# ─── GAME HANDLER ─────────────────────────────────────────────────────────────

async def _game_handler(message: Message, game_fn, game_name: str):
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await message.answer("❌ Please /start first.")
        return

    # Check bonus eligibility on every action
    await check_and_process_bonus_eligibility(
        user_id,
        message.from_user.first_name or "",
        message.from_user.last_name or "",
        message.from_user.username or ""
    )

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(f"Usage: `/{game_name} <amount>`\nExample: `/{game_name} 100`", parse_mode="Markdown")
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
        await message.answer(error_text("⏳ Game already in progress!"), parse_mode="Markdown")
        return

    await game_fn(message, bot, amount)
    # Pay referral bonus after every bet
    await pay_referral_bonus(user_id, amount)


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
        await message.answer(error_text("Insufficient balance!"), parse_mode="Markdown")
        return
    if await db.is_balance_locked(user_id):
        await message.answer(error_text("⏳ Game in progress!"), parse_mode="Markdown")
        return
    await prompt_coinflip(message, amount)


# ─── WALLET COMMANDS ──────────────────────────────────────────────────────────

@dp.message(Command("balance"))
@registered_only
async def cmd_balance(message: Message):
    user = await db.get_user(message.from_user.id)
    await message.answer(wallet_text(user), parse_mode="Markdown", reply_markup=wallet_menu_kb())

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
    await message.answer(f"💸 Format: `/withdraw <amount> <upi_id>`", parse_mode="Markdown")

@dp.message(Command("deposit"))
@registered_only
async def cmd_deposit(message: Message):
    await message.answer(f"💳 *DEPOSIT*\n{SEP}\nChoose method:", parse_mode="Markdown", reply_markup=deposit_menu_kb())


# ─── ADMIN COMMANDS ───────────────────────────────────────────────────────────

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
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


# ─── STARS PAYMENT HANDLERS ───────────────────────────────────────────────────

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await process_stars_payment(query, bot)

@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    await handle_successful_payment(message, bot)


# ─── DEPOSIT FSM ──────────────────────────────────────────────────────────────

class DepositFSM2(StatesGroup):
    stars_amount = State()
    upi_info = State()

class WithdrawFSM2(StatesGroup):
    combined = State()

@dp.message(DepositFSM2.stars_amount)
async def deposit_stars_amount(message: Message, state: FSMContext):
    amount, err = validate_amount(message.text)
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await send_stars_invoice(message, bot, amount)

@dp.message(DepositFSM2.upi_info)
async def deposit_upi_info(message: Message, state: FSMContext):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer(error_text("Send: `amount txn_id`\nExample: `500 TXN123`"), parse_mode="Markdown")
        return
    amount, err = validate_amount(parts[0])
    if err:
        await message.answer(error_text(err), parse_mode="Markdown")
        return
    await state.clear()
    await process_upi_deposit(message, bot, amount, parts[1])

@dp.message(WithdrawFSM2.combined)
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

class AdminFSM2(StatesGroup):
    waiting_value = State()

SETTING_PROMPTS = {
    "aset_minwd":     ("min_withdrawal",   "Send new minimum withdrawal amount (number):"),
    "aset_weekly":    ("weekly_bonus",     "Send new weekly bonus amount (number):"),
    "aset_monthly":   ("monthly_bonus",    "Send new monthly bonus amount (number):"),
    "aset_bonusmode": ("bonus_mode",       "Send bonus mode: `wagered` or `fixed`"),
    "aset_upi":       ("upi_id",           "Send new UPI ID (e.g. name@upi):"),
    "aset_qr":        ("upi_qr",           "Send UPI QR code as a PHOTO:"),
    "aset_star":      ("star_payment_id",  "Send Telegram Star Payment provider token:"),
    "aset_wdtoggle":  ("withdraw_enabled", "Send `on` or `off`:"),
    "aset_bottag":    ("bot_username_tag", "Send bot username tag users must add (e.g. @YourBotName):"),
}

@dp.message(AdminFSM2.waiting_value)
async def admin_setting_value(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()

    if key == "upi_qr":
        if not message.photo:
            await message.answer(error_text("Please send a PHOTO for QR code."), parse_mode="Markdown")
            return
        file_id = message.photo[-1].file_id
        await db.set_setting("upi_qr", file_id)
        await message.answer(success_text("UPI QR image saved!"), parse_mode="Markdown", reply_markup=back_kb("admin_settings"))
        return

    value = message.text.strip() if message.text else ""
    if not value:
        await message.answer(error_text("No text received."), parse_mode="Markdown")
        return

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
    elif key == "bot_username_tag":
        value = value.strip("@").lower()

    await db.set_setting(key, value)
    await message.answer(success_text(f"Updated: `{key}` = `{value}`"), parse_mode="Markdown", reply_markup=back_kb("admin_settings"))


# ─── CALLBACKS ────────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "menu_main")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await db.get_user(callback.from_user.id)
    uname = callback.from_user.username or callback.from_user.first_name or str(callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS
    try:
        await callback.message.edit_text(
            main_menu_text(f"@{uname}" if callback.from_user.username else uname, user["balance"] if user else 0),
            parse_mode="Markdown",
            reply_markup=main_menu_kb(is_admin=is_admin)
        )
    except:
        await callback.message.answer(
            main_menu_text(uname, user["balance"] if user else 0),
            parse_mode="Markdown",
            reply_markup=main_menu_kb(is_admin=is_admin)
        )
    await callback.answer()

@dp.callback_query(F.data == "menu_games")
async def cb_games(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text(
            f"🎮 *GAMES*\n{SEP}\n"
            f"🎲 `/dice <amt>` | 🏀 `/bask <amt>`\n"
            f"⚽ `/ball <amt>` | 🎳 `/bowl <amt>`\n"
            f"🎯 `/darts <amt>` | 🚀 `/limbo <amt>`\n"
            f"🪙 `/coinflip <amt>`",
            parse_mode="Markdown", reply_markup=games_menu_kb()
        )
    except:
        pass
    await callback.answer()

@dp.callback_query(F.data == "menu_wallet")
async def cb_wallet(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    try:
        await callback.message.edit_text(wallet_text(user), parse_mode="Markdown", reply_markup=wallet_menu_kb())
    except:
        await callback.message.answer(wallet_text(user), parse_mode="Markdown", reply_markup=wallet_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "menu_referral")
async def cb_referral(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    bot_info = await bot.get_me()
    ref_count = await db.get_referral_count(callback.from_user.id)
    try:
        await callback.message.edit_text(
            referral_text(user, ref_count, bot_info.username),
            parse_mode="Markdown", reply_markup=back_kb()
        )
    except:
        await callback.message.answer(referral_text(user, ref_count, bot_info.username), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data == "menu_bonus")
async def cb_bonus(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    mode = await db.get_setting("bonus_mode") or "fixed"

    can_weekly = await can_claim_bonus(user, "weekly")
    can_monthly = await can_claim_bonus(user, "monthly")

    if mode == "wagered":
        w_amt = round(user["total_wagered"] * 0.01, 2)
        m_amt = w_amt
    else:
        w_amt = float(await db.get_setting("weekly_bonus") or "0")
        m_amt = float(await db.get_setting("monthly_bonus") or "0")

    try:
        join_date = datetime.fromisoformat(user["join_date"])
        days_old = (datetime.now() - join_date).days
    except:
        days_old = 0

    tag = await db.get_setting("bot_username_tag") or "not set"
    tag_display = f"@{tag}" if tag and not tag.startswith("@") else tag

    last_w = user.get("last_weekly")
    last_m = user.get("last_monthly")

    def next_str(last, period):
        if not last:
            return f"After {period}d (day {days_old}/{period})" if days_old < period else "Available now!"
        diff = (datetime.now() - datetime.fromisoformat(last)).days
        rem = period - diff
        return "Available now!" if rem <= 0 else f"In {rem} day(s)"

    text = (
        f"🎁 *BONUS CENTER*\n{SEP}\n"
        f"📊 Status: {'✅ Eligible' if user['bonus_eligible'] else '❌ Not Eligible'}\n"
        f"🏷️ Required Tag: *{tag_display}*\n"
        f"🎰 Mode: *{mode}*\n\n"
        f"🗓️ Weekly: *₹{w_amt:,.2f}* — {next_str(last_w, 7)}\n"
        f"📅 Monthly: *₹{m_amt:,.2f}* — {next_str(last_m, 30)}\n"
        f"{SEP}\n"
        f"📋 Add *{tag_display}* to your name/bio to be eligible!"
    )

    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=bonus_claim_kb(can_weekly, can_monthly))
    except:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=bonus_claim_kb(can_weekly, can_monthly))
    await callback.answer()

@dp.callback_query(F.data == "bonus_claim_weekly")
async def cb_claim_weekly(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not await can_claim_bonus(user, "weekly"):
        await callback.answer("Not eligible yet!", show_alert=True); return
    amount = await calculate_bonus_amount(user, "weekly")
    if amount <= 0:
        await callback.answer("Bonus amount is 0. Contact admin.", show_alert=True); return
    await db.update_balance(callback.from_user.id, amount)
    await db.add_transaction(callback.from_user.id, "deposit", amount, "weekly_bonus")
    await db.update_last_bonus(callback.from_user.id, "weekly")
    await callback.answer(f"✅ ₹{amount:,.2f} weekly bonus credited!", show_alert=True)

@dp.callback_query(F.data == "bonus_claim_monthly")
async def cb_claim_monthly(callback: CallbackQuery):
    user = await db.get_user(callback.from_user.id)
    if not await can_claim_bonus(user, "monthly"):
        await callback.answer("Not eligible yet!", show_alert=True); return
    amount = await calculate_bonus_amount(user, "monthly")
    if amount <= 0:
        await callback.answer("Bonus amount is 0. Contact admin.", show_alert=True); return
    await db.update_balance(callback.from_user.id, amount)
    await db.add_transaction(callback.from_user.id, "deposit", amount, "monthly_bonus")
    await db.update_last_bonus(callback.from_user.id, "monthly")
    await callback.answer(f"✅ ₹{amount:,.2f} monthly bonus credited!", show_alert=True)

@dp.callback_query(F.data == "menu_support")
async def cb_support(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(f"🆘 *SUPPORT*\n{SEP}\nType your message:", parse_mode="Markdown", reply_markup=back_kb())
    except:
        await callback.message.answer(f"🆘 Type your message:", reply_markup=back_kb())
    await state.set_state(SupportState.waiting_message)
    await callback.answer()

@dp.callback_query(F.data == "menu_history")
async def cb_history(callback: CallbackQuery):
    txns = await db.get_transactions(callback.from_user.id)
    try:
        await callback.message.edit_text(history_text(txns), parse_mode="Markdown", reply_markup=back_kb())
    except:
        await callback.message.answer(history_text(txns), parse_mode="Markdown", reply_markup=back_kb())
    await callback.answer()

@dp.callback_query(F.data.startswith("game_"))
async def cb_game(callback: CallbackQuery):
    cmd = callback.data[5:]
    try:
        await callback.message.edit_text(
            f"Use: `/{cmd} <amount>`\nExample: `/{cmd} 100`",
            parse_mode="Markdown", reply_markup=back_kb("menu_games")
        )
    except:
        pass
    await callback.answer()

@dp.callback_query(F.data == "wallet_deposit")
async def cb_deposit_menu(callback: CallbackQuery):
    try:
        await callback.message.edit_text(f"💳 *DEPOSIT*\n{SEP}\nChoose method:", parse_mode="Markdown", reply_markup=deposit_menu_kb())
    except:
        await callback.message.answer(f"💳 Choose deposit method:", reply_markup=deposit_menu_kb())
    await callback.answer()

@dp.callback_query(F.data == "wallet_withdraw")
async def cb_withdraw(callback: CallbackQuery, state: FSMContext):
    min_wd = await db.get_setting("min_withdrawal")
    user = await db.get_user(callback.from_user.id)
    try:
        await callback.message.edit_text(
            f"💸 *WITHDRAW*\n{SEP}\n"
            f"💰 Balance: *{format_balance(user['balance'])}*\n"
            f"📉 Min: *₹{min_wd}*\n\n"
            f"Send: `amount upi_id`\nExample: `500 name@upi`",
            parse_mode="Markdown", reply_markup=back_kb("menu_wallet")
        )
    except:
        await callback.message.answer(f"Send: `amount upi_id`", parse_mode="Markdown")
    await state.set_state(WithdrawFSM2.combined)
    await callback.answer()

@dp.callback_query(F.data == "deposit_stars")
async def cb_dep_stars(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            f"⭐ *STARS DEPOSIT*\n{SEP}\nSend amount in ₹ you want to add:\nExample: `100`",
            parse_mode="Markdown", reply_markup=back_kb("wallet_deposit")
        )
    except:
        await callback.message.answer("Send amount in ₹:", reply_markup=back_kb("wallet_deposit"))
    await state.set_state(DepositFSM2.stars_amount)
    await callback.answer()

@dp.callback_query(F.data == "deposit_upi")
async def cb_dep_upi(callback: CallbackQuery, state: FSMContext):
    await show_deposit_upi(callback, bot)
    await state.set_state(DepositFSM2.upi_info)

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
    try:
        await callback.message.edit_text(
            f"🔐 *ADMIN PANEL*\n{SEP}\n👥 Users: *{len(users)}*",
            parse_mode="Markdown", reply_markup=admin_panel_kb()
        )
    except:
        await callback.message.answer(f"🔐 *ADMIN PANEL*\n👥 Users: *{len(users)}*", parse_mode="Markdown", reply_markup=admin_panel_kb())
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
    try:
        await callback.message.edit_text(
            f"📢 Use: `/broadcast your message`", parse_mode="Markdown", reply_markup=back_kb("admin_panel")
        )
    except:
        pass
    await callback.answer()

@dp.callback_query(F.data.startswith("aset_"))
async def cb_admin_set(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Admin only!", show_alert=True); return
    key_data = SETTING_PROMPTS.get(callback.data)
    if not key_data:
        await callback.answer(); return
    db_key, prompt = key_data
    await state.set_state(AdminFSM2.waiting_value)
    await state.update_data(setting_key=db_key)
    try:
        await callback.message.edit_text(
            f"⚙️ *{db_key.upper()}*\n{SEP}\n{prompt}",
            parse_mode="Markdown", reply_markup=back_kb("admin_settings")
        )
    except:
        await callback.message.answer(prompt, reply_markup=back_kb("admin_settings"))
    await callback.answer()

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
    await pay_referral_bonus(callback.from_user.id, amount)
    await callback.answer()


# ─── FALLBACK — handle unknown messages gracefully ────────────────────────────

@dp.message()
async def fallback_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    # If in a FSM state, don't interrupt
    if current_state:
        return
    # Ignore dice/media sent randomly
    if not message.text:
        return
    # Ignore if it looks like a command we don't handle
    if message.text.startswith("/"):
        await message.answer(
            f"❓ Unknown command.\nUse /start to open the menu.",
            reply_markup=back_kb()
        )
        return
    # Random text — show menu
    user = await db.get_user(message.from_user.id)
    if user:
        is_admin = message.from_user.id in ADMIN_IDS
        uname = message.from_user.username or message.from_user.first_name or str(message.from_user.id)
        await message.answer(
            main_menu_text(uname, user["balance"]),
            parse_mode="Markdown",
            reply_markup=main_menu_kb(is_admin=is_admin)
        )
    else:
        await message.answer("Please use /start to register.")


# ─── STARTUP ──────────────────────────────────────────────────────────────────

async def main():
    await db.init()
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as _db:
        await _db.execute("DELETE FROM balance_locks")
        await _db.commit()
    logger.info("🎰 Casino Bot started!")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
