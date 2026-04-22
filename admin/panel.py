from aiogram.types import Message, CallbackQuery
from aiogram import Bot
from database import db
from config import ADMIN_IDS
from ui.keyboards import admin_panel_kb, admin_settings_kb, approve_reject_deposit_kb, approve_reject_withdraw_kb, back_kb
from ui.messages import SEP, success_text, error_text
from utils.logger import logger


async def show_admin_panel(message: Message):
    users = await db.get_all_users()
    await message.answer(
        f"🔐 *ADMIN PANEL*\n{SEP}\n👥 Users: *{len(users)}*\n{SEP}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )


async def show_pending_deposits(callback: CallbackQuery):
    deposits = await db.get_pending_deposits()
    if not deposits:
        await callback.message.edit_text(
            f"💳 *PENDING DEPOSITS*\n{SEP}\nNone pending.",
            parse_mode="Markdown", reply_markup=back_kb("admin_panel")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💳 *PENDING DEPOSITS* ({len(deposits)})\n{SEP}\nSending details below...",
        parse_mode="Markdown", reply_markup=back_kb("admin_panel")
    )
    await callback.answer()

    for dep in deposits:
        caption = (
            f"🆔 #{dep['id']} | 👤 `{dep['user_id']}`\n"
            f"💰 ₹{dep['amount']:,.2f} | {dep['method'].upper()}\n"
            f"🔖 Txn: {dep['txn_id'] or 'Pending'}\n"
            f"📅 {dep['date'][:16]}"
        )
        ss_id = dep.get("screenshot_id", "")
        try:
            if ss_id:
                await callback.message.answer_photo(
                    photo=ss_id,
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=approve_reject_deposit_kb(dep["id"])
                )
            else:
                await callback.message.answer(
                    caption,
                    parse_mode="Markdown",
                    reply_markup=approve_reject_deposit_kb(dep["id"])
                )
        except:
            await callback.message.answer(
                caption, parse_mode="Markdown",
                reply_markup=approve_reject_deposit_kb(dep["id"])
            )


async def show_pending_withdrawals(callback: CallbackQuery):
    wds = await db.get_pending_withdrawals()
    if not wds:
        await callback.message.edit_text(
            f"💸 *PENDING WITHDRAWALS*\n{SEP}\nNone pending.",
            parse_mode="Markdown", reply_markup=back_kb("admin_panel")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        f"💸 *PENDING WITHDRAWALS* ({len(wds)})\n{SEP}",
        parse_mode="Markdown", reply_markup=back_kb("admin_panel")
    )
    for wd in wds:
        wd_tax = float(await db.get_setting("withdrawal_tax") or "0")
        tax = round(wd["amount"] * wd_tax / 100, 2)
        net = round(wd["amount"] - tax, 2)
        await callback.message.answer(
            f"🆔 #{wd['id']} | 👤 `{wd['user_id']}`\n"
            f"💰 ₹{wd['amount']:,.2f} | Tax: ₹{tax:,.2f} | Net: ₹{net:,.2f}\n"
            f"🏦 UPI: `{wd['upi_id']}`\n"
            f"📅 {wd['date'][:16]}",
            parse_mode="Markdown",
            reply_markup=approve_reject_withdraw_kb(wd["id"])
        )
    await callback.answer()


async def show_admin_stats(callback: CallbackQuery):
    users = await db.get_all_users()
    total_bal = sum(u["balance"] for u in users)
    total_wag = sum(u["total_wagered"] for u in users)
    dep_tax = await db.get_setting("deposit_tax")
    wd_tax = await db.get_setting("withdrawal_tax")
    ref_pct = await db.get_setting("referral_percent")

    await callback.message.edit_text(
        f"📊 *BOT STATS*\n{SEP}\n"
        f"👥 Users: *{len(users)}*\n"
        f"💰 Total Balance: *₹{total_bal:,.2f}*\n"
        f"🎰 Total Wagered: *₹{total_wag:,.2f}*\n"
        f"📥 Deposit Tax: *{dep_tax}%*\n"
        f"📤 Withdraw Tax: *{wd_tax}%*\n"
        f"🤝 Referral: *{ref_pct}%*\n{SEP}",
        parse_mode="Markdown", reply_markup=back_kb("admin_panel")
    )
    await callback.answer()


async def show_admin_settings(callback: CallbackQuery):
    min_wd = await db.get_setting("min_withdrawal")
    wd_en = await db.get_setting("withdraw_enabled")
    weekly = await db.get_setting("weekly_bonus")
    monthly = await db.get_setting("monthly_bonus")
    mode = await db.get_setting("bonus_mode")
    upi = await db.get_setting("upi_id")
    dep_tax = await db.get_setting("deposit_tax")
    wd_tax = await db.get_setting("withdrawal_tax")
    ref_pct = await db.get_setting("referral_percent")
    tag = await db.get_setting("bot_username_tag")

    await callback.message.edit_text(
        f"⚙️ *SETTINGS*\n{SEP}\n"
        f"💸 Min Withdrawal: ₹{min_wd}\n"
        f"🔄 Withdrawals: {'🟢 ON' if wd_en == '1' else '🔴 OFF'}\n"
        f"🎁 Weekly Bonus: ₹{weekly}\n"
        f"📅 Monthly Bonus: ₹{monthly}\n"
        f"🎰 Bonus Mode: *{mode}*\n"
        f"🏷️ Bot Tag: @{tag or 'not set'}\n"
        f"🏦 UPI: `{upi}`\n"
        f"📥 Deposit Tax: *{dep_tax}%*\n"
        f"📤 Withdraw Tax: *{wd_tax}%*\n"
        f"🤝 Referral %: *{ref_pct}%*\n{SEP}",
        parse_mode="Markdown",
        reply_markup=admin_settings_kb()
    )
    await callback.answer()


async def cmd_add_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/addbalance user_id amount`", parse_mode="Markdown"); return
    try:
        target, amount = int(parts[1]), float(parts[2])
        user = await db.get_user(target)
        if not user:
            await message.answer(error_text("User not found."), parse_mode="Markdown"); return
        await db.update_balance(target, amount)
        await db.add_transaction(target, "deposit", amount, "admin_credit")
        await message.answer(success_text(f"Added ₹{amount:,.2f} to `{target}`"), parse_mode="Markdown")
        try:
            await bot.send_message(target, success_text(f"Admin credited ₹{amount:,.2f}!"), parse_mode="Markdown")
        except: pass
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_remove_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/removebalance user_id amount`", parse_mode="Markdown"); return
    try:
        target, amount = int(parts[1]), float(parts[2])
        user = await db.get_user(target)
        if not user or user["balance"] < amount:
            await message.answer(error_text("User not found or insufficient balance."), parse_mode="Markdown"); return
        await db.update_balance(target, -amount)
        await db.add_transaction(target, "withdraw", amount, "admin_debit")
        await message.answer(success_text(f"Removed ₹{amount:,.2f} from `{target}`"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_set_balance(message: Message, bot: Bot):
    parts = message.text.split()
    if len(parts) < 3:
        await message.answer("Usage: `/setbalance user_id amount`", parse_mode="Markdown"); return
    try:
        target, amount = int(parts[1]), float(parts[2])
        if not await db.get_user(target):
            await message.answer(error_text("User not found."), parse_mode="Markdown"); return
        await db.set_balance(target, amount)
        await message.answer(success_text(f"Balance of `{target}` set to ₹{amount:,.2f}"), parse_mode="Markdown")
    except:
        await message.answer(error_text("Invalid input."), parse_mode="Markdown")


async def cmd_broadcast(message: Message, bot: Bot):
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        await message.answer("Usage: `/broadcast message`", parse_mode="Markdown"); return
    users = await db.get_all_users()
    sent = failed = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], f"📢 *ANNOUNCEMENT*\n{SEP}\n{parts[1]}", parse_mode="Markdown")
            sent += 1
        except: failed += 1
    await message.answer(success_text(f"Sent: {sent} | Failed: {failed}"), parse_mode="Markdown")
