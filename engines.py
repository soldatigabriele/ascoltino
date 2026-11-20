"""Transcription engines used by Ascoltino.

Three backends share one small interface:

* ``WhisperEngine``  - faster-whisper (CTranslate2), model names like ``base``/``medium``/``turbo``.
* ``ParakeetEngine`` - NVIDIA Parakeet-TDT 0.6B v3 via onnx-asr, model name ``parakeet``.
* ``WyomingEngine``  - a speech-to-text server that is already running elsewhere (for
  example a Home Assistant voice add-on), model name ``wyoming``. Loads no model here.

All consume a 16 kHz mono float32 numpy array produced by :func:`decode_audio`, so the
audio is decoded exactly once (PyAV, bundled with faster-whisper) and no ffmpeg process
is spawned.
"""

import json
import logging
import os
import shutil
import socket
import time
from urllib.parse import urlparse

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000

# Public alias -> onnx-asr model id
PARAKEET_MODELS = {
    "parakeet": "nemo-parakeet-tdt-0.6b-v3",
}

# Silence appended to every clip. Avoids the last word being clipped by Parakeet and gives
# Whisper a clean end-of-speech; costs nothing measurable.
TAIL_PAD_SECONDS = float(os.getenv("TAIL_PAD_SECONDS", "0.5"))

# Parakeet processes a clip in a single pass up to this length; longer clips are split on
# silence with Silero VAD to keep memory bounded.
PARAKEET_SINGLE_PASS_MAX_S = float(os.getenv("PARAKEET_SINGLE_PASS_MAX_S", "30"))

# Model name that hands transcription to a Wyoming server instead of loading a model here.
WYOMING_MODEL = "wyoming"
WYOMING_DEFAULT_PORT = 10300
# Wyoming speech-to-text servers are built for short voice commands and transcribe a
# request in one pass, so longer notes are sent as several requests of at most this length.
# It also bounds how long a note can keep the server away from its other clients.
WYOMING_MAX_CHUNK_S = float(os.getenv("WYOMING_MAX_CHUNK_S", "30"))
# Seconds to wait for the transcript of one request.
WYOMING_TIMEOUT = float(os.getenv("WYOMING_TIMEOUT", "120"))
WYOMING_CONNECT_TIMEOUT = 10.0


