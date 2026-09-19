# 🗣️ Ascoltino – Self-Hosted Telegram Voice Transcriber Bot

Ascoltino is a minimalist, self-hosted Telegram bot that listens to voice messages in any chat it's added to, transcribes the audio locally, and replies with the text. No cloud services—everything runs on your own hardware. Built using plain HTTP requests (no Telegram SDKs) and packaged with Docker.

Two engines are available, selected with `BOT_MODEL`:

- **`parakeet`** – [NVIDIA Parakeet-TDT 0.6B v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3) via [`onnx-asr`](https://github.com/istupakov/onnx-asr). 25 European languages, punctuation and capitalisation built in, and by far the fastest option on a CPU. Recommended.
- **Whisper sizes** (`tiny`, `base`, `small`, `medium`, `turbo`, `large-v3`, ...) via [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper).


## 🚀 Features

- ✅ Transcribes voice messages with Parakeet-TDT or `faster-whisper`
- ✅ Responds in the same chat with the transcription (live-updating for long notes)
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
BOT_MODEL=parakeet       # or a Whisper size: tiny, base, small, medium, turbo, large-v3
LANGUAGE=it              # Used by Whisper (Parakeet detects the language automatically)
THREADS=0                # 0 = all cores; use cores-1 if other services keep the CPU busy
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

A poller thread long-polls `getUpdates` and downloads voice notes as they arrive; a worker thread transcribes them one at a time, so the next note is already on disk while the current one is being processed. For each note:

1. The `.oga` (Opus) file is decoded in-process to 16 kHz mono (PyAV, no `ffmpeg` binary)
2. The audio array is transcribed by the selected engine
3. The text is sent back into the same chat. Fast results arrive as a single message; for longer notes a "Transcribing..." placeholder is posted after `PLACEHOLDER_DELAY` seconds and edited live as segments arrive (edits are throttled and never block the decoder)

Whisper is run with speed-oriented decoder settings for short clips (`without_timestamps`, no temperature fallback, `condition_on_previous_text=False`). Set `WHISPER_TIMESTAMPS=true` / `WHISPER_FALLBACK=true` to restore the stock behaviour.

## Benchmarking

`bench.py` runs every `samples/*.ogg` (Italian voice notes with reference transcripts in `samples/*.txt`) through the same code path as the bot and reports elapsed time, realtime factor and word error rate:

```bash
python3 bench.py --models parakeet,small,base --threads 0
python3 bench.py --models medium --threads 2,3,4
WHISPER_TIMESTAMPS=true WHISPER_FALLBACK=true python3 bench.py --models medium   # stock Whisper decoding
```

Measured on an Intel N100 (4 cores, shared with Frigate and other Home Assistant add-ons), 72.6 s of audio in 6 notes:

| Model | Total time | Realtime factor | WER |
|---|---|---|---|
| `medium`, stock decoding (Ascoltino ≤ 1.3) | 95.4 s | 1.31 | 9.4% |
| `medium`, tuned decoding | 84.6 s | 1.16 | 9.8% |
| `small`, tuned decoding | 48.8 s | 0.67 | 18.4% |
| `base`, tuned decoding | 17.7 s | 0.24 | 33.6% |
| `parakeet` int8, 2 threads | 19.9 s | 0.27 | 14.2% |

Parakeet is roughly 5x faster than the previous default on this box while being far more accurate than any Whisper size that is comparably fast. Set `PARAKEET_QUANTIZATION=` (empty) to use the fp32 weights: about 2x slower, ~2 GB more RAM, slightly better accuracy.

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
