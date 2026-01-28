import os
import time
import requests
import subprocess
from faster_whisper import WhisperModel

import logging

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_MODEL = os.getenv("BOT_MODEL", "base")
LANGUAGE = os.getenv("LANGUAGE")
BEAM_SIZE = int(os.getenv("BEAM_SIZE", "1"))
VAD_FILTER = os.getenv("VAD_FILTER", "false").lower() == "true"

LAST_UPDATE_FILE = "storage/.last_update"

logging.basicConfig(
    filename='logs/bot.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)

log = logging.getLogger(__name__)

# Load model once at startup
log.info(f"Loading Whisper model: {BOT_MODEL}")
model = WhisperModel(BOT_MODEL, device="cpu", compute_type="int8")
log.info("Model loaded!")


def convert_oga_to_wav(input_path, output_path):
    try:
        log.info(f"Converting {input_path} to WAV format")
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", input_path, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            log.error(f"FFmpeg error: {result.stderr}")
            return False
        return True
    except Exception as e:
        log.error(f"FFmpeg conversion failed: {e}")
        return False

def get_last_update_id():
    os.makedirs("storage", exist_ok=True)
    if not os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "w") as f:
            f.write("0")
    with open(LAST_UPDATE_FILE, "r") as f:
        return int(f.read().strip())



def set_last_update_id(update_id):
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(update_id))


def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        res = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
        return res.json()["result"]
    except Exception as e:
        log.info(f"Error getting updates: {e}")
        return []


def download_file(file_id):
    try:
        log.info("Downloading file")
        res = requests.get(f"{API_URL}/getFile", params={"file_id": file_id})
        file_path = res.json()["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        local_path = "storage/voice.oga"
        with requests.get(download_url, stream=True) as r:
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        log.info("File downloaded!")
        return local_path
    except Exception as e:
        log.error(f"Download failed: {e}")
        return None

def transcribe(file_path, on_segment=None):
    """
    Transcribe audio file. If on_segment callback is provided,
    it will be called with the accumulated text after each segment.
    """
    try:
        log.info("Transcribing file")
        segments, info = model.transcribe(
            file_path,
            language=LANGUAGE,
            beam_size=BEAM_SIZE,
            vad_filter=VAD_FILTER,
        )
        log.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")
        
        full_text = ""
        for segment in segments:
            log.info(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
            full_text += segment.text.strip() + " "
            
            # Call the callback with accumulated text if provided
            if on_segment:
                on_segment(full_text.strip())

        full_text = full_text.strip()
        
        if not full_text:
            log.warning("No transcription result found.")
            return None

        return full_text

    except Exception as e:
        log.error(f"Transcription failed: {e}")
        return None

def send_message(chat_id, text):
    try:
        log.info("Sending message")
        requests.post(f"{API_URL}/sendMessage", data={"chat_id": chat_id, "text": text, "disable_notification": True})
    except Exception as e:
        log.error(f"Failed to send message: {e}")


def send_message_and_get_id(chat_id, text):
    """Send message and return message_id for later editing."""
    try:
        res = requests.post(f"{API_URL}/sendMessage", data={
            "chat_id": chat_id,
            "text": text,
            "disable_notification": True
        })
        return res.json()["result"]["message_id"]
    except Exception as e:
        log.error(f"Failed to send message: {e}")
        return None


def edit_message(chat_id, message_id, text):
    """Edit an existing message."""
    try:
        requests.post(f"{API_URL}/editMessageText", data={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text
        })
    except Exception as e:
        log.warning(f"Failed to edit message: {e}")


def cleanup_temp_files(*file_paths):
    """Remove temporary files after processing."""
    for file_path in file_paths:
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
                log.info(f"Cleaned up temp file: {file_path}")
        except Exception as e:
            log.warning(f"Failed to clean up {file_path}: {e}")


def main():
    log.info("Bot started... again")
    last_update_id = get_last_update_id()

    while True:
        updates = get_updates(offset=last_update_id + 1 if last_update_id else None)

        for update in updates:
            try:
                update_id = update["update_id"]
                last_update_id = update_id
                set_last_update_id(update_id)

                message = update.get("message", {})
                chat_id = message["chat"]["id"]

                if "voice" in message:
                    log.info("Voice message received")
                    file_id = message["voice"]["file_id"]
                    voice_file = download_file(file_id)
                    wav_file = voice_file + ".wav" if voice_file else None
                    try:
                        if voice_file:
                            if convert_oga_to_wav(voice_file, wav_file):
                                # Send initial "transcribing" message
                                message_id = send_message_and_get_id(chat_id, "🎤 Transcribing...")
                                
                                # Track last edit time to avoid rate limits
                                last_edit_time = [0]  # Use list to allow mutation in closure
                                MIN_EDIT_INTERVAL = 0.5  # 500ms between edits
                                
                                def on_segment(partial_text):
                                    now = time.time()
                                    if now - last_edit_time[0] >= MIN_EDIT_INTERVAL:
                                        edit_message(chat_id, message_id, f"🗣️ {partial_text}...")
                                        last_edit_time[0] = now
                                
                                text = transcribe(wav_file, on_segment=on_segment)
                                
                                if text:
                                    # Final update without the trailing "..."
                                    edit_message(chat_id, message_id, f"🗣️ {text}")
                                else:
                                    log.info(chat_id, "❌ Could not transcribe audio.")
                                    edit_message(chat_id, message_id, "❌ Could not transcribe audio.")
                            else:
                                log.error("could not convert")
                    finally:
                        # Clean up temp files after processing
                        cleanup_temp_files(voice_file, wav_file)
                else:
                    log.info("Non-voice message, ignoring")

            except Exception as e:
                log.error(f"Error processing update: {e}")

        time.sleep(1)


if __name__ == "__main__":
    main()
