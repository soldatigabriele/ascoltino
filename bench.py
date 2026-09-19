#!/usr/bin/env python3
"""Benchmark transcription engines on the clips in samples/.

Each ``samples/N.ogg`` is paired with a reference transcript ``samples/N.txt``. For every
model/threads combination the script reports elapsed time, realtime factor (audio seconds
per wall second) and word error rate, using exactly the same code path as the bot
(``engines.py``).

Examples:
    python3 bench.py                                    # default model from BOT_MODEL or "base"
    python3 bench.py --models parakeet,medium,small     # compare engines
    python3 bench.py --models medium --threads 3,4      # thread sweep
    WHISPER_FALLBACK=true WHISPER_TIMESTAMPS=true python3 bench.py --models medium   # old decoder behaviour
    python3 bench.py --models parakeet --json out.json
"""

import argparse
import glob
import json
import os
import re
import sys
import time

import engines

PUNCT = re.compile(r"[^\w\s']", re.UNICODE)


def normalise(text):
    text = text.lower().replace("’", "'")
    text = PUNCT.sub(" ", text)
    return text.split()


def wer(reference, hypothesis):
    """Word error rate via Levenshtein distance on normalised words (no external deps)."""
    ref, hyp = normalise(reference), normalise(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1] / len(ref)


def load_samples(directory):
    samples = []
    for audio_path in sorted(glob.glob(os.path.join(directory, "*.ogg")), key=lambda p: (len(p), p)):
        ref_path = os.path.splitext(audio_path)[0] + ".txt"
        reference = ""
        if os.path.exists(ref_path):
            with open(ref_path, encoding="utf-8") as f:
                reference = f.read().strip()
        samples.append((audio_path, reference))
    return samples


def run_config(model_name, threads, beam_size, vad_filter, language, samples, repeat, warmup):
    t0 = time.time()
    engine = engines.create_engine(model_name, threads, language)
    load_s = time.time() - t0
    label = engine.label(beam_size, vad_filter)
    print(f"\n=== {label} (loaded in {load_s:.1f}s) ===")

    decoded = [(p, engines.decode_audio(p), ref) for p, ref in samples]

    if warmup and decoded:
        shortest = min(decoded, key=lambda d: len(d[1]))
        t0 = time.time()
        engine.transcribe(shortest[1], beam_size=beam_size, vad_filter=vad_filter)
        print(f"warm-up on {os.path.basename(shortest[0])}: {time.time() - t0:.2f}s (not counted)")

    rows = []
    print(f"{'file':<10}{'audio':>7}{'elapsed':>9}{'RTF':>7}{'WER':>7}  text")
    for path, audio, reference in decoded:
        best = None
        for _ in range(repeat):
            res = engine.transcribe(audio, beam_size=beam_size, vad_filter=vad_filter)
            if res and (best is None or res["elapsed"] < best["elapsed"]):
                best = res
        text = best["text"] if best else ""
        elapsed = best["elapsed"] if best else float("nan")
        duration = engines.audio_duration(audio)
        rtf = elapsed / duration if duration else float("nan")
        err = wer(reference, text) if reference else float("nan")
        rows.append({"file": os.path.basename(path), "duration": duration, "elapsed": elapsed,
                     "rtf": rtf, "wer": err, "text": text})
        print(f"{os.path.basename(path):<10}{duration:>6.1f}s{elapsed:>8.2f}s{rtf:>7.2f}{err:>7.1%}  {text[:70]}")

    total_audio = sum(r["duration"] for r in rows)
    total_elapsed = sum(r["elapsed"] for r in rows)
    wers = [r["wer"] for r in rows if r["wer"] == r["wer"]]
    summary = {
        "label": label, "model": model_name, "threads": engine.threads, "beam_size": beam_size,
        "vad_filter": vad_filter, "load_s": load_s, "total_audio_s": total_audio,
        "total_elapsed_s": total_elapsed,
        "rtf": total_elapsed / total_audio if total_audio else float("nan"),
        "mean_wer": sum(wers) / len(wers) if wers else float("nan"),
        "files": rows,
    }
    print(f"TOTAL     {total_audio:>6.1f}s{total_elapsed:>8.2f}s{summary['rtf']:>7.2f}{summary['mean_wer']:>7.1%}  "
          f"(speed {1 / summary['rtf']:.1f}x realtime)")
    return summary


def parse_list(value, cast=str):
    return [cast(v.strip()) for v in value.split(",") if v.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=os.getenv("BOT_MODEL", "base"),
                    help="comma-separated: parakeet, tiny, base, small, medium, turbo, large-v3, ...")
    ap.add_argument("--threads", default=os.getenv("THREADS", "0"), help="comma-separated, 0 = all cores")
    ap.add_argument("--beam", default=os.getenv("BEAM_SIZE", "1"), help="comma-separated beam sizes (whisper)")
    ap.add_argument("--vad", default=os.getenv("VAD_FILTER", "false"), help="comma-separated true/false")
    ap.add_argument("--language", default=os.getenv("LANGUAGE", "it"))
    ap.add_argument("--samples", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples"))
    ap.add_argument("--repeat", type=int, default=1, help="runs per file, best time kept")
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--json", help="write full results to this file")
    args = ap.parse_args()

    samples = load_samples(args.samples)
    if not samples:
        sys.exit(f"no .ogg files in {args.samples}")
    print(f"{len(samples)} samples, {os.cpu_count()} CPUs, "
          f"WHISPER_TIMESTAMPS={os.getenv('WHISPER_TIMESTAMPS', 'false')} "
          f"WHISPER_FALLBACK={os.getenv('WHISPER_FALLBACK', 'false')}")

    results = []
    for model in parse_list(args.models):
        for threads in parse_list(args.threads, int):
            for vad in parse_list(args.vad, lambda v: v.lower() == "true"):
                beams = [1] if engines.is_parakeet(model) else parse_list(args.beam, int)
                for beam in beams:
                    results.append(run_config(model, threads, beam, vad, args.language, samples,
                                              args.repeat, not args.no_warmup))

    if len(results) > 1:
        print("\n=== summary ===")
        print(f"{'config':<48}{'RTF':>7}{'speed':>8}{'WER':>7}")
        for r in sorted(results, key=lambda r: r["rtf"]):
            print(f"{r['label']:<48}{r['rtf']:>7.2f}{1 / r['rtf']:>7.1f}x{r['mean_wer']:>7.1%}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
