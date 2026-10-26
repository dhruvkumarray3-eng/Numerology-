<div align="center">

# ⚡ NUMBOTT ⚡

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=24&pause=1000&color=00F0FF&center=true&vCenter=true&width=500&lines=Advanced+Telegram+Account+Shop+Bot;Modular+%2B+Asynchronous+%2B+Python;Custom+UI+%2B+Dynamic+Must-Join" alt="Typing SVG" />
</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![SQLite](https://img.shields.io/badge/Database-SQLite-orange?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-red?style=for-the-badge)](LICENSE)

</div>

---

## 🌟 Key Features

* 🚀 **Modular Architecture:** Cleanly organized plugins (`buy`, `deposit`, `profile`, `admin`, `callbacks`, `start`).
* 🎨 **Dynamic Keyboard & Modern UI:** Sleek styling with custom emojis, colors, and responsive inline/reply keyboards.
* 🔐 **Smart Must-Join Verification:** Auto-detects remaining channels and dynamically updates UI as users join.
* 💳 **Multi-Payment Gateways:** Supports automatic/manual Crypto (CWallet) and Indian UPI Payment options.
* 📦 **Automatic Stock & OTP System:** Complete session buying flow with built-in OTP retrieval and account state handling.
* 📊 **Multi-Log Channel Support:** Instant deposit alerts and administrative auditing sent across designated log channels.
* ⚡ **Anti-Bypass Referral Engine:** Secure referral tracking to guarantee bonuses apply strictly to unique, verified users.

---

## 🛠️ Environment Configuration (`.env`)

For local development, keep the `.env` file untracked by Git. On Replit, set real values only in Replit Secrets. Never commit actual credentials or private channel details.

```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_user_id
SUPER_ADMIN_ID=your_telegram_user_id

# Logging Channels
LOG_CHANNEL_ID=your_log_channel_id
LOG_CHANNEL_ID_2=your_second_log_channel_id

# Must Join Verification Setup
CHECK_CHANNELS=channel_id_1,channel_id_2
JOIN_URLS=https://t.me/your_channel,https://t.me/your_invite

# Payment Credentials
CWALLET_ID=your_cwallet_id
UPI_ID=your_upi_id
```

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/dhruvkumarray3-eng/Numerology-.git
cd Numerology-
```

### 2. Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Bot
```bash
python main.py
```

---

## 💻 Tech Stack

- **Core Engine:** [Python 3.10+](https://www.python.org/)
- **Database:** SQLite3
- **Process Manager:** `tmux` / Background Daemon execution

---

## 👤 Developer & Credits

<div align="center">

Developed with ❤️ by **[𝐌꧊᱂ 𝁛 ꪜᛧƖƖ𝛂ᛧ𝝶](https://t.me/I_VIP_RADHE_II)**

</div>\n\n## Replit deployment\n\nThis bot can run on Replit with Python 3.10+ and the values listed in .env.sample. Set the required Telegram secrets in the deployment environment, then start it with:\n\n```bash\npython main.py\n```\n\nThe built-in health server listens on the PORT environment variable (8080 by default), so hosted health checks can use /health.\n

## LZT Market integration

The bot can fetch listings and complete purchases through the LZT Market API when LZT mode is enabled and a key is configured. Set `LZT_API_KEY` as a deployment secret, or enter it in **Admin Panel → LZT Settings**; never commit a real API key. The admin setting is checked first, with the environment variable used as a fallback.

Use `/lztmargin` to view the current fixed INR markup per automatically priced LZT item, or `/lztmargin 25` (also `/setlztmargin 25`) to set it. This command is admin-only; negative, infinite, and invalid values are rejected. Explicit/manual prices can still override automatic pricing.

---

## 🧩 New Feature Set (Settings, Servers, All Apps, More Content)

The bot now ships with the full feature set from the reference app:

### ⚙️ Settings (per-user currency & language)
- **Currency:** INR ₹ / USD $ / EUR € / GBP £
- **Language:** English / Hinglish / हिंदी / Русский / 中文 / العربية
- Preferences are stored per user in the `users` table (`currency`, `language` columns).

### 🖥 Servers
Configured via `SERVERS_CONFIG` (name|status|mode):
- `Server-1` — OFF by default
- `Server-2 (Good Quality TG)` — non-spam Telegram accounts
- `Server-3 (TG NUM change)` — TemporaSMS number-change flow
- `Server-4 (cheap phishing)` — cheapest bulk accounts

### 📱 All Apps Accounts (OTP) + Buy Wp Acc
Buy OTP numbers for Telegram, WhatsApp, Instagram, Facebook, Twitter/X, TikTok,
Google, Discord, Uber, Amazon, Netflix and PayPal. Prices/numbers are fetched
from your configured OTP provider (5SIM is the default engine).

### 📦 More Content
- **Read & Generate Sessions** — convert a Telethon `StringSession` into a
  downloadable `.session` file, or read an uploaded `.session`.
- **Redeem** — redeem gift codes (`/redeem CODE`) for instant balance.
- **Refer & Earn** — existing referral engine.
- **Get your own Bots** — external link.

### ✅ Good Quality & Cheap Rates
Every Telegram search result now shows a **“Good Quality and Cheap Rates”**
header, and the **Panels** store is sorted cheapest-first for users.

### 💎 Premium Emoji
All new menus use Telegram premium `<tg-emoji>` where available, with safe
text fallbacks when `USE_PREMIUM_EMOJIS=0`.

---

## 🔑 API Keys (set these in your host's Variables/Secrets)

| Variable | Purpose |
|---|---|
| `FIVESIM_API_KEY` | 5SIM OTP numbers (default engine) |
| `SMSACTIVATE_API_KEY` | SMS-Activate OTP numbers |
| `SMSPVA_API_KEY` | SMSPVA OTP numbers |
| `SMSMAN_API_KEY` | SMS-Man OTP numbers |
| `TEMPMAIL_API_KEY` | Temp-mail inbox API |
| `TEMPORASMS_API_KEY` | **TG Number Change** (TemporaSMS) |
| `TEMPORASMS_BASE_URL` | TemporaSMS base URL (default `https://api.temporasms.com`) |
| `IMAP_HOST` / `IMAP_PORT` / `IMAP_USER` / `IMAP_PASSWORD` | Auto-read Telegram login codes |
| `SERVERS_CONFIG` | Server list shown in the Servers screen |
| `DEFAULT_CURRENCY` / `DEFAULT_LANGUAGE` | Defaults for new users |

> The bot starts fine with these blank — the related feature simply reports that
> the provider is not configured. Add real keys in Railway → Variables,
> Render → Environment, or Heroku → Config Vars. Never commit real keys.
