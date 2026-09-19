import os
import queue
import threading
import time
from itertools import product

import requests

import logging

VERSION = "1.4.0"

# Detect Home Assistant add-on environment
HA_ADDON = os.getenv("HA_ADDON", "").lower() == "true"

# Set paths based on environment
if HA_ADDON:
    DATA_DIR = "/data"
    LOG_DIR = "/data/logs"
    LOG_FILE = "/data/logs/bot.log"
    # Model cache location for HA (faster-whisper and onnx-asr both use the HF cache)
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
FILE_URL = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
BOT_NAME = os.getenv("BOT_NAME", "")
LANGUAGE = os.getenv("LANGUAGE") or None
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Optional: send startup message to this chat
SHOW_FOOTER = os.getenv("SHOW_FOOTER", "true").lower() == "true"
# Wait this long before posting the "Transcribing..." placeholder; fast transcriptions
# (Parakeet, short notes) then arrive as a single message instead of placeholder + edit.
PLACEHOLDER_DELAY = float(os.getenv("PLACEHOLDER_DELAY", "1.0"))
MIN_EDIT_INTERVAL = 0.5  # seconds between live edits of the same message (Telegram rate limits)

# Parse comma-separated config values for multi-config mode
def parse_models(val):
    return [m.strip() for m in val.split(",") if m.strip()]

def parse_ints(val):
    return [int(x.strip()) for x in val.split(",") if x.strip()]

def parse_bools(val):
    return [x.strip().lower() == "true" for x in val.split(",") if x.strip()]

# Chats allowed to use the bot. Empty means open to everyone (not recommended).
ALLOWED_CHAT_IDS = set(parse_ints(os.getenv("ALLOWED_CHAT_IDS", "")))

BOT_MODELS = parse_models(os.getenv("BOT_MODEL", "base"))
BEAM_SIZES = parse_ints(os.getenv("BEAM_SIZE", "1"))
VAD_FILTERS = parse_bools(os.getenv("VAD_FILTER", "false"))
THREADS_LIST = parse_ints(os.getenv("THREADS", "0"))  # 0 = all cores

# For backward compatibility, expose single values (first in list)
BOT_MODEL = BOT_MODELS[0]
BEAM_SIZE = BEAM_SIZES[0]
VAD_FILTER = VAD_FILTERS[0]
THREADS = THREADS_LIST[0]

# Check if we're in multi-config mode (more than one combination)
CONFIGS = list(product(BOT_MODELS, BEAM_SIZES, VAD_FILTERS, THREADS_LIST))
MULTI_CONFIG_MODE = len(CONFIGS) > 1

LAST_UPDATE_FILE = os.path.join(DATA_DIR, ".last_update")

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
    print(f"  Model: {BOT_MODEL} | Beam: {BEAM_SIZE} | VAD: {VAD_FILTER} | Threads: {THREADS or 'all cores'}")
if BOT_NAME:
    print(f"  Name: {BOT_NAME}")
if ALLOWED_CHAT_IDS:
    print(f"  Allowed chats: {sorted(ALLOWED_CHAT_IDS)}")
else:
    print("  ⚠️  ALLOWED_CHAT_IDS not set: the bot will answer anyone who messages it")

log.info(f"Ascoltino v{VERSION} starting")
if ALLOWED_CHAT_IDS:
    log.info(f"Allowed chats: {sorted(ALLOWED_CHAT_IDS)}")
else:
    log.warning("ALLOWED_CHAT_IDS not set: the bot will answer anyone who messages it")
if MULTI_CONFIG_MODE:
    log.info(f"Multi-config mode: {len(CONFIGS)} combinations")
    log.info(f"Models: {BOT_MODELS}, Beams: {BEAM_SIZES}, VADs: {VAD_FILTERS}, Threads: {THREADS_LIST}")
else:
    log.info(f"Config: model={BOT_MODEL}, beam={BEAM_SIZE}, vad={VAD_FILTER}, threads={THREADS}, name={BOT_NAME or '(not set)'}")

