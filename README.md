# Vibe Music Bot 🎵

A simple Telegram music player bot built with Pyrogram and PyTgCalls. It can play
songs in a group voice chat, queue tracks, and stream from YouTube.

> This project is a hobby music bot. It is still under development and some
> commands may not work perfectly yet.

---

## Features

- Play music in Telegram voice chats
- Queue system (add, skip, pause, resume, stop)
- Search songs by name
- Simple and lightweight
- Works in groups and channels

---

## Requirements

- Python 3.9+
- Telegram API ID and API Hash
- A bot token from BotFather
- FFmpeg installed on the server
- A Telegram account string session (for the assistant)

---

## Installation

```bash
git clone https://github.com/dhruvkumarray3-eng/Numerology-.git
cd Numerology-
pip install -r requirements.txt
```

Create a `.env` file:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=your_bot_token
SESSION_STRING=your_pyrogram_session
```

Run the bot:

```bash
python main.py
```

---

## Commands

| Command | Description |
| --- | --- |
| `/start` | Start the bot |
| `/play <song>` | Play a song in voice chat |
| `/pause` | Pause the current song |
| `/resume` | Resume playback |
| `/skip` | Skip to the next song |
| `/stop` | Stop and leave voice chat |
| `/queue` | Show the current queue |

---

## Notes

- The bot must be an admin in the group to join voice chat.
- FFmpeg must be available in `PATH`.
- Large files may take a while to buffer.

---

## Disclaimer

This bot is provided for learning purposes. Please respect copyright and the
terms of service of any platform you use it with.

---

## License

MIT
