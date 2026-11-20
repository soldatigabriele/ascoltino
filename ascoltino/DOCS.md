# Ascoltino - Telegram Voice Transcriber

Ascoltino is a Telegram bot that automatically transcribes voice messages locally, using NVIDIA's Parakeet-TDT model or OpenAI's Whisper.

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
2. Set your preferred **Language** code (e.g., `en`, `it`, `de`, `es`, `fr`). Whisper uses it and a Wyoming server receives it; Parakeet detects the language automatically
3. Choose a **Model**:
   - `parakeet` - NVIDIA Parakeet-TDT 0.6B v3 (recommended). 25 European languages, punctuation included, several times faster than Whisper on a CPU with accuracy between Whisper `small` and `medium`. Needs ~1.5 GB RAM
   - `tiny` / `base` - Whisper, fastest but inaccurate for non-English speech
   - `small` - Whisper, acceptable accuracy, slower than Parakeet
   - `medium` - Whisper, high accuracy but slow on small CPUs (10+ s per note on an Intel N100)
   - `turbo` / `large-v2` / `large-v3` - Whisper, best accuracy, needs a fast CPU or GPU
   - `wyoming` - no model of its own: uses a speech-to-text add-on you already run, see [below](#using-a-speech-to-text-add-on-you-already-run)

### 3. Add the Bot to Chats

1. Open Telegram and find your bot by its username
2. Start a chat with the bot, or add it to a group chat
3. In group chats, make sure the bot has permission to read messages

**For group chats:** You may need to disable privacy mode. Send `/setprivacy` to @BotFather, select your bot, and choose "Disable".

## Configuration Options

| Option | Description |
|--------|-------------|
| **Bot Token** | Your Telegram bot token from @BotFather (required) |
| **Model** | `parakeet`, a Whisper size or `wyoming` - see above |
| **Language** | Two-letter language code (e.g., `en`, `it`, `de`); used by Whisper and sent to a Wyoming server |
| **Beam Size** | Whisper search beam size (1-10). Higher may improve accuracy slightly; ignored by Parakeet |
| **VAD Filter** | Voice Activity Detection - skips silence; Parakeet uses it automatically for notes over 30 s |
| **Threads** | CPU threads for transcription (0 = all cores) |
| **Show Footer** | Show transcription stats (time, model, speed) in messages |
| **Bot Name** | Optional name shown in the transcription footer |
| **Admin Chat ID** | Optional chat ID to receive startup notifications |
| **Allowed Chat IDs** | Comma-separated chat IDs allowed to use the bot. Strongly recommended: without it, anyone who finds your bot can send it voice messages and use your CPU |
| **Wyoming Server URI** | Only for model `wyoming`: address of the speech-to-text add-on, e.g. `tcp://core-whisper:10300` |

When **Allowed Chat IDs** is set, voice messages from other chats are ignored and logged. If **Admin Chat ID** is also set, you get a one-time notification per unknown chat.

## Using a speech-to-text add-on you already run

If Home Assistant voice already keeps a speech-to-text add-on running (Whisper, ONNX ASR with Parakeet, ...), Ascoltino can send voice notes to it over the Wyoming protocol instead of loading a second model. Ascoltino then downloads no model and needs very little memory.

1. Set **Model** to `wyoming`
2. Set **Wyoming Server URI** to `tcp://<hostname>:<port>`. The hostname is shown on the other add-on's **Info** page; the port is the one it listens on inside Home Assistant, which does not need to be exposed under **Network**:
   - Official Whisper add-on: `tcp://core-whisper:10300`
   - ONNX ASR add-on: `tcp://<hostname ending in -onnx-asr>:10301`
3. Restart Ascoltino. The log shows the server and the models it offers

This mode is best-effort, because the other add-on does the work:

- **Speed and accuracy are that add-on's.** Model, quantization and threads are configured there; **Beam Size** and **Threads** here are ignored
- **Language matters.** The **Language** code is sent with every note and some add-ons choose the model by it. ONNX ASR uses its English model for `en` and its multilingual model for everything else, and falls back to the English model when no multilingual model is enabled. Ascoltino logs a warning at startup when the server does not list your language
- **It is shared with your voice assistant.** These servers handle one request at a time, so a voice command waits while a note is being transcribed. Notes over 30 s are sent in pieces of at most 30 s, cut at pauses, which keeps that wait short
- If the other add-on is stopped, notes get "Could not transcribe audio" until it is back; the reason is in the log

## Finding Your Chat ID

You'll need chat IDs for **Allowed Chat IDs** and (optionally) **Admin Chat ID**:

1. Send a message to your bot (or in the group where the bot is)
2. Open this URL in your browser (replace `<TOKEN>` with your bot token):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. Look for `"chat":{"id":` in the response - the number after it is your chat ID
4. For private chats, it's a positive number. For groups, it's negative (e.g., `-1001234567890`)

**Note:** Make sure to keep the `/bot` part before your token in the URL!

## Performance Tips

- **Start with `parakeet`**: on an Intel N100 it transcribes a 5 s note in about 2 s and a 30 s note in about 6 s, where Whisper `medium` needs 12-20 s for either
- **Threads**: `0` uses every core. If other add-ons (Frigate, other speech add-ons) keep the CPU busy, setting threads to one or two less than your core count is usually faster, not slower
- **Whisper on small CPUs**: prefer `small` over `medium`; `medium` costs a fixed ~12 s per note on an N100 regardless of how short the note is
- **Beam Size**: Keep at 1 for speed, increase to 3-5 for slightly better Whisper accuracy
- **VAD Filter**: Only useful for Whisper on notes with long pauses

## Troubleshooting

**Bot doesn't respond:**
- Ensure the bot is added to the chat
- Check that it has permission to read messages
- In groups, try disabling privacy mode via @BotFather

**Transcription is slow:**
- Switch to `parakeet`
- Reduce the number of threads if other add-ons are using the CPU
- With Whisper, try a smaller model (`small` or `base`)

**Model download takes long:**
- First run downloads the model (~640 MB for Parakeet, can take several minutes)
- The model is cached in the add-on data directory for subsequent runs

## Logs

View the add-on logs to see transcription activity and troubleshoot issues. The logs show:
- Voice messages received
- Transcription time and speed
- Any errors that occur

## Support

For issues and feature requests, visit:
https://github.com/soldatigabriele/ascoltino/issues
