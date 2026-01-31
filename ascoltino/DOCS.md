# Ascoltino - Telegram Voice Transcriber

Ascoltino is a Telegram bot that automatically transcribes voice messages using OpenAI's Whisper AI model.

## How it works

1. Add the bot to any Telegram chat (group or private)
2. When someone sends a voice message, the bot automatically transcribes it
3. The transcription is posted as a reply in the same chat

## Setup

### 1. Create a Telegram Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts to create your bot
3. Give your bot a name (e.g., "My Voice Transcriber")
4. Give your bot a username (must end in `bot`, e.g., `my_voice_transcriber_bot`)
5. Copy the bot token - it looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

**Important:** Keep your bot token secret! Anyone with the token can control your bot.

### 2. Configure the Add-on

1. Paste your bot token in the **Bot Token** field
2. Set your preferred **Language** code (e.g., `en`, `it`, `de`, `es`, `fr`)
3. Choose a **Whisper Model**:
   - `tiny` - Fastest, least accurate
   - `base` - Good balance (recommended for most users)
   - `small` - Better accuracy, slower
   - `medium` - High accuracy, requires more RAM
   - `turbo` - Fast and accurate (good for powerful hardware)
   - `large-v2` / `large-v3` - Best accuracy, requires significant RAM

### 3. Add the Bot to Chats

1. Open Telegram and find your bot by its username
2. Start a chat with the bot, or add it to a group chat
3. In group chats, make sure the bot has permission to read messages

**For group chats:** You may need to disable privacy mode. Send `/setprivacy` to @BotFather, select your bot, and choose "Disable".

## Configuration Options

| Option | Description |
|--------|-------------|
| **Bot Token** | Your Telegram bot token from @BotFather (required) |
| **Model** | Whisper model size - larger is more accurate but slower |
| **Language** | Two-letter language code (e.g., `en`, `it`, `de`) |
| **Beam Size** | Search beam size (1-10). Higher may improve accuracy slightly |
| **VAD Filter** | Voice Activity Detection - skips silence for faster processing |
| **Threads** | CPU threads for transcription (0 = auto-detect) |
| **Show Footer** | Show transcription stats (time, model, speed) in messages |
| **Bot Name** | Optional name shown in the transcription footer |
| **Admin Chat ID** | Optional chat ID to receive startup notifications |

## Finding Your Chat ID

If you want to receive startup notifications, you'll need your chat ID:

1. Send a message to your bot (or in the group where the bot is)
2. Open this URL in your browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":` in the response - the number after it is your chat ID
4. For private chats, it's a positive number. For groups, it's negative (e.g., `-1001234567890`)

**Note:** Make sure to keep the `/bot` part before your token in the URL!

## Performance Tips

- **For Raspberry Pi 4**: Use `tiny` or `base` model with 2-4 threads
- **For more powerful hardware**: Try `small`, `medium`, or `turbo` models
- **VAD Filter**: Enable to speed up transcription of messages with pauses
- **Beam Size**: Keep at 1 for speed, increase to 3-5 for slightly better accuracy

## Troubleshooting

**Bot doesn't respond:**
- Ensure the bot is added to the chat
- Check that it has permission to read messages
- In groups, try disabling privacy mode via @BotFather

**Transcription is slow:**
- Try a smaller model (`tiny` or `base`)
- Reduce the number of threads if on limited hardware
- Enable VAD filter to skip silence

**Model download takes long:**
- First run downloads the Whisper model (can take several minutes)
- The model is cached for subsequent runs

## Logs

View the add-on logs to see transcription activity and troubleshoot issues. The logs show:
- Voice messages received
- Transcription time and speed
- Any errors that occur

## Support

For issues and feature requests, visit:
https://github.com/soldatigabriele/ascoltino/issues
