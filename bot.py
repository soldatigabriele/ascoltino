import os
import time
import requests
import subprocess
from itertools import product
from faster_whisper import WhisperModel

import logging

VERSION = "1.1.0"

# Detect Home Assistant add-on environment
HA_ADDON = os.getenv("HA_ADDON", "").lower() == "true"

# Set paths based on environment
if HA_ADDON:
    DATA_DIR = "/data"
    LOG_DIR = "/data/logs"
    LOG_FILE = "/data/logs/bot.log"
    # Set Whisper model cache location for HA
    os.environ["HF_HOME"] = "/data/.cache"
else:
    DATA_DIR = "storage"
    LOG_DIR = "logs"
    LOG_FILE = "logs/bot.log"

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
BOT_NAME = os.getenv("BOT_NAME", "")
LANGUAGE = os.getenv("LANGUAGE")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Optional: send startup message to this chat

# Parse comma-separated config values for multi-config mode
def parse_models(val):
    return [m.strip() for m in val.split(",") if m.strip()]

def parse_ints(val):
    return [int(x.strip()) for x in val.split(",") if x.strip()]

def parse_bools(val):
    return [x.strip().lower() == "true" for x in val.split(",") if x.strip()]

BOT_MODELS = parse_models(os.getenv("BOT_MODEL", "base"))
BEAM_SIZES = parse_ints(os.getenv("BEAM_SIZE", "1"))
VAD_FILTERS = parse_bools(os.getenv("VAD_FILTER", "false"))
THREADS_LIST = parse_ints(os.getenv("THREADS", "4"))

# For backward compatibility, expose single values (first in list)
BOT_MODEL = BOT_MODELS[0]
BEAM_SIZE = BEAM_SIZES[0]
VAD_FILTER = VAD_FILTERS[0]
THREADS = THREADS_LIST[0]

# Check if we're in multi-config mode (more than one combination)
CONFIGS = list(product(BOT_MODELS, BEAM_SIZES, VAD_FILTERS, THREADS_LIST))
MULTI_CONFIG_MODE = len(CONFIGS) > 1

LAST_UPDATE_FILE = os.path.join(DATA_DIR, ".last_update")
VOICE_FILE_PATH = os.path.join(DATA_DIR, "voice.oga")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
)

log = logging.getLogger(__name__)

# Startup banner (prints to stdout for container logs)
print(f"Ascoltino v{VERSION}")
if HA_ADDON:
    print(f"  Mode: Home Assistant Add-on")
if MULTI_CONFIG_MODE:
    print(f"  Multi-config mode: {len(CONFIGS)} combinations")
    print(f"  Models: {BOT_MODELS} | Beams: {BEAM_SIZES} | VADs: {VAD_FILTERS} | Threads: {THREADS_LIST}")
else:
    print(f"  Model: {BOT_MODEL} | Beam: {BEAM_SIZE} | VAD: {VAD_FILTER} | Threads: {THREADS}")
if BOT_NAME:
    print(f"  Name: {BOT_NAME}")

# Load models at startup - cache all unique models
log.info(f"Ascoltino v{VERSION} starting")
if MULTI_CONFIG_MODE:
    log.info(f"Multi-config mode: {len(CONFIGS)} combinations")
    log.info(f"Models: {BOT_MODELS}, Beams: {BEAM_SIZES}, VADs: {VAD_FILTERS}, Threads: {THREADS_LIST}")
else:
    log.info(f"Config: model={BOT_MODEL}, beam={BEAM_SIZE}, vad={VAD_FILTER}, threads={THREADS}, name={BOT_NAME or '(not set)'}")

# Load all unique models (keyed by model name and threads since threads affects model loading)
models = {}
for model_name in BOT_MODELS:
    for threads in THREADS_LIST:
        key = (model_name, threads)
        if key not in models:
            log.info(f"Loading Whisper model: {model_name} (threads={threads})")
            print(f"  Loading model {model_name} (threads={threads})...")
            models[key] = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
            log.info(f"Model {model_name} loaded!")

# For backward compatibility
model = models[(BOT_MODEL, THREADS)]
print(f"  ✅ Ready!")


def send_startup_message():
    """Send startup notification to admin chat if configured."""
    if not ADMIN_CHAT_ID:
        return
    try:
        footer = format_config_footer()
        text = f"✅ Ascoltino is ready!{footer}"
        requests.post(f"{API_URL}/sendMessage", data={
            "chat_id": ADMIN_CHAT_ID,
            "text": text,
            "disable_notification": True
        }, timeout=10)
        log.info(f"Startup message sent to chat {ADMIN_CHAT_ID}")
    except Exception as e:
        log.warning(f"Failed to send startup message: {e}")

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
        local_path = VOICE_FILE_PATH
        with requests.get(download_url, stream=True) as r:
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        log.info("File downloaded!")
        return local_path
    except Exception as e:
        log.error(f"Download failed: {e}")
        return None

