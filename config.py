import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip()]
STAR_PAYMENT_ID = os.getenv("STAR_PAYMENT_ID", "")
UPI_ID = os.getenv("UPI_ID", "")
DEFAULT_MIN_WITHDRAWAL = float(os.getenv("DEFAULT_MIN_WITHDRAWAL", "100"))
REFERRAL_PERCENT = float(os.getenv("REFERRAL_PERCENT", "0.01"))

WIN_MULTIPLIER = 2.0
TAX_PERCENT = 0.10
DEPOSIT_TAX = 0.05
COOLDOWN_SECONDS = 3
DB_PATH = "casino.db"
LOG_FILE = "bot.log"
