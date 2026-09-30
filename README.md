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