def transcribe(file_path, on_segment=None, model_name=None, beam_size=None, vad_filter=None, threads=None):
    """
    Transcribe audio file. If on_segment callback is provided,
    it will be called with the accumulated text after each segment.
    
    Config parameters default to the primary config if not specified.
    
    Returns a dict with 'text', 'duration', 'elapsed', and config info on success, or None on failure.
    """
    # Use defaults if not specified
    model_name = model_name if model_name is not None else BOT_MODEL
    beam_size = beam_size if beam_size is not None else BEAM_SIZE
    vad_filter = vad_filter if vad_filter is not None else VAD_FILTER
    threads = threads if threads is not None else THREADS
    
    try:
        log.info(f"Transcribing file (model={model_name}, beam={beam_size}, vad={vad_filter}, threads={threads})")
        start_time = time.time()
        
        # Get the appropriate model
        current_model = models[(model_name, threads)]
        
        segments, info = current_model.transcribe(
            file_path,
            language=LANGUAGE,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )
        log.info(f"Detected language '{info.language}' with probability {info.language_probability:.2f}")
        
        full_text = ""
        for segment in segments:
            log.info(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
            full_text += segment.text.strip() + " "
            
            # Call the callback with accumulated text if provided
            if on_segment:
                on_segment(full_text.strip())

        elapsed = time.time() - start_time
        full_text = full_text.strip()
        
        if not full_text:
            log.warning("No transcription result found.")
            return None

        return {
            "text": full_text,
            "duration": info.duration,
            "elapsed": elapsed,
            "model": model_name,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "threads": threads,
        }

    except Exception as e:
        log.error(f"Transcription failed: {e}")
        return None

def format_config_footer():
    """Format a config footer with bot info (no timing)."""
    parts = [
        f"model={BOT_MODEL}",
        f"beam={BEAM_SIZE}",
        f"vad={'on' if VAD_FILTER else 'off'}",
        f"threads={THREADS}",
        f"v{VERSION}",
    ]
    if BOT_NAME:
        parts.insert(0, BOT_NAME)
    return "\n\n---\n" + " | ".join(parts)


def format_stats_footer(duration, elapsed, model_name=None, beam_size=None, vad_filter=None, threads=None):
    """Format a stats footer with transcription info."""
    # Use defaults if not specified
    model_name = model_name if model_name is not None else BOT_MODEL
    beam_size = beam_size if beam_size is not None else BEAM_SIZE
    vad_filter = vad_filter if vad_filter is not None else VAD_FILTER
    threads = threads if threads is not None else THREADS
    
    speed = duration / elapsed if elapsed > 0 else 0
    parts = [
        f"⏱ {elapsed:.1f}s ({speed:.1f}x)",
        f"model={model_name}",
        f"beam={beam_size}",
        f"vad={'on' if vad_filter else 'off'}",
        f"threads={threads}",
        f"v{VERSION}",
    ]
    if BOT_NAME:
        parts.insert(0, BOT_NAME)
    return "\n\n---\n" + " | ".join(parts)


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
    log.info("Bot started")
    send_startup_message()
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
                                if MULTI_CONFIG_MODE:
                                    # Multi-config mode: process with all configurations
                                    log.info(f"Multi-config mode: processing {len(CONFIGS)} configurations")
                                    send_message(chat_id, f"🎤 Processing with {len(CONFIGS)} configurations...")
                                    
                                    for idx, (model_name, beam_size, vad_filter, threads) in enumerate(CONFIGS, 1):
                                        config_label = f"[{idx}/{len(CONFIGS)}] model={model_name}, beam={beam_size}, vad={'on' if vad_filter else 'off'}, threads={threads}"
                                        log.info(f"Processing config: {config_label}")
                                        
                                        result = transcribe(
                                            wav_file,
                                            model_name=model_name,
                                            beam_size=beam_size,
                                            vad_filter=vad_filter,
                                            threads=threads
                                        )
                                        
                                        if result:
                                            stats = format_stats_footer(
                                                result["duration"], result["elapsed"],
                                                model_name=model_name, beam_size=beam_size,
                                                vad_filter=vad_filter, threads=threads
                                            )
                                            send_message(chat_id, f"🗣️ {result['text']}{stats}")
                                        else:
                                            send_message(chat_id, f"❌ Failed: {config_label}")
                                else:
                                    # Single config mode: streaming with edits
                                    message_id = send_message_and_get_id(chat_id, "🎤 Transcribing...")
                                    
                                    # Track last edit time to avoid rate limits
                                    last_edit_time = [0]  # Use list to allow mutation in closure
                                    MIN_EDIT_INTERVAL = 0.5  # 500ms between edits
                                    
                                    def on_segment(partial_text):
                                        now = time.time()
                                        if now - last_edit_time[0] >= MIN_EDIT_INTERVAL:
                                            edit_message(chat_id, message_id, f"🗣️ {partial_text}...")
                                            last_edit_time[0] = now
                                    
                                    result = transcribe(wav_file, on_segment=on_segment)
                                    
                                    if result:
                                        # Final update with stats footer
                                        stats = format_stats_footer(result["duration"], result["elapsed"])
                                        edit_message(chat_id, message_id, f"🗣️ {result['text']}{stats}")
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
