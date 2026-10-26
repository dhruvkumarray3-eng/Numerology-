<div align="center">

# 🎧 VIBE MUSIC BOT 🎧

<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=24&pause=1000&color=00F0FF&center=true&vCenter=true&width=520&lines=Telegram+Music+%26+Voice+Chat+Player;YouTube+%7C+Spotify+%7C+SoundCloud;Queue+System+%2B+Live+Streaming" alt="Typing SVG" />
</p>

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Telethon](https://img.shields.io/badge/Telethon-1.44-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://docs.telethon.dev)
[![License](https://img.shields.io/badge/License-MIT-red?style=for-the-badge)](LICENSE)

</div>

---

## 🌟 What is this?

A lightweight, self-hosted Telegram music bot that streams audio straight into your group
**Voice Chat**. Drop a link, and the bot joins the VC, plays the track, and keeps a clean
queue for everyone in the group. Built for small friend groups, fan communities and late-night
listening sessions.

No ads, no watermarks, no forced subscriptions — just music.

---

## ✨ Features

* 🎵 **Play from anywhere** — YouTube, YouTube Music, SoundCloud and direct audio links.
* 🔊 **Voice Chat streaming** — the bot joins the VC and plays in real time.
* 📜 **Smart queue** — add, skip, pause, resume, loop and shuffle without leaving chat.
* ⏱ **Live now-playing card** — track title, duration, requester and progress bar.
* 🔁 **Auto-leave** — the bot leaves the VC automatically when the queue is empty.
* 👥 **Multi-group support** — one instance can serve several groups at once.
* 🛡 **Admin controls** — restrict who can add tracks, clear the queue, or stop playback.
* 🎨 **Clean inline UI** — colour-coded buttons, thumbnails and tidy captions.
* ⚡ **Async everywhere** — built on Telethon + PyTgCalls, so it stays snappy under load.

---

## 🕹 Commands

| Command | What it does |
| --- | --- |
| `/start` | Wake the bot up and show the mini player card |
| `/play <song or link>` | Search and queue a track |
| `/pause` | Pause the current track |
| `/resume` | Resume playback |
| `/skip` | Skip to the next track in queue |
| `/queue` | Show the current queue |
| `/loop` | Toggle loop mode |
| `/shuffle` | Shuffle the queue |
| `/stop` | Stop playback and clear the queue |
| `/leave` | Disconnect from the voice chat |
| `/help` | Show the short command card |

---

## 🛠 Tech Stack

* **Python 3.10+**
* **Telethon** — Telegram client framework
* **PyTgCalls / pytgcalls** — voice chat streaming engine
* **yt-dlp** — media extraction
* **FFmpeg** — audio transcoding
* **SQLite** — lightweight local storage for queues and preferences

---

## 🚀 Quick Start

### 1. Clone

```bash
git clone https://github.com/dhruvkumarray3-eng/Numerology-.git
cd Numerology-
```

### 2. Virtual environment

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

FFmpeg is required on the host:

```bash
sudo apt update && sudo apt install -y ffmpeg
```

### 4. Configure

Copy `.env.sample` to `.env` and fill in your own values:

```env
API_ID=your_api_id
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_user_id
```

Get `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org) and the
`BOT_TOKEN` from [@BotFather](https://t.me/BotFather).

### 5. Run

```bash
python main.py
```

The bot logs in, prints a ready message, and starts listening for commands.

---

## ☁️ Deploying

The project ships with ready-made configs for the usual suspects:

* **Railway** — `railway.json`
* **Render** — `render.yaml`
* **Heroku** — `Procfile` + `app.json`
* **Docker** — `Dockerfile`

Just connect the repo, paste the environment variables into the dashboard, and deploy.
A small health endpoint is exposed on `$PORT` so platforms can verify the process is alive.

---

## 📁 Project Layout

```
.
├── main.py              # entry point
├── config.py            # environment + settings loader
├── database.py          # SQLite helpers
├── plugins/             # command handlers (play, queue, admin, ...)
├── utils/               # keyboards, states, streaming helpers
├── assets/              # banners and static media
└── requirements.txt
```

---

## 🤝 Contributing

Pull requests are welcome. For larger changes, open an issue first so we can talk about
the direction. Keep the code async, keep the UI tidy, and test in a real group before
submitting.

---

## 📄 License

Released under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">

**Made for people who just want to listen to music together.** 🎶

</div>
