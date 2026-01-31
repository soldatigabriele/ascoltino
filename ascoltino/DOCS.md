# Ascoltino - Telegram Voice Transcriber

Ascoltino is a Telegram bot that automatically transcribes voice messages using OpenAI's Whisper AI model.

## How it works

1. Add the bot to any Telegram chat (group or private)
2. When someone sends a voice message, the bot automatically transcribes it
3. The transcription is posted as a reply in the same chat

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Copy the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 2. Configure the Add-on

1. Paste your bot token in the **Bot Token** field
2. Set your preferred **Language** code (e.g., `en`, `it`, `de`, `es`)
3. Choose a **Whisper Model**:
   - `tiny` - Fastest, least accurate
   - `base` - Good balance (recommended)
   - `small` - Better accuracy, slower
   - `medium` - High accuracy, requires more RAM
   - `large-v2` / `large-v3` - Best accuracy, requires significant RAM

### 3. Add the Bot to Chats

1. Open your Telegram bot
2. Add it to any group chat, or message it directly
3. Make sure the bot has permission to read messages

## Configuration Options

| Option | Description |
|--------|-------------|
| **Bot Token** | Your Telegram bot token from @BotFather |
| **Model** | Whisper model size (tiny/base/small/medium/large) |
| **Language** | Two-letter language code for transcription |
| **Beam Size** | Search beam size (1-10). Higher may improve accuracy |
| **VAD Filter** | Voice Activity Detection to skip silence |
| **Threads** | CPU threads for transcription (0 = auto) |
| **Bot Name** | Optional name shown in transcription footer |
| **Admin Chat ID** | Optional chat ID for startup notifications |

## Performance Tips

- **For Raspberry Pi 4**: Use `tiny` or `base` model with 2-4 threads
- **For more powerful hardware**: Try `small` or `medium` models
- **VAD Filter**: Enable to speed up transcription of messages with pauses

## Logs

View the add-on logs to see transcription activity and troubleshoot issues.

## Support

For issues and feature requests, visit:
https://github.com/gab9119/ascoltino/issues
