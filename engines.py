"""Transcription engines used by Ascoltino.

Two backends share one small interface:

* ``WhisperEngine``  - faster-whisper (CTranslate2), model names like ``base``/``medium``/``turbo``.
* ``ParakeetEngine`` - NVIDIA Parakeet-TDT 0.6B v3 via onnx-asr, model name ``parakeet``.

Both consume a 16 kHz mono float32 numpy array produced by :func:`decode_audio`, so the
audio is decoded exactly once (PyAV, bundled with faster-whisper) and no ffmpeg process
is spawned.
"""

import logging
import os
import shutil
import time

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


def env_flag(name, default):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def is_parakeet(model_name):
    return model_name.strip().lower() in PARAKEET_MODELS


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


def create_engine(model_name, threads, language=None):
    if is_parakeet(model_name):
        return ParakeetEngine(model_name, threads, language)
    return WhisperEngine(model_name, threads, language)
