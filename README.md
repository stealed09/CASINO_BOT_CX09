# 🎰 Casino Bot — Production Deployment Guide

## ─── RAILWAY DEPLOYMENT ───────────────────────────────────────

### Step 1: Prepare Repository
1. Create a new GitHub repo
2. Push all files to root of the repo

### Step 2: Create Railway Project
1. Go to https://railway.app
2. Click "New Project" → "Deploy from GitHub Repo"
3. Select your repo

### Step 3: Set Environment Variables
In Railway dashboard → Variables tab, add:
```
BOT_TOKEN=your_bot_token
ADMIN_IDS=123456789
STAR_PAYMENT_ID=your_star_id
UPI_ID=yourname@upi
DEFAULT_MIN_WITHDRAWAL=100
REFERRAL_PERCENT=0.01
```

### Step 4: Add Persistent Volume (CRITICAL for data persistence)
1. In Railway project → click your service
2. Go to "Volumes" tab
3. Click "Add Volume"
4. Mount path: `/app/data`
5. Update DB_PATH in config.py to `/app/data/casino.db`

> ⚠️ Without a volume, data resets on every redeploy!

### Step 5: Set Start Command
In Railway → Settings → Deploy:
```
python main.py
```

### Step 6: Deploy
Click "Deploy" — Railway will install requirements.txt and start.

---

## ─── VPS DEPLOYMENT (Ubuntu/Debian) ─────────────────────────

### Step 1: Install Python
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv git -y
```

### Step 2: Clone / Upload your bot
```bash
mkdir -p /opt/casinobot
cd /opt/casinobot
# Upload files via SFTP or git clone
```

### Step 3: Create Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 4: Create .env file
```bash
cp .env.example .env
nano .env
# Fill in your values
```

### Step 5: Run as systemd service (auto-restart on crash/reboot)
```bash
sudo nano /etc/systemd/system/casinobot.service
```

Paste:
```ini
[Unit]
Description=Telegram Casino Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/casinobot
ExecStart=/opt/casinobot/venv/bin/python main.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/casinobot/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable casinobot
sudo systemctl start casinobot
sudo systemctl status casinobot
```

### Step 6: View logs
```bash
sudo journalctl -u casinobot -f
# Or
tail -f /opt/casinobot/bot.log
```

### Data Persistence
- SQLite database saved at: `casino.db` (same directory)
- Data persists across restarts automatically
- Backup: `cp casino.db casino.db.backup`

---

## ─── ADMIN COMMANDS ──────────────────────────────────────────

| Command | Description |
|---|---|
| `/admin` | Open admin panel |
| `/addbalance user_id amount` | Add balance to user |
| `/removebalance user_id amount` | Remove balance from user |
| `/setbalance user_id amount` | Set exact balance |
| `/setminwithdraw amount` | Set min withdrawal |
| `/withdrawtoggle on/off` | Enable/disable withdrawals |
| `/setbonus weekly/monthly amount` | Set bonus amounts |
| `/broadcast message` | Send to all users |
| `/seteligible user_id` | Toggle bonus eligibility |
| `/reply user_id message` | Reply to support message |

## ─── USER COMMANDS ───────────────────────────────────────────

| Command | Description |
|---|---|
| `/start` | Register & main menu |
| `/balance` | Check wallet |
| `/dice amount` | Play dice |
| `/bask amount` | Play basketball |
| `/ball amount` | Play soccer |
| `/bowl amount` | Play bowling |
| `/darts amount` | Play darts |
| `/limbo amount` | Play limbo |
| `/coinflip amount` | Play coin flip |
| `/deposit` | Deposit menu |
| `/withdraw amount upi_id` | Withdraw funds |
| `/support` | Contact support |
