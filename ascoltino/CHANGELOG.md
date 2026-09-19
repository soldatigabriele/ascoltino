# Changelog

## 1.4.1

- Exclude the model cache from backups: snapshots were carrying several GB of downloaded models that are re-fetched automatically when missing

## 1.4.0

- New `parakeet` model (NVIDIA Parakeet-TDT 0.6B v3 via onnx-asr): several times faster than Whisper on CPU, 25 European languages, punctuation included. Now the default for new installs
- Whisper decoding tuned for short voice notes: no temperature fallback, no timestamps, independent windows. Removes the 10-20 s floor seen on short clips with `medium`. `WHISPER_TIMESTAMPS` / `WHISPER_FALLBACK` restore the old behaviour
- Audio is decoded in-process (PyAV) instead of spawning ffmpeg and decoding twice
- Telegram calls use a keep-alive session and run on a separate thread; live edits are coalesced and never stall the decoder
- Voice notes are downloaded by a poller thread while the previous note is being transcribed; per-note temp files
- Fast results are posted as a single message; the "Transcribing..." placeholder only appears when a note takes longer than `PLACEHOLDER_DELAY` (1 s)
- `threads: 0` now means all cores
- Added `bench.py` (speed and word error rate over `samples/`) and pinned dependencies

## 1.3.0

- Added "Allowed Chat IDs" option to restrict which chats can use the bot
- Voice messages from other chats are ignored, logged, and reported once to the admin chat
- Logs now include chat and user details for every voice message
- Non-message updates (edits, joins, channel posts) no longer log as errors

## 1.2.1

- Documentation cleanup

## 1.2.0

- Added "turbo" model option
- Added toggle to show/hide stats footer in messages

## 1.1.0

- Initial Home Assistant add-on release
- Whisper-based voice message transcription
- Configurable model size and language
- Streaming transcription with live updates
- Optional startup notifications