# Imported after HF_HOME is set so the model cache lands in the persistent data dir.
from engines import create_engine, decode_audio  # noqa: E402

# Load all unique engines (keyed by model name and threads since threads affects loading)
engines = {}
for model_name in BOT_MODELS:
    for threads in THREADS_LIST:
        key = (model_name, threads)
        if key not in engines:
            log.info(f"Loading model: {model_name} (threads={threads})")
            print(f"  Loading model {model_name} (threads={threads})...")
            t0 = time.time()
            engines[key] = create_engine(model_name, threads, LANGUAGE)
            log.info(f"Model {model_name} loaded in {time.time() - t0:.1f}s")

engine = engines[(BOT_MODEL, THREADS)]
print(f"  ✅ Ready!")


class Telegram:
    """Thin Bot API client on a keep-alive session (one TLS handshake, not one per call)."""

    def __init__(self):
        self.session = requests.Session()

    def get_updates(self, offset=None):
        params = {"timeout": 30}
        if offset:
            params["offset"] = offset
        try:
            res = self.session.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            return res.json()["result"]
        except Exception as e:
            log.info(f"Error getting updates: {e}")
            return []

    def download_voice(self, file_id, dest_path):
        try:
            res = self.session.get(f"{API_URL}/getFile", params={"file_id": file_id}, timeout=15)
            file_path = res.json()["result"]["file_path"]
            with self.session.get(f"{FILE_URL}/{file_path}", stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        f.write(chunk)
            return dest_path
        except Exception as e:
            log.error(f"Download failed: {e}")
            return None

    def send_message(self, chat_id, text):
        """Send a message; returns its message_id (for later edits) or None."""
        try:
            res = self.session.post(f"{API_URL}/sendMessage", data={
                "chat_id": chat_id,
                "text": text,
                "disable_notification": True,
            }, timeout=15)
            return res.json()["result"]["message_id"]
        except Exception as e:
            log.error(f"Failed to send message: {e}")
            return None

    def edit_message(self, chat_id, message_id, text):
        try:
            self.session.post(f"{API_URL}/editMessageText", data={
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
            }, timeout=15)
        except Exception as e:
            log.warning(f"Failed to edit message: {e}")


tg = Telegram()


class Notifier(threading.Thread):
    """Runs Telegram calls off the transcription thread so the decoder never waits on HTTP."""

    def __init__(self):
        super().__init__(name="notifier", daemon=True)
        self.tasks = queue.Queue()

    def submit(self, fn):
        self.tasks.put(fn)

    def run(self):
        while True:
            fn = self.tasks.get()
            try:
                fn()
            except Exception as e:
                log.error(f"Notifier task failed: {e}")


notifier = Notifier()


class ReplyStream:
    """One reply message per voice note, updated live while segments arrive.

    Partial texts are coalesced (only the latest is sent) and throttled to MIN_EDIT_INTERVAL.
    The placeholder is delayed by PLACEHOLDER_DELAY; if the final text is ready before
    that, a single message is sent instead.
    """

    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.lock = threading.Lock()
        self.final_event = threading.Event()
        self.deadline = time.time() + PLACEHOLDER_DELAY
        self.latest = None
        self.final = False
        self.scheduled = False
        self.done = False
        self.message_id = None
        self.placeholder_tried = False
        self.last_sent = None
        self.last_edit_at = 0.0

    def start(self):
        notifier.submit(self._tick)

    def update(self, partial_text):
        with self.lock:
            self.latest = f"🗣️ {partial_text}..."
            if self.scheduled:
                return
            self.scheduled = True
        notifier.submit(self._tick)

    def finish(self, text):
        with self.lock:
            self.latest = text
            self.final = True
        self.final_event.set()
        notifier.submit(self._tick)

    def _tick(self):
        if self.done:
            return
        if not self.placeholder_tried:
            self.final_event.wait(max(0.0, self.deadline - time.time()))
            with self.lock:
                text, final = self.latest, self.final
            if final:
                tg.send_message(self.chat_id, text)
                self.done = True
                return
            self.placeholder_tried = True
            self.message_id = tg.send_message(self.chat_id, "🎤 Transcribing...")
            self.last_edit_at = time.time()
            if self.message_id is None:
                log.warning("Placeholder could not be sent; final text will be sent as a new message")
            if text is None:
                return

        wait = self.last_edit_at + MIN_EDIT_INTERVAL - time.time()
        if wait > 0:
            self.final_event.wait(wait)
        with self.lock:
            text, final = self.latest, self.final
            self.scheduled = False
        if text is not None and text != self.last_sent:
            if self.message_id is None:
                if final:
                    tg.send_message(self.chat_id, text)
            else:
                tg.edit_message(self.chat_id, self.message_id, text)
            self.last_sent = text
            self.last_edit_at = time.time()
        if final:
            self.done = True


def send_startup_message():
    """Send startup notification to admin chat if configured."""
    if not ADMIN_CHAT_ID:
        return
    if tg.send_message(ADMIN_CHAT_ID, f"✅ Ascoltino is ready!{format_config_footer()}") is not None:
        log.info(f"Startup message sent to chat {ADMIN_CHAT_ID}")


def get_last_update_id():
    if not os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "w") as f:
            f.write("0")
    with open(LAST_UPDATE_FILE, "r") as f:
        return int(f.read().strip())


