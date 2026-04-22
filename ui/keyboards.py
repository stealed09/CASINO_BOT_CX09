from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎮 Play Games", callback_data="menu_games"),
        InlineKeyboardButton(text="💰 Wallet", callback_data="menu_wallet")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Bonus", callback_data="menu_bonus"),
        InlineKeyboardButton(text="🤝 Referral", callback_data="menu_referral")
    )
    builder.row(
        InlineKeyboardButton(text="🆘 Support", callback_data="menu_support"),
        InlineKeyboardButton(text="📊 History", callback_data="menu_history")
    )
    if is_admin:
        builder.row(InlineKeyboardButton(text="🔐 Admin Panel", callback_data="admin_panel"))
    return builder.as_markup()


def games_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🎲 Dice", callback_data="game_dice"),
        InlineKeyboardButton(text="🏀 Basketball", callback_data="game_bask")
    )
    builder.row(
        InlineKeyboardButton(text="⚽ Soccer", callback_data="game_ball"),
        InlineKeyboardButton(text="🎳 Bowling", callback_data="game_bowl")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Darts", callback_data="game_darts"),
        InlineKeyboardButton(text="🚀 Limbo", callback_data="game_limbo")
    )
    builder.row(InlineKeyboardButton(text="🪙 Coin Flip", callback_data="game_coinflip"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="menu_main"))
    return builder.as_markup()


def wallet_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Deposit", callback_data="wallet_deposit"),
        InlineKeyboardButton(text="💸 Withdraw", callback_data="wallet_withdraw")
    )
    builder.row(
        InlineKeyboardButton(text="📋 History", callback_data="menu_history"),
        InlineKeyboardButton(text="🔙 Back", callback_data="menu_main")
    )
    return builder.as_markup()


def deposit_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ Telegram Stars", callback_data="deposit_stars"),
        InlineKeyboardButton(text="🏦 UPI / QR", callback_data="deposit_upi")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="menu_wallet"))
    return builder.as_markup()


def back_to_main_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🏠 Main Menu", callback_data="menu_main"),
        InlineKeyboardButton(text="🎮 Play Again", callback_data="menu_games")
    )
    return builder.as_markup()


def back_kb(callback: str = "menu_main") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data=callback))
    return builder.as_markup()


def coinflip_choice_kb(amount: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👑 Heads", callback_data=f"cf_heads_{amount}"),
        InlineKeyboardButton(text="🦅 Tails", callback_data=f"cf_tails_{amount}")
    )
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="menu_games"))
    return builder.as_markup()


def admin_panel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Deposits", callback_data="admin_deposits"),
        InlineKeyboardButton(text="💸 Withdrawals", callback_data="admin_withdrawals")
    )
    builder.row(
        InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats")
    )
    builder.row(InlineKeyboardButton(text="⚙️ Settings", callback_data="admin_settings"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="menu_main"))
    return builder.as_markup()


def admin_settings_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💸 Min Withdrawal", callback_data="aset_minwd"),
        InlineKeyboardButton(text="🔄 Toggle Withdraw", callback_data="aset_wdtoggle")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Weekly Bonus", callback_data="aset_weekly"),
        InlineKeyboardButton(text="📅 Monthly Bonus", callback_data="aset_monthly")
    )
    builder.row(
        InlineKeyboardButton(text="🎰 Bonus Mode", callback_data="aset_bonusmode"),
        InlineKeyboardButton(text="🏷️ Bot Tag", callback_data="aset_bottag")
    )
    builder.row(
        InlineKeyboardButton(text="🏦 Set UPI ID", callback_data="aset_upi"),
        InlineKeyboardButton(text="📸 Set UPI QR", callback_data="aset_qr")
    )
    builder.row(InlineKeyboardButton(text="⭐ Star Pay ID", callback_data="aset_star"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="admin_panel"))
    return builder.as_markup()


def approve_reject_deposit_kb(did: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Approve", callback_data=f"dep_approve_{did}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"dep_reject_{did}")
    )
    return builder.as_markup()


def approve_reject_withdraw_kb(wid: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Approve", callback_data=f"wd_approve_{wid}"),
        InlineKeyboardButton(text="❌ Reject", callback_data=f"wd_reject_{wid}")
    )
    return builder.as_markup()


def paid_confirm_kb(did: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ I Have Paid", callback_data=f"deposit_confirm_{did}"))
    builder.row(InlineKeyboardButton(text="❌ Cancel", callback_data="menu_wallet"))
    return builder.as_markup()


def bonus_claim_kb(can_weekly: bool, can_monthly: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_weekly:
        builder.row(InlineKeyboardButton(text="🗓️ Claim Weekly Bonus", callback_data="bonus_claim_weekly"))
    if can_monthly:
        builder.row(InlineKeyboardButton(text="📅 Claim Monthly Bonus", callback_data="bonus_claim_monthly"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="menu_main"))
    return builder.as_markup()
