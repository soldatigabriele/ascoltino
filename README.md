# 🗣️ Ascoltino – Telegram Voice Transcriber Bot

Ascoltino is a minimalist Telegram bot that listens to voice messages in any chat it's added to, transcribes the audio using [`faster-whisper`](https://github.com/guillaumekln/faster-whisper), and replies with the text. Built using plain HTTP requests (no Telegram SDKs) and packaged with Docker.


## 🚀 Features

- ✅ Transcribes voice messages using `faster-whisper`
- ✅ Responds in the same chat with the transcription
- ✅ Uses Telegram Bot API directly (no dependencies like `python-telegram-bot`)
- ✅ Runs in a Docker container with persistent logs and model cache
- ✅ Can run on CPU (ARM/x86) with model caching
- ✅ Automatically converts `.oga` Telegram voice files using `ffmpeg`

---

## 🛠️ Requirements

- Docker
- Docker Compose

---

## ⚙️ Setup

### 1. Clone the repo

```bash
git clone https://github.com/your-username/ascoltino.git
cd ascoltino
```

### 2. Create a .env file
Create a file named .env in the root folder with the following content:

```
BOT_TOKEN=your_telegram_bot_token
BOT_MODEL=base           # Options: tiny, base, small, medium, large-v2, large-v3
LANGUAGE=it              # Optional but speeds up transcription if known
```


```
docker-compose build
docker-compose up

```

## How it works

The bot polls getUpdates to receive messages.
If a voice message is received, it:
Downloads the .oga file
Converts it to .wav using ffmpeg
Transcribes it with faster-whisper
Sends the text back into the same chat.

## View logs in real time:

```
tail -f logs/bot.log
```

## Troubleshooting

`exec format error`: Check that the image is built for the correct platform (e.g. ARM vs x86).

Bot doesn't respond: Ensure it’s added to the chat and has permission to read/send messages.

Transcription not working: Check if `ffmpeg` properly converts the `.oga` file.


## Build and deploy

```bash
docker build --platform linux/arm64 -t gab9119/ascoltino-bot .
docker build --platform linux/amd64 -t gab9119/ascoltino-bot .

docker tag gab9119/ascoltino-bot gab9119/ascoltino-bot:amd_v2
docker push gab9119/ascoltino-bot:amd_v2
```

## Find the chat_id

```bash
https://api.telegram.org/bot<token>/getUpdates
```

! Note: make sure you keep the `/bot` part in the url before the token!