def set_last_update_id(update_id):
    with open(LAST_UPDATE_FILE, "w") as f:
        f.write(str(update_id))


def format_config_footer():
    """Footer with bot info (no timing)."""
    parts = [engine.label(BEAM_SIZE, VAD_FILTER), f"v{VERSION}"]
    if BOT_NAME:
        parts.insert(0, BOT_NAME)
    return "\n\n---\n" + " | ".join(parts)


def format_stats_footer(result, eng, beam_size, vad_filter):
    """Footer with transcription stats."""
    speed = result["duration"] / result["elapsed"] if result["elapsed"] > 0 else 0
    parts = [
        f"⏱ {result['elapsed']:.1f}s ({speed:.1f}x)",
        eng.label(beam_size, vad_filter),
        f"v{VERSION}",
    ]
    if BOT_NAME:
        parts.insert(0, BOT_NAME)
    return "\n\n---\n" + " | ".join(parts)


def describe_chat(message):
    """Human-readable summary of where a message came from, for audit logs."""
    chat = message.get("chat", {})
    sender = message.get("from", {})
    chat_label = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
    sender_label = sender.get("username") or sender.get("first_name") or "?"
    return (
        f"chat_id={chat.get('id')} type={chat.get('type')} chat='{chat_label}' "
        f"user_id={sender.get('id')} user='{sender_label}'"
    )


_reported_unauthorized_chats = set()

def report_unauthorized(message):
    """Log an unauthorized voice message and notify the admin once per chat."""
    chat_id = message["chat"]["id"]
    log.warning(f"Unauthorized voice message ignored: {describe_chat(message)}")
    if not ADMIN_CHAT_ID or chat_id in _reported_unauthorized_chats:
        return
    _reported_unauthorized_chats.add(chat_id)
    tg.send_message(
        ADMIN_CHAT_ID,
        f"🚫 Ignored voice message from a chat that is not in ALLOWED_CHAT_IDS:\n{describe_chat(message)}",
    )


