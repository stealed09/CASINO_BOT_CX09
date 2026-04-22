from aiogram.types import Message, CallbackQuery
from aiogram import Bot
from database import db
from config import ADMIN_IDS
from ui.keyboards import admin_panel_kb, approve_reject_deposit_kb, approve_reject_withdraw_kb, withdraw_toggle_kb, back_kb
from ui.messages import SEP, success_text, error_text
from utils.decorators import admin_only
from utils.logger import logger


async def show_admin_panel(message: Message):
    total_users = len(await db.get_all_users())
    await message.answer(
        f"🔐 *ADMIN PANEL*\n{SEP}\n"
        f"👥 Total Users: *{total_users}*\n"
        f"{SEP}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )


async def show_pending_deposits(callback: CallbackQuery):
    deposits = await db.get_pending_deposits()
    if not deposits:
        await callback.message.edit_text(
            f"💳 *PENDING DEPOSITS*\n{SEP}\nNo pending deposits.",
            parse_mode="Markdown",
            reply_markup=back_kb("admin_panel")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💳 *PENDING DEPOSITS* ({len(deposits)})\n{SEP}",
        parse_mode="Markdown",
        reply_markup=back_kb("admin_panel")
    )
    await callback.answer()

    for dep in deposits:
        await callback.message.answer(
            f"🆔 #{dep['id']} | 👤 `{dep['user_id']}`\n"
            f"💰 ₹{dep['amount']:,.2f} | 📌 {dep['method'].upper()}\n"
            f"🔖 Txn: {dep['txn_id'] or 'N/A'}\n"
            f"📅 {dep['date'][:16]}",
            reply_markup=approve_reject_deposit_kb(dep["id"])
        )


async def show_pending_withdrawals(callback: CallbackQuery):
    withdrawals = await db.get_pending_withdrawals()
    if not withdrawals:
        await callback.message.edit_text(
            f"💸 *PENDING WITHDRAWALS*\n{SEP}\nNo pending withdrawals.",
            parse_mode="Markdown",
            reply_markup=back_kb("admin_panel")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💸 *PENDING WITHDRAWALS* ({len(withdrawals)})\n{SEP}",
        parse_mode="Markdown",
        reply_markup=back_kb("admin_panel")
    )
    await callback.answer()

    for wd in withdrawals:
        await callback.message.answer(
            f"🆔 #{wd['id']} | 👤 `{wd['user_id']}`\n"
            f"💰 ₹{wd['amount']:,.2f}\n"
            f"🏦 UPI: {wd['upi_id']}\n"
            f"📅 {wd['date'][:16]}",
            reply_markup=approve_reject_withdraw_kb(wd["id"])
        )


async def show_admin_stats(callback: CallbackQuery):
    users = await db.get_all_users()
    total_balance = sum(u["balance"] for u in users)
    total_wagered = sum(u["total_wagered"] for u in users)

    await callback.message.edit_text(
        f"📊 *BOT STATS*\n{SEP}\n"
        f"👥 Total Users: *{len(users)}*\n"
        f"💰 Total Balance: *₹{total_balance:,.2f}*\n"
        f"🎰 Total Wagered: *₹{total_wagered:,.2f}*\n"
        f"{SEP}",
        parse_mode="Markdown",
        reply_markup=back_kb("admin_panel")
    )
    await callback.answer()


async def show_admin_settings(callback: CallbackQuery):
    min_wd = await db.get_setting("min_withdrawal")
    wd_enabled = await db.get_setting("withdraw_enabled")
    weekly = await db.get_setting("weekly_bonus")
    monthly = await db.get_setting("monthly_bonus")

    await callback.message.edit_text(
        f"⚙️ *SETTINGS*\n{SEP}\n"
        f"💸 Min Withdrawal: ₹{min_wd}\n"
        f"🔄 Withdrawals: {'🟢 ON' if wd_enabled == '1' else '🔴 OFF'}\n"
        f"🎁 Weekly Bonus: ₹{weekly}\n"
        f"📅 Monthly Bonus: ₹{monthly}\n"
        f"{SEP}\n"
        f"Commands:\n"
        f"`/setminwithdraw amount`\n"
        f"`/withdrawtoggle on/off`\n"
        f"`/setbonus weekly/monthly amount`",
        parse_mode="Markdown",
        reply_markup=back_kb("admin_panel")
    )
    await callback.answer()


async def cmd_set_min_withdraw(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: `/setminwithdraw 100`", parse_mode="Markdown")
        return
    try:
        amount = float(parts[1])
        if amount < 0:
            raise ValueError
        await db.set_setting("min_withdrawal", str(amount))
        await message.answer(success_text(f"Min withdrawal set to ₹{amount:,.2f}"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid amount."), parse_mode="Markdown")


async def cmd_withdraw_toggle(message: Message):
    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await message.answer("Usage: `/withdrawtoggle on` or `/withdrawtoggle off`", parse_mode="Markdown")
        return
    val = "1" if parts[1].lower() == "on" else "0"
    await db.set_setting("withdraw_enabled", val)
    status = "🟢 Enabled" if val == "1" else "🔴 Disabled"
    await message.answer(success_text(f"Withdrawals: {status}"), parse_mode="Markdown")


async def cmd_add_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/addbalance user_id amount`", parse_mode="Markdown")
        return
    try:
        target = int(parts[1])
        amount = float(parts[2])
        if amount <= 0:
            raise ValueError
        user = await db.get_user(target)
        if not user:
            await message.answer(error_text("User not found."), parse_mode="Markdown")
            return
        await db.update_balance(target, amount)
        await db.add_transaction(target, "deposit", amount, "admin_credit")
        await message.answer(success_text(f"Added ₹{amount:,.2f} to user `{target}`"), parse_mode="Markdown")
        try:
            await bot.send_message(target, success_text(f"Admin credited ₹{amount:,.2f} to your balance!"), parse_mode="Markdown")
        except:
            pass
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_remove_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/removebalance user_id amount`", parse_mode="Markdown")
        return
    try:
        target = int(parts[1])
        amount = float(parts[2])
        if amount <= 0:
            raise ValueError
        user = await db.get_user(target)
        if not user:
            await message.answer(error_text("User not found."), parse_mode="Markdown")
            return
        if user["balance"] < amount:
            await message.answer(error_text(f"User only has ₹{user['balance']:,.2f}"), parse_mode="Markdown")
            return
        await db.update_balance(target, -amount)
        await db.add_transaction(target, "withdraw", amount, "admin_debit")
        await message.answer(success_text(f"Removed ₹{amount:,.2f} from user `{target}`"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_set_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/setbalance user_id amount`", parse_mode="Markdown")
        return
    try:
        target = int(parts[1])
        amount = float(parts[2])
        if amount < 0:
            raise ValueError
        user = await db.get_user(target)
        if not user:
            await message.answer(error_text("User not found."), parse_mode="Markdown")
            return
        await db.set_balance(target, amount)
        await message.answer(success_text(f"Set balance of user `{target}` to ₹{amount:,.2f}"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_set_bonus(message: Message):
    parts = message.text.split()
    if len(parts) < 3 or parts[1].lower() not in ("weekly", "monthly"):
        await message.answer("Usage: `/setbonus weekly 50` or `/setbonus monthly 200`", parse_mode="Markdown")
        return
    try:
        key = f"{parts[1].lower()}_bonus"
        amount = float(parts[2])
        await db.set_setting(key, str(amount))
        await message.answer(success_text(f"{parts[1].capitalize()} bonus set to ₹{amount:,.2f}"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_broadcast(message: Message, bot: Bot):
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer("Usage: `/broadcast your message here`", parse_mode="Markdown")
        return
    text = parts[1]
    users = await db.get_all_users()
    sent, failed = 0, 0

    await message.answer(f"📢 Broadcasting to {len(users)} users...", parse_mode="Markdown")

    for user in users:
        try:
            await bot.send_message(
                user["user_id"],
                f"📢 *ANNOUNCEMENT*\n{SEP}\n{text}",
                parse_mode="Markdown"
            )
            sent += 1
        except Exception as e:
            failed += 1
            logger.debug(f"Broadcast failed for {user['user_id']}: {e}")

    await message.answer(
        success_text(f"Broadcast complete!\n✅ Sent: {sent}\n❌ Failed: {failed}"),
        parse_mode="Markdown"
    )


async def cmd_set_bonus_eligible(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: `/seteligible user_id`", parse_mode="Markdown")
        return
    try:
        target = int(parts[1])
        user = await db.get_user(target)
        if not user:
            await message.answer(error_text("User not found."), parse_mode="Markdown")
            return
        new_val = 0 if user["bonus_eligible"] else 1
        await db.set_bonus_eligible(target, new_val)
        status = "eligible" if new_val else "ineligible"
        await message.answer(success_text(f"User `{target}` is now bonus {status}."), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")
