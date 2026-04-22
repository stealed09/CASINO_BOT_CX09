import io
import qrcode
from aiogram.types import Message, CallbackQuery, LabeledPrice, BufferedInputFile
from aiogram import Bot
from database import db
from config import ADMIN_IDS
from ui.keyboards import approve_reject_deposit_kb, back_kb, upi_paid_done_kb
from ui.messages import success_text, error_text, SEP
from utils.logger import logger


async def generate_upi_qr(upi_id: str, amount: float) -> BufferedInputFile:
    """Generate a UPI QR code for a specific amount."""
    upi_string = f"upi://pay?pa={upi_id}&am={amount:.2f}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(upi_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return BufferedInputFile(buf.read(), filename="upi_qr.png")


async def start_upi_deposit(message: Message, bot: Bot, amount: float):
    """Step 1: Generate QR for the amount and show Payment Done button."""
    upi_id = await db.get_setting("upi_id") or "notset@upi"

    # Create a pending deposit record first
    did = await db.create_deposit(message.from_user.id, "upi", amount)

    # Generate QR
    try:
        qr_file = await generate_upi_qr(upi_id, amount)
        await message.answer_photo(
            photo=qr_file,
            caption=(
                f"🏦 *UPI PAYMENT*\n{SEP}\n"
                f"💰 Amount: *₹{amount:,.2f}*\n"
                f"🏦 UPI ID: `{upi_id}`\n\n"
                f"📌 Scan QR or pay to UPI ID above\n"
                f"After payment click ✅ *Payment Done*\n"
                f"{SEP}\n"
                f"🆔 Request ID: *#{did}*"
            ),
            parse_mode="Markdown",
            reply_markup=upi_paid_done_kb(did)
        )
    except Exception as e:
        logger.error(f"QR generation error: {e}")
        await message.answer(
            f"🏦 *UPI PAYMENT*\n{SEP}\n"
            f"💰 Amount: *₹{amount:,.2f}*\n"
            f"🏦 UPI ID: `{upi_id}`\n\n"
            f"Pay the above amount and click ✅ Done\n"
            f"🆔 Request ID: *#{did}*",
            parse_mode="Markdown",
            reply_markup=upi_paid_done_kb(did)
        )


async def show_deposit_stars(callback: CallbackQuery):
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"⭐ *STARS DEPOSIT*\n{SEP}\n"
            f"Send the amount in ₹ you want to deposit:\nExample: `100`",
            parse_mode="Markdown",
            reply_markup=back_kb("wallet_deposit")
        )
    except:
        await callback.message.answer(
            "Send amount in ₹:", reply_markup=back_kb("wallet_deposit")
        )


async def send_stars_invoice(message: Message, bot: Bot, amount_inr: float):
    stars_count = max(1, int(amount_inr))
    did = await db.create_deposit(message.from_user.id, "stars", amount_inr)
    try:
        await bot.send_invoice(
            chat_id=message.chat.id,
            title="💰 Add Balance",
            description=f"Add ₹{amount_inr:,.0f} to your Casino wallet",
            payload=f"deposit_{did}_{message.from_user.id}",
            currency="XTR",
            prices=[LabeledPrice(label=f"₹{amount_inr:,.0f} Balance", amount=stars_count)],
        )
    except Exception as e:
        logger.error(f"Stars invoice error: {e}")
        await message.answer(error_text(f"Stars payment error: {e}"), parse_mode="Markdown")


async def process_stars_payment(pre_checkout_query, bot: Bot):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


async def handle_successful_payment(message: Message, bot: Bot):
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

    dep_tax_pct = float(await db.get_setting("deposit_tax") or "5")
    amount = deposit["amount"]
    tax = round(amount * dep_tax_pct / 100, 2)
    credited = round(amount - tax, 2)

    await db.update_deposit_status(did, "approved")
    await db.update_balance(user_id, credited)
    await db.add_transaction(user_id, "deposit", credited)

    await message.answer(
        success_text(
            f"⭐ Stars Payment Received!\n"
            f"💰 Credited: ₹{credited:,.2f}\n"
            f"⭐ Stars: {stars_paid}\n"
            f"🧾 Tax ({dep_tax_pct}%): -₹{tax:,.2f}"
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
                f"⭐ *STARS CONFIRMED*\n{SEP}\n"
                f"👤 @{uname} (`{user_id}`)\n"
                f"💰 ₹{credited:,.2f} credited | Stars: {stars_paid}",
                parse_mode="Markdown"
            )
        except:
            pass


async def approve_deposit(callback: CallbackQuery, bot: Bot, did: int):
    deposit = await db.get_deposit(did)
    if not deposit:
        await callback.answer("Not found!", show_alert=True); return
    if deposit["status"] != "pending":
        await callback.answer("Already processed!", show_alert=True); return

    dep_tax_pct = float(await db.get_setting("deposit_tax") or "5")
    tax = round(deposit["amount"] * dep_tax_pct / 100, 2)
    credited = round(deposit["amount"] - tax, 2)

    await db.update_deposit_status(did, "approved")
    await db.update_balance(deposit["user_id"], credited)
    await db.add_transaction(deposit["user_id"], "deposit", credited)

    try:
        await callback.message.edit_caption(
            f"✅ *DEPOSIT APPROVED* #{did}\n"
            f"💰 ₹{deposit['amount']:,.2f} → Credited: ₹{credited:,.2f} (Tax: {dep_tax_pct}%)",
            parse_mode="Markdown"
        )
    except:
        try:
            await callback.message.edit_text(
                f"✅ *DEPOSIT APPROVED* #{did}\n"
                f"💰 ₹{deposit['amount']:,.2f} → Credited: ₹{credited:,.2f}",
                parse_mode="Markdown"
            )
        except:
            pass

    try:
        await bot.send_message(
            deposit["user_id"],
            success_text(f"Deposit approved!\n💰 Credited: ₹{credited:,.2f}\n🧾 Tax ({dep_tax_pct}%): -₹{tax:,.2f}"),
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
    try:
        await callback.message.edit_caption(f"❌ Deposit #{did} rejected.", parse_mode="Markdown")
    except:
        try:
            await callback.message.edit_text(f"❌ Deposit #{did} rejected.", parse_mode="Markdown")
        except:
            pass

    try:
        await bot.send_message(
            deposit["user_id"],
            error_text(f"Deposit #{did} rejected. Contact support."),
            parse_mode="Markdown"
        )
    except:
        pass
    await callback.answer("❌ Rejected!")
