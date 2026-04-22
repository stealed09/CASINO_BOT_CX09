from aiogram.types import Message, CallbackQuery
from aiogram import Bot
from database import db
from config import ADMIN_IDS
from ui.keyboards import approve_reject_deposit_kb, back_kb, paid_confirm_kb
from ui.messages import success_text, error_text, SEP
from utils.logger import logger


async def show_deposit_stars(callback: CallbackQuery):
    star_id = await db.get_setting("star_payment_id") or "Not configured"
    await callback.message.edit_text(
        f"⭐ *DEPOSIT VIA TELEGRAM STARS*\n{SEP}\n"
        f"📋 Payment ID:\n`{star_id}`\n\n"
        f"📌 Steps:\n"
        f"1️⃣ Send stars to above ID\n"
        f"2️⃣ Enter amount below\n"
        f"3️⃣ Click 'I Have Paid'\n"
        f"4️⃣ Admin verifies & credits\n"
        f"{SEP}\n⚠️ 5% fee applies\nSend deposit amount (₹):",
        parse_mode="Markdown",
        reply_markup=back_kb("wallet_deposit")
    )
    await callback.answer()


async def show_deposit_upi(callback: CallbackQuery, bot: Bot):
    upi_id = await db.get_setting("upi_id") or "Not configured"
    qr_file_id = await db.get_setting("upi_qr") or ""

    text = (
        f"🏦 *DEPOSIT VIA UPI*\n{SEP}\n"
        f"💳 UPI ID:\n`{upi_id}`\n\n"
        f"📌 Steps:\n"
        f"1️⃣ Send money to above UPI\n"
        f"2️⃣ Reply: `amount txn_id`\n"
        f"   Example: `500 TXN123456`\n"
        f"{SEP}\n⚠️ 5% fee applies"
    )

    if qr_file_id:
        await callback.message.answer_photo(
            photo=qr_file_id,
            caption=text,
            parse_mode="Markdown",
            reply_markup=back_kb("wallet_deposit")
        )
        await callback.message.delete()
    else:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_kb("wallet_deposit"))
    await callback.answer()


async def process_stars_deposit(message: Message, bot: Bot, amount: float):
    user_id = message.from_user.id
    did = await db.create_deposit(user_id, "stars", amount)
    user = await db.get_user(user_id)
    uname = user.get("username", str(user_id)) if user else str(user_id)

    await message.answer(
        f"⭐ *DEPOSIT REQUEST SENT*\n{SEP}\n"
        f"💰 Amount: *₹{amount:,.2f}*\n"
        f"🆔 Request ID: *#{did}*\n\n"
        f"⏳ Waiting for admin approval...",
        parse_mode="Markdown",
        reply_markup=paid_confirm_kb(did)
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⭐ *NEW STARS DEPOSIT*\n{SEP}\n"
                f"👤 @{uname} (`{user_id}`)\n"
                f"💰 ₹{amount:,.2f} | ID: *#{did}*",
                parse_mode="Markdown",
                reply_markup=approve_reject_deposit_kb(did)
            )
        except Exception as e:
            logger.error(f"Admin notify failed: {e}")


async def process_upi_deposit(message: Message, bot: Bot, amount: float, txn_id: str):
    user_id = message.from_user.id
    did = await db.create_deposit(user_id, "upi", amount, txn_id)
    user = await db.get_user(user_id)
    uname = user.get("username", str(user_id)) if user else str(user_id)

    await message.answer(
        success_text(
            f"UPI Deposit Request Sent!\n"
            f"💰 Amount: ₹{amount:,.2f}\n"
            f"🔖 Txn: {txn_id} | ID: #{did}\n"
            f"⏳ Awaiting admin approval..."
        ),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🏦 *NEW UPI DEPOSIT*\n{SEP}\n"
                f"👤 @{uname} (`{user_id}`)\n"
                f"💰 ₹{amount:,.2f} | Txn: `{txn_id}`\n"
                f"ID: *#{did}*",
                parse_mode="Markdown",
                reply_markup=approve_reject_deposit_kb(did)
            )
        except Exception as e:
            logger.error(f"Admin notify failed: {e}")


async def approve_deposit(callback: CallbackQuery, bot: Bot, did: int):
    deposit = await db.get_deposit(did)
    if not deposit:
        await callback.answer("Not found!", show_alert=True)
        return
    if deposit["status"] != "pending":
        await callback.answer("Already processed!", show_alert=True)
        return

    tax = deposit["amount"] * 0.05
    credited = deposit["amount"] - tax

    await db.update_deposit_status(did, "approved")
    await db.update_balance(deposit["user_id"], credited)
    await db.add_transaction(deposit["user_id"], "deposit", credited)

    await callback.message.edit_text(
        f"✅ *DEPOSIT APPROVED* #{did}\n"
        f"Credited: ₹{credited:,.2f} (after 5% fee)",
        parse_mode="Markdown"
    )
    try:
        await bot.send_message(
            deposit["user_id"],
            success_text(f"Deposit approved!\n💰 Credited: ₹{credited:,.2f}"),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"User notify failed: {e}")
    await callback.answer("✅ Approved!")


async def reject_deposit(callback: CallbackQuery, bot: Bot, did: int):
    deposit = await db.get_deposit(did)
    if not deposit:
        await callback.answer("Not found!", show_alert=True)
        return
    if deposit["status"] != "pending":
        await callback.answer("Already processed!", show_alert=True)
        return

    await db.update_deposit_status(did, "rejected")
    await callback.message.edit_text(f"❌ Deposit #{did} rejected.", parse_mode="Markdown")
    try:
        await bot.send_message(
            deposit["user_id"],
            error_text(f"Deposit #{did} rejected. Contact support."),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"User notify failed: {e}")
    await callback.answer("❌ Rejected!")