def env_flag(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def is_parakeet(model_name):
    return model_name.strip().lower() in PARAKEET_MODELS


def is_wyoming(model_name):
    return model_name.strip().lower() == WYOMING_MODEL


def models_root():
    """Directory for downloaded models; shares HF_HOME so one persistent volume covers everything."""
    return os.getenv("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")


def resolve_threads(threads):
    """0 means "all cores"; CTranslate2 would otherwise silently cap 0 at 4."""
    if threads and threads > 0:
        return threads
    return os.cpu_count() or 4


def decode_audio(source, tail_pad_s=TAIL_PAD_SECONDS):
    """Decode any container/codec (Telegram sends Ogg/Opus) to 16 kHz mono float32."""
    from faster_whisper.audio import decode_audio as fw_decode

    audio = fw_decode(source, sampling_rate=SAMPLE_RATE)
    if tail_pad_s > 0:
        pad = np.zeros(int(tail_pad_s * SAMPLE_RATE), dtype=np.float32)
        audio = np.concatenate([audio, pad])
    return audio


def audio_duration(audio, tail_pad_s=TAIL_PAD_SECONDS):
    return max(0.0, len(audio) / SAMPLE_RATE - tail_pad_s)


class Engine:
    """Common interface. ``transcribe`` returns a dict or None when nothing was recognised."""

    kind = "?"

    def __init__(self, model_name, threads):
        self.model_name = model_name
        self.threads = resolve_threads(threads)

    def label(self, beam_size=None, vad_filter=None):
        raise NotImplementedError

    def transcribe(self, audio, beam_size=1, vad_filter=False, on_partial=None, **overrides):
        raise NotImplementedError

    def _result(self, text, audio, started):
        text = " ".join(text.split())
        if not text:
            return None
        return {
            "text": text,
            "duration": audio_duration(audio),
            "elapsed": time.time() - started,
            "model": self.model_name,
            "threads": self.threads,
            "engine": self.kind,
        }


class WhisperEngine(Engine):
    kind = "whisper"

    def __init__(self, model_name, threads, language=None):
        super().__init__(model_name, threads)
        self.language = language or None
        # Must be set before CTranslate2 is imported for the first time.
        os.environ.setdefault("OMP_NUM_THREADS", str(self.threads))
        from faster_whisper import WhisperModel

        self.model = WhisperModel(
            model_name, device="cpu", compute_type="int8", cpu_threads=self.threads
        )

    def label(self, beam_size=None, vad_filter=None):
        parts = [f"model={self.model_name}"]
        if beam_size is not None:
            parts.append(f"beam={beam_size}")
        if vad_filter is not None:
            parts.append(f"vad={'on' if vad_filter else 'off'}")
        parts.append(f"threads={self.threads}")
        return " | ".join(parts)

    def decode_options(self, beam_size, vad_filter, **overrides):
        """Speed-oriented defaults for short voice notes.

        * ``without_timestamps``: with timestamps Whisper ends the 30 s window at the last
          predicted timestamp and re-encodes the remaining tail as a new window, so a
          13 s note can cost two full encoder passes. Without them a <=30 s note is
          always a single pass.
        * ``temperature=0``: disables the temperature fallback, which re-decodes the same
          window up to five more times when the model is unsure (very common on 1-3 s
          clips) and was the main cause of the 10-20 s floor seen in production.
        * ``condition_on_previous_text=False``: independent windows, fewer repetition loops.
        """
        opts = {
            "language": self.language,
            "beam_size": beam_size,
            "vad_filter": vad_filter,
            "without_timestamps": not env_flag("WHISPER_TIMESTAMPS", False),
            "condition_on_previous_text": False,
        }
        if not env_flag("WHISPER_FALLBACK", False):
            opts["temperature"] = 0.0
        if vad_filter:
            opts["vad_parameters"] = {"min_silence_duration_ms": 500, "speech_pad_ms": 200}
        opts.update(overrides)
        return opts

    def transcribe(self, audio, beam_size=1, vad_filter=False, on_partial=None, **overrides):
        started = time.time()
        segments, info = self.model.transcribe(
            audio, **self.decode_options(beam_size, vad_filter, **overrides)
        )
        if not self.language:
            log.info(
                f"Detected language '{info.language}' with probability {info.language_probability:.2f}"
            )
        text = ""
        for segment in segments:
            log.info(f"[{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
            text += segment.text.strip() + " "
            if on_partial:
                on_partial(text.strip())
        return self._result(text, audio, started)


class ParakeetEngine(Engine):
    kind = "parakeet"

    def __init__(self, model_name, threads, language=None):
        super().__init__(model_name, threads)
        import onnx_asr
        import onnxruntime as ort

        sess = ort.SessionOptions()
        sess.intra_op_num_threads = self.threads
        sess.inter_op_num_threads = 1
        model_id = PARAKEET_MODELS[model_name.strip().lower()]
        quant = os.getenv("PARAKEET_QUANTIZATION", "int8") or None
        providers = ["CPUExecutionProvider"]
        # Download into a plain directory rather than the symlinked HF cache: onnxruntime
        # >= 1.30 rejects external-data files whose resolved path leaves the model directory.
        # onnx-asr treats an existing directory as complete, so key it by quantization and
        # start over if a previous download was interrupted.
        model_dir = os.path.join(models_root(), "onnx-asr", f"{model_id}-{quant or 'fp32'}")
        self.model = _load_with_retry(
            lambda: onnx_asr.load_model(
                model_id, model_dir, quantization=quant, sess_options=sess, providers=providers
            ),
            model_dir,
        )
        vad_dir = os.path.join(models_root(), "onnx-asr", "silero-vad")
        vad = _load_with_retry(
            lambda: onnx_asr.load_vad("silero", vad_dir, sess_options=sess, providers=providers),
            vad_dir,
        )
        self.long_form = self.model.with_vad(
            vad,
            batch_size=1,
            max_speech_duration_s=PARAKEET_SINGLE_PASS_MAX_S,
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        )

    def label(self, beam_size=None, vad_filter=None):
        return f"model={self.model_name} | threads={self.threads}"

    def transcribe(self, audio, beam_size=1, vad_filter=False, on_partial=None, **overrides):
        started = time.time()
        use_vad = vad_filter or audio_duration(audio) > PARAKEET_SINGLE_PASS_MAX_S
        if not use_vad:
            text = self.model.recognize(audio, sample_rate=SAMPLE_RATE)
            log.info(f"[single pass] {text}")
            if on_partial and text:
                on_partial(text.strip())
            return self._result(text, audio, started)

        text = ""
        for seg in self.long_form.recognize(audio, sample_rate=SAMPLE_RATE):
            log.info(f"[{seg.start:.2f}s -> {seg.end:.2f}s] {seg.text}")
            text += seg.text.strip() + " "
            if on_partial:
                on_partial(text.strip())
        return self._result(text, audio, started)


def _load_with_retry(load, model_dir):
    from onnx_asr.utils import ModelFileNotFoundError

    try:
        return load()
    except ModelFileNotFoundError:
        if not os.path.isdir(model_dir):
            raise
        log.warning(f"Incomplete model files in {model_dir}, downloading again")
        shutil.rmtree(model_dir, ignore_errors=True)
        return load()


class WyomingError(RuntimeError):
    """The Wyoming server could not be reached, or answered with a failure."""


def parse_wyoming_uri(uri):
    """``tcp://host:port`` (or just ``host:port``) -> ``(host, port)``."""
    uri = (uri or "").strip()
    if not uri:
        raise ValueError(
            f"Model '{WYOMING_MODEL}' needs the address of a Wyoming speech-to-text server: "
            "set WYOMING_URI (add-on option 'Wyoming Server URI'), e.g. tcp://core-whisper:10300"
        )
    parsed = urlparse(uri if "://" in uri else f"tcp://{uri}")
    try:
        host, port = parsed.hostname, parsed.port
    except ValueError:
        host = None
    if parsed.scheme != "tcp" or not host:
        raise ValueError(f"Invalid WYOMING_URI '{uri}': expected tcp://host:port")
    return host, port or WYOMING_DEFAULT_PORT


def _wyoming_event(event_type, data=None, payload=None):
    """One event on the wire: a JSON header line, then optional JSON data and binary payload."""
    header = {"type": event_type}
    data_bytes = json.dumps(data).encode("utf-8") if data else b""
    if data_bytes:
        header["data_length"] = len(data_bytes)
    if payload:
        header["payload_length"] = len(payload)
    return json.dumps(header).encode("utf-8") + b"\n" + data_bytes + (payload or b"")


def _read_wyoming_event(stream):
    """Returns ``(type, data)``, or None when the server closed the connection."""
    line = stream.readline()
    if not line:
        return None
    header = json.loads(line)
    data = header.get("data") or {}
    for field, keep in (("data_length", True), ("payload_length", False)):
        length = header.get(field) or 0
        if not length:
            continue
        body = stream.read(length)
        if len(body) < length:
            return None
        if keep:
            data.update(json.loads(body))
    return header["type"], data


class WyomingEngine(Engine):
    """Speech-to-text on a Wyoming server, e.g. a Home Assistant Whisper or Parakeet add-on.

    Nothing is loaded in this process, so the model that the voice assistant already keeps
    in memory is reused. Speed and accuracy are whatever that server delivers.

    A request is ``transcribe``, ``audio-start``, ``audio-chunk``..., ``audio-stop`` and the
    answer is a single ``transcript``; the protocol is spoken directly over a socket so no
    extra dependency is needed. Long notes are cut at pauses and sent piece by piece, which
    also keeps the live updates in Telegram.
    """

    kind = "wyoming"

    def __init__(self, model_name, threads, language=None, uri=None):
        super().__init__(model_name, threads)
        self.language = language or None
        self.host, self.port = parse_wyoming_uri(uri if uri is not None else os.getenv("WYOMING_URI"))
        self.server = None
        self._describe()

    @property
    def address(self):
        return f"tcp://{self.host}:{self.port}"

    def label(self, beam_size=None, vad_filter=None):
        return f"model={self.model_name} ({self.server})" if self.server else f"model={self.model_name}"

    def _exchange(self, events, want, timeout):
        """Send ``events`` on a fresh connection and return the data of the first ``want`` event."""
        try:
            with socket.create_connection((self.host, self.port), timeout=WYOMING_CONNECT_TIMEOUT) as sock:
                sock.settimeout(timeout)
                for event in events:
                    sock.sendall(event)
                with sock.makefile("rb") as stream:
                    while True:
                        event = _read_wyoming_event(stream)
                        if event is None:
                            raise WyomingError(f"{self.address} closed the connection without a '{want}'")
                        event_type, data = event
                        if event_type == "error":
                            raise WyomingError(f"{self.address} reported: {data.get('text')}")
                        if event_type == want:
                            return data
        except socket.timeout:
            raise WyomingError(f"{self.address} did not answer within {timeout:.0f}s") from None
        except (OSError, ValueError) as e:
            raise WyomingError(f"{self.address}: {e}") from None

    def _describe(self):
        """Ask the server what it is, for the logs and the footer.

        An unreachable server is not fatal: the other add-on may still be starting, and
        every note opens a new connection anyway.
        """
        try:
            info = self._exchange([_wyoming_event("describe")], "info", WYOMING_CONNECT_TIMEOUT)
        except WyomingError as e:
            _announce(f"⚠️  Wyoming server not reachable yet, will retry on the next voice note ({e})",
                      logging.WARNING)
            return
        programs = [p for p in info.get("asr") or [] if p.get("installed", True)]
        if not programs:
            raise WyomingError(f"{self.address} is a Wyoming server but offers no speech-to-text")
        program = programs[0]
        models = [m for m in program.get("models") or [] if m.get("installed", True)]
        self.server = program.get("name") or "?"
        names = ", ".join(str(m.get("name")) for m in models) or "?"
        _announce(f"Wyoming server {self.server} {program.get('version') or ''} at {self.address}, "
                  f"models: {names}")
        languages = {lang for m in models for lang in m.get("languages") or []}
        if self.language and languages and self.language not in languages:
            _announce(f"⚠️  Language '{self.language}' is not offered by the Wyoming server "
                      f"({', '.join(sorted(languages))}): check the models enabled there", logging.WARNING)

    def _pieces(self, audio, vad_filter):
        """The audio as pieces the server can take in one pass each.

        Speech is found with the Silero model bundled with faster-whisper (nothing to
        download) and neighbouring stretches are joined up to WYOMING_MAX_CHUNK_S, so cuts
        only fall on pauses.
        """
        if not vad_filter and audio_duration(audio) <= WYOMING_MAX_CHUNK_S:
            return [audio]
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        speech = get_speech_timestamps(audio, VadOptions(
            max_speech_duration_s=WYOMING_MAX_CHUNK_S, min_silence_duration_ms=500, speech_pad_ms=200,
        ))
        limit = int(WYOMING_MAX_CHUNK_S * SAMPLE_RATE)
        spans = []
        for segment in speech:
            if spans and segment["end"] - spans[-1][0] <= limit:
                spans[-1][1] = segment["end"]
            else:
                spans.append([segment["start"], segment["end"]])
        return [audio[start:end] for start, end in spans]

    def _recognize(self, audio):
        # decode_audio yields 16-bit samples divided by 32768, so this restores them exactly.
        pcm = np.clip(np.round(audio * 32768.0), -32768, 32767).astype("<i2").tobytes()
        audio_format = {"rate": SAMPLE_RATE, "width": 2, "channels": 1}
        step = SAMPLE_RATE * 2  # one second of 16-bit mono per audio-chunk event
        events = [
            _wyoming_event("transcribe", {"language": self.language} if self.language else None),
            _wyoming_event("audio-start", audio_format),
            *(_wyoming_event("audio-chunk", audio_format, pcm[i:i + step]) for i in range(0, len(pcm), step)),
            _wyoming_event("audio-stop"),
        ]
        text = self._exchange(events, "transcript", WYOMING_TIMEOUT).get("text") or ""
        # Some servers (wyoming-onnx-asr) report failures as the text of a normal transcript.
        if text.startswith("ERROR: "):
            raise WyomingError(f"{self.address} reported: {text[len('ERROR: '):]}")
        return text

    def transcribe(self, audio, beam_size=1, vad_filter=False, on_partial=None, **overrides):
        started = time.time()
        if self.server is None:
            self._describe()
        pieces = self._pieces(audio, vad_filter)
        text = ""
        for index, piece in enumerate(pieces, 1):
            part = self._recognize(piece)
            log.info(f"[piece {index}/{len(pieces)}, {len(piece) / SAMPLE_RATE:.1f}s] {part}")
            text += part.strip() + " "
            if on_partial and text.strip():
                on_partial(text.strip())
        return self._result(text, audio, started)


def _announce(message, level=logging.INFO):
    """Start-up facts worth seeing in the container log as well as in the log file."""
    log.log(level, message)
    print(f"  {message}")


def create_engine(model_name, threads, language=None):
    if is_parakeet(model_name):
        return ParakeetEngine(model_name, threads, language)
    if is_wyoming(model_name):
        return WyomingEngine(model_name, threads, language)
    return WhisperEngine(model_name, threads, language)