def remove_file(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        log.warning(f"Failed to clean up {path}: {e}")


def poller(jobs):
    """Receive updates and download voice notes; transcription happens on the worker thread.

    Downloading here means the next note is already on disk while the current one is
    being transcribed.
    """
    last_update_id = get_last_update_id()
    while True:
        updates = tg.get_updates(offset=last_update_id + 1 if last_update_id else None)
        for update in updates:
            try:
                last_update_id = update["update_id"]
                set_last_update_id(last_update_id)

                message = update.get("message")
                if not message or "chat" not in message:
                    log.info("Non-message update, ignoring")
                    continue
                chat_id = message["chat"]["id"]

                if ALLOWED_CHAT_IDS and chat_id not in ALLOWED_CHAT_IDS:
                    if "voice" in message:
                        report_unauthorized(message)
                    else:
                        log.info(f"Message from unauthorized chat ignored: {describe_chat(message)}")
                    continue

                if "voice" not in message:
                    log.info("Non-voice message, ignoring")
                    continue

                log.info(f"Voice message received: {describe_chat(message)}")
                path = os.path.join(DATA_DIR, f"voice_{last_update_id}.oga")
                t0 = time.time()
                if tg.download_voice(message["voice"]["file_id"], path):
                    log.info(f"File downloaded in {time.time() - t0:.2f}s (queue={jobs.qsize()})")
                    jobs.put({"chat_id": chat_id, "path": path})
            except Exception as e:
                log.error(f"Error processing update: {e}")


def process_job(job):
    chat_id, path = job["chat_id"], job["path"]
    try:
        t0 = time.time()
        audio = decode_audio(path)
        log.info(f"Decoded audio in {time.time() - t0:.2f}s")
    except Exception as e:
        log.error(f"Audio decode failed: {e}")
        tg.send_message(chat_id, "❌ Could not read the audio file.")
        return
    finally:
        remove_file(path)

    if MULTI_CONFIG_MODE:
        log.info(f"Multi-config mode: processing {len(CONFIGS)} configurations")
        tg.send_message(chat_id, f"🎤 Processing with {len(CONFIGS)} configurations...")
        for idx, (model_name, beam_size, vad_filter, threads) in enumerate(CONFIGS, 1):
            eng = engines[(model_name, threads)]
            label = f"[{idx}/{len(CONFIGS)}] {eng.label(beam_size, vad_filter)}"
            log.info(f"Processing config: {label}")
            result = transcribe(eng, audio, beam_size, vad_filter)
            if result:
                footer = format_stats_footer(result, eng, beam_size, vad_filter) if SHOW_FOOTER else ""
                tg.send_message(chat_id, f"🗣️ {result['text']}{footer}")
            else:
                tg.send_message(chat_id, f"❌ Failed: {label}")
        return

    stream = ReplyStream(chat_id)
    stream.start()
    result = transcribe(engine, audio, BEAM_SIZE, VAD_FILTER, on_partial=stream.update)
    if result:
        footer = format_stats_footer(result, engine, BEAM_SIZE, VAD_FILTER) if SHOW_FOOTER else ""
        stream.finish(f"🗣️ {result['text']}{footer}")
    else:
        stream.finish("❌ Could not transcribe audio.")


def transcribe(eng, audio, beam_size, vad_filter, on_partial=None):
    log.info(f"Transcribing ({eng.label(beam_size, vad_filter)})")
    try:
        result = eng.transcribe(audio, beam_size=beam_size, vad_filter=vad_filter, on_partial=on_partial)
    except Exception as e:
        log.error(f"Transcription failed: {e}")
        return None
    if not result:
        log.warning("No transcription result found.")
        return None
    speed = result["duration"] / result["elapsed"] if result["elapsed"] > 0 else 0
    log.info(f"Transcribed {result['duration']:.1f}s of audio in {result['elapsed']:.2f}s ({speed:.1f}x realtime)")
    return result


def main():
    log.info("Bot started")
    notifier.start()
    send_startup_message()

    jobs = queue.Queue()
    threading.Thread(target=poller, args=(jobs,), name="poller", daemon=True).start()

    while True:
        job = jobs.get()
        try:
            process_job(job)
        except Exception as e:
            log.error(f"Error processing voice note: {e}")


if __name__ == "__main__":
    main()
