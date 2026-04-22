from aiogram.types import Message, CallbackQuery, LabeledPrice
from aiogram import Bot
from database import db
from config import ADMIN_IDS
from ui.keyboards import approve_reject_deposit_kb, back_kb, paid_confirm_kb
from ui.messages import success_text, error_text, SEP
from utils.logger import logger


async def show_deposit_stars(callback: CallbackQuery, bot: Bot, state):
    """Send native Telegram Stars invoice."""
    await callback.answer()
    await callback.message.answer(
        f"⭐ *STARS DEPOSIT*\n{SEP}\nHow many Stars worth of balance do you want to add?\n\nSend amount in ₹ (e.g. `100`):",
        parse_mode="Markdown",
        reply_markup=back_kb("wallet_deposit")
    )
    from aiogram.fsm.state import State
    await state.set_state("DepositFSM:stars_amount")


async def send_stars_invoice(message: Message, bot: Bot, amount_inr: float):
    """Send native Telegram Stars payment invoice."""
    # 1 Star ≈ ₹1 (adjust rate as needed)
    stars_count = max(1, int(amount_inr))

    did = await db.create_deposit(message.from_user.id, "stars", amount_inr)

    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="💰 Add Balance",
            description=f"Add ₹{amount_inr:,.0f} to your Casino wallet",
            payload=f"deposit_{did}_{message.from_user.id}",
            currency="XTR",  # Telegram Stars currency code
            prices=[LabeledPrice(label=f"₹{amount_inr:,.0f} Balance", amount=stars_count)],
        )
    except Exception as e:
        logger.error(f"Stars invoice error: {e}")
        await message.answer(error_text(f"Stars payment unavailable: {e}"), parse_mode="Markdown")


async def show_deposit_upi(callback: CallbackQuery, bot: Bot):
    upi_id = await db.get_setting("upi_id") or "Not configured"
    qr_file_id = await db.get_setting("upi_qr") or ""

    text = (
        f"🏦 *DEPOSIT VIA UPI*\n{SEP}\n"
        f"💳 UPI ID:\n`{upi_id}`\n\n"
        f"📌 Steps:\n"
        f"1️⃣ Send money to above UPI\n"
        f"2️⃣ Reply here: `amount txn_id`\n"
        f"   Example: `500 TXN123456`\n"
        f"{SEP}\n⚠️ 5% fee applies"
    )

    try:
        if qr_file_id:
            await callback.message.answer_photo(
                photo=qr_file_id,
                caption=text,
                parse_mode="Markdown",
                reply_markup=back_kb("wallet_deposit")
            )
            try:
                await callback.message.delete()
            except:
                pass
        else:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=back_kb("wallet_deposit"))
    except Exception as e:
        logger.error(f"show_deposit_upi error: {e}")
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=back_kb("wallet_deposit"))

    await callback.answer()


async def process_stars_payment(pre_checkout_query, bot: Bot):
    """Approve pre-checkout automatically."""
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


async def handle_successful_payment(message: Message, bot: Bot):
    """Handle completed Stars payment."""
    payload = message.successful_payment.invoice_payload
    stars_paid = message.successful_payment.total_amount

    try:
        parts = payload.split("_")
        did = int(parts[1])
        user_id = int(parts[2])
    except:
        logger.error(f"Bad payment payload: {payload}")
        return

    deposit = await db.get_deposit(did)
    if not deposit:
        return

    amount = deposit["amount"]
    tax = amount * 0.05
    credited = amount - tax

    await db.update_deposit_status(did, "approved")
    await db.update_balance(user_id, credited)
    await db.add_transaction(user_id, "deposit", credited)

    await message.answer(
        success_text(
            f"⭐ Stars Payment Received!\n"
            f"💰 Credited: ₹{credited:,.2f}\n"
            f"⭐ Stars Paid: {stars_paid}\n"
            f"🧾 Fee (5%): -₹{tax:,.2f}"
        ),
        parse_mode="Markdown",
        reply_markup=back_kb()
    )

    user = await db.get_user(user_id)
    uname = user.get("username", str(user_id)) if user else str(user_id)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"⭐ *STARS PAYMENT CONFIRMED*\n{SEP}\n"
                f"👤 @{uname} (`{user_id}`)\n"
                f"💰 ₹{credited:,.2f} credited | Stars: {stars_paid}",
                parse_mode="Markdown"
            )
        except:
            pass

    logger.info(f"Stars payment: user={user_id} credited={credited} stars={stars_paid}")


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
        await callback.answer("Not found!", show_alert=True); return
    if deposit["status"] != "pending":
        await callback.answer("Already processed!", show_alert=True); return

    tax = deposit["amount"] * 0.05
    credited = deposit["amount"] - tax

    await db.update_deposit_status(did, "approved")
    await db.update_balance(deposit["user_id"], credited)
    await db.add_transaction(deposit["user_id"], "deposit", credited)

    await callback.message.edit_text(
        f"✅ *DEPOSIT APPROVED* #{did}\nCredited: ₹{credited:,.2f}", parse_mode="Markdown"
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
        await callback.answer("Not found!", show_alert=True); return
    if deposit["status"] != "pending":
        await callback.answer("Already processed!", show_alert=True); return

    await db.update_deposit_status(did, "rejected")
    await callback.message.edit_text(f"❌ Deposit #{did} rejected.", parse_mode="Markdown")
    try:
        await bot.send_message(
            deposit["user_id"],
            error_text(f"Deposit #{did} rejected. Contact support."),
            parse_mode="Markdown"
        )
    except:
        pass
    await callback.answer("❌ Rejected!")
