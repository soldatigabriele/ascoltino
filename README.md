# 🗣️ Ascoltino – Self-Hosted Telegram Voice Transcriber Bot

Ascoltino is a minimalist, self-hosted Telegram bot that listens to voice messages in any chat it's added to, transcribes the audio locally using [`faster-whisper`](https://github.com/guillaumekln/faster-whisper) (up to 4x faster than OpenAI's Whisper), and replies with the text. No cloud services—everything runs on your own hardware. Built using plain HTTP requests (no Telegram SDKs) and packaged with Docker.


## 🚀 Features

- ✅ Transcribes voice messages using `faster-whisper`
- ✅ Responds in the same chat with the transcription
- ✅ Uses Telegram Bot API directly (no dependencies like `python-telegram-bot`)
- ✅ Runs in a Docker container with persistent logs and model cache
- ✅ Can run on CPU (ARM/x86) with model caching
- ✅ Available as a Home Assistant add-on

---

## 🏠 Home Assistant Add-on

Ascoltino is also available as a **self-hosted Home Assistant add-on** for easy installation and management directly from your Home Assistant instance. All transcription happens locally on your hardware—no cloud services required.

---

## 🛠️ Requirements

- Docker
- Docker Compose

---

## ⚙️ Setup

### 1. Clone the repo

```bash
git clone https://github.com/soldatigabriele/ascoltino.git
cd ascoltino
```

### 2. Create a .env file
Create a file named .env in the root folder with the following content:

```
BOT_TOKEN=your_telegram_bot_token
BOT_MODEL=base           # Options: tiny, base, small, medium
LANGUAGE=it              # Optional but speeds up transcription if known
ALLOWED_CHAT_IDS=-1001234567890,123456789  # Strongly recommended, see below
```

### Restricting who can use the bot

Anyone who finds your bot's username on Telegram can send it voice messages, and your machine will transcribe them. Set `ALLOWED_CHAT_IDS` to a comma-separated list of chat IDs (groups are negative numbers) to only serve those chats. Messages from other chats are ignored and logged with the chat/user details; if `ADMIN_CHAT_ID` is set you also get notified once per unknown chat. See [Setup Telegram Bot](#setup-telegram-bot) for how to find a chat ID.

### 3. Build and run

```bash
docker-compose build
docker-compose up
```

---

## How it works

The bot polls `getUpdates` to receive messages. When a voice message is received, it:

1. Downloads the `.oga` file
2. Converts it to `.wav` using `ffmpeg`
3. Transcribes it with `faster-whisper`
4. Sends the text back into the same chat

## View logs in real time:

```
tail -f logs/bot.log
```

## Troubleshooting

Bot doesn't respond: Ensure it’s added to the chat and has permission to read/send messages.

## Setup Telegram Bot

Create a Telegram Bot with BotFather and grab the token, then invite the bot in your chat with admin privileges (necessary to read, write and edit messages).
To find a chat_id (needed for `ALLOWED_CHAT_IDS`), either:

- Open the chat in [web.telegram.org](https://web.telegram.org) and read the number after `#` in the URL (e.g. `#-1001234567890`), or
- Stop the bot, send a message in the chat, then open:

```bash
https://api.telegram.org/bot<TOKEN>/getUpdates
```

! Note: make sure you keep the `/bot` part in the url before the token, and the `-` before the chat_id!
