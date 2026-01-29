#!/usr/bin/env python3
"""
Whisper Benchmark Runner

Benchmarks faster-whisper transcription with various parameter combinations.
Measures performance (time, memory) and accuracy (WER) for Italian audio samples.
"""

import os
import sys
import json
import time
import argparse
import platform
import socket
from datetime import datetime
from pathlib import Path
from itertools import product

import yaml
import psutil
import jiwer
from faster_whisper import WhisperModel


# Fixed language for all benchmarks
LANGUAGE = "it"

# Default paths
SAMPLES_DIR = Path("/benchmark/samples")
RESULTS_DIR = Path("/benchmark/results")
CONFIG_FILE = Path("/benchmark/config.yaml")


def get_system_info():
    """Collect system information for benchmark context."""
    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def normalize_text(text):
    """Normalize text for WER calculation."""
    if not text:
        return ""
    # Lowercase and remove punctuation for fair comparison
    text = text.lower()
    # Remove common punctuation
    for char in ".,!?;:\"'()-":
        text = text.replace(char, "")
    # Normalize whitespace
    text = " ".join(text.split())
    return text


def load_samples(samples_dir):
    """Load audio samples and their ground truth transcripts."""
    samples = []
    samples_path = Path(samples_dir)
    
    if not samples_path.exists():
        print(f"Warning: Samples directory not found: {samples_path}")
        return samples
    
    # Find all audio files
    audio_extensions = {".wav", ".mp3", ".ogg", ".oga", ".m4a", ".flac", ".opus"}
    
    for audio_file in samples_path.iterdir():
        if audio_file.suffix.lower() in audio_extensions:
            # Look for corresponding ground truth file
            txt_file = audio_file.with_suffix(".txt")
            ground_truth = ""
            
            if txt_file.exists():
                ground_truth = txt_file.read_text(encoding="utf-8").strip()
            else:
                print(f"Warning: No ground truth for {audio_file.name}")
            
            samples.append({
                "path": str(audio_file),
                "name": audio_file.name,
                "ground_truth": normalize_text(ground_truth),
            })
    
    return samples


def load_config(config_path):
    """Load benchmark configuration from YAML file."""
    config_file = Path(config_path)
    
    if not config_file.exists():
        print(f"Config file not found: {config_file}, using defaults")
        return get_default_config()
    
    with open(config_file) as f:
        return yaml.safe_load(f)


def get_default_config():
    """Return default benchmark configuration."""
    return {
        "language": "it",
        "grid": {
            "model": ["tiny", "base"],
            "beam_size": [1, 5],
            "vad_filter": [False, True],
            "compute_type": ["int8"],
            "num_workers": [1],
            "best_of": [1],
        },
        "runs_per_config": 1,
        "record_system_info": True,
    }


def generate_param_combinations(config):
    """Generate all parameter combinations from grid config."""
    grid = config.get("grid", {})
    
    # If specific combinations are provided, use those
    if "combinations" in config:
        return config["combinations"]
    
    # Otherwise, generate from grid
    if not grid:
        return [{}]
    
    keys = list(grid.keys())
    values = [grid[k] if isinstance(grid[k], list) else [grid[k]] for k in keys]
    
    combinations = []
    for combo in product(*values):
        combinations.append(dict(zip(keys, combo)))
    
    return combinations


def run_single_benchmark(audio_path, ground_truth, params, model_cache):
    """Run a single benchmark with given parameters."""
    result = {
        "params": params.copy(),
        "audio_file": Path(audio_path).name,
    }
    
    # Get or create model
    model_key = (params.get("model", "base"), params.get("compute_type", "int8"), params.get("num_workers", 1))
    
    if model_key not in model_cache:
        print(f"  Loading model: {model_key[0]} ({model_key[1]}, workers={model_key[2]})")
        load_start = time.perf_counter()
        model_cache[model_key] = WhisperModel(
            model_key[0],
            device="cpu",
            compute_type=model_key[1],
            num_workers=model_key[2],
        )
        result["load_time_s"] = round(time.perf_counter() - load_start, 3)
    else:
        result["load_time_s"] = 0  # Model already cached
    
    model = model_cache[model_key]
    
    # Measure memory before
    process = psutil.Process()
    mem_before = process.memory_info().rss
    
    # Transcribe
    transcribe_start = time.perf_counter()
    try:
        segments, info = model.transcribe(
            audio_path,
            language=LANGUAGE,
            beam_size=params.get("beam_size", 1),
            vad_filter=params.get("vad_filter", False),
            best_of=params.get("best_of", 1),
            condition_on_previous_text=params.get("condition_on_previous_text", True),
            patience=params.get("patience", 1.0),
        )
        
        # Consume the generator to get all segments
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        
        transcript = " ".join(text_parts)
        result["transcribe_time_s"] = round(time.perf_counter() - transcribe_start, 3)
        result["transcript"] = transcript
        result["detected_language"] = info.language
        result["language_probability"] = round(info.language_probability, 3)
        result["success"] = True
        
    except Exception as e:
        result["transcribe_time_s"] = round(time.perf_counter() - transcribe_start, 3)
        result["transcript"] = ""
        result["error"] = str(e)
        result["success"] = False
    
    # Memory after
    mem_after = process.memory_info().rss
    result["memory_mb"] = round(mem_after / (1024 * 1024), 2)
    result["memory_delta_mb"] = round((mem_after - mem_before) / (1024 * 1024), 2)
    
    # Calculate WER if we have ground truth
    if ground_truth and result.get("success"):
        normalized_transcript = normalize_text(result["transcript"])
        if normalized_transcript and ground_truth:
            result["wer"] = round(jiwer.wer(ground_truth, normalized_transcript), 4)
        else:
            result["wer"] = 1.0 if ground_truth else None
    else:
        result["wer"] = None
    
    return result


def run_benchmarks(samples, param_combinations, runs_per_config=1):
    """Run all benchmark combinations."""
    results = []
    model_cache = {}
    
    total_runs = len(param_combinations) * len(samples) * runs_per_config
    current_run = 0
    
    for params in param_combinations:
        print(f"\nBenchmarking: {params}")
        
        param_results = {
            "params": params.copy(),
            "samples": [],
        }
        
        for sample in samples:
            sample_runs = []
            
            for run_idx in range(runs_per_config):
                current_run += 1
                print(f"  [{current_run}/{total_runs}] {sample['name']} (run {run_idx + 1})")
                
                run_result = run_single_benchmark(
                    sample["path"],
                    sample["ground_truth"],
                    params,
                    model_cache,
                )
                sample_runs.append(run_result)
            
            # Average the runs for this sample
            if runs_per_config > 1:
                avg_result = average_runs(sample_runs)
            else:
                avg_result = sample_runs[0]
            
            param_results["samples"].append(avg_result)
        
        # Calculate averages across samples
        successful_samples = [s for s in param_results["samples"] if s.get("success")]
        if successful_samples:
            param_results["avg_transcribe_time_s"] = round(
                sum(s["transcribe_time_s"] for s in successful_samples) / len(successful_samples), 3
            )
            wer_samples = [s for s in successful_samples if s.get("wer") is not None]
            if wer_samples:
                param_results["avg_wer"] = round(
                    sum(s["wer"] for s in wer_samples) / len(wer_samples), 4
                )
        
        results.append(param_results)
    
    return results


def average_runs(runs):
    """Average multiple runs of the same benchmark."""
    if not runs:
        return {}
    
    if len(runs) == 1:
        return runs[0]
    
    avg = runs[0].copy()
    numeric_keys = ["load_time_s", "transcribe_time_s", "memory_mb", "memory_delta_mb", "wer"]
    
    for key in numeric_keys:
        values = [r.get(key) for r in runs if r.get(key) is not None]
        if values:
            avg[key] = round(sum(values) / len(values), 4)
    
    avg["runs"] = len(runs)
    return avg


def save_results(results, system_info, output_dir):
    """Save benchmark results to files."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Full JSON results
    full_results = {
        "system": system_info,
        "language": LANGUAGE,
        "benchmarks": results,
    }
    
    json_path = output_path / f"results_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(full_results, f, indent=2)
    print(f"\nResults saved to: {json_path}")
    
    # CSV summary
    csv_path = output_path / f"results_{timestamp}.csv"
    with open(csv_path, "w") as f:
        headers = ["model", "beam_size", "vad_filter", "compute_type", "num_workers", 
                   "best_of", "avg_transcribe_time_s", "avg_wer", "memory_mb"]
        f.write(",".join(headers) + "\n")
        
        for bench in results:
            params = bench.get("params", {})
            row = [
                str(params.get("model", "")),
                str(params.get("beam_size", "")),
                str(params.get("vad_filter", "")),
                str(params.get("compute_type", "")),
                str(params.get("num_workers", "")),
                str(params.get("best_of", "")),
                str(bench.get("avg_transcribe_time_s", "")),
                str(bench.get("avg_wer", "")),
                str(bench["samples"][0].get("memory_mb", "") if bench.get("samples") else ""),
            ]
            f.write(",".join(row) + "\n")
    print(f"CSV summary saved to: {csv_path}")
    
    # Markdown report
    md_path = output_path / f"report_{timestamp}.md"
    with open(md_path, "w") as f:
        f.write("# Whisper Benchmark Report\n\n")
        f.write(f"**Date:** {timestamp}\n")
        f.write(f"**Host:** {system_info.get('hostname')}\n")
        f.write(f"**CPU:** {system_info.get('processor')} ({system_info.get('cpu_count')} cores)\n")
        f.write(f"**Memory:** {system_info.get('memory_gb')} GB\n")
        f.write(f"**Language:** {LANGUAGE}\n\n")
        
        f.write("## Results Summary\n\n")
        f.write("| Model | Beam | VAD | Time (s) | WER | Memory (MB) |\n")
        f.write("|-------|------|-----|----------|-----|-------------|\n")
        
        for bench in sorted(results, key=lambda x: x.get("avg_transcribe_time_s", 999)):
            params = bench.get("params", {})
            f.write(f"| {params.get('model', '-')} ")
            f.write(f"| {params.get('beam_size', '-')} ")
            f.write(f"| {params.get('vad_filter', '-')} ")
            f.write(f"| {bench.get('avg_transcribe_time_s', '-')} ")
            f.write(f"| {bench.get('avg_wer', '-')} ")
            mem = bench["samples"][0].get("memory_mb", "-") if bench.get("samples") else "-"
            f.write(f"| {mem} |\n")
        
        f.write("\n## Best Configurations\n\n")
        
        # Best by speed
        fastest = min(results, key=lambda x: x.get("avg_transcribe_time_s", 999))
        f.write(f"**Fastest:** {fastest['params']} ({fastest.get('avg_transcribe_time_s')}s)\n\n")
        
        # Best by accuracy (lowest WER)
        with_wer = [r for r in results if r.get("avg_wer") is not None]
        if with_wer:
            most_accurate = min(with_wer, key=lambda x: x.get("avg_wer", 999))
            f.write(f"**Most Accurate:** {most_accurate['params']} (WER: {most_accurate.get('avg_wer')})\n")
    
    print(f"Report saved to: {md_path}")
    
    return json_path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Whisper Benchmark Runner")
    
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE),
                        help="Path to config YAML file")
    parser.add_argument("--samples", type=str, default=str(SAMPLES_DIR),
                        help="Path to samples directory")
    parser.add_argument("--output", type=str, default=str(RESULTS_DIR),
                        help="Path to output directory")
    
    # Override grid parameters
    parser.add_argument("--models", type=str,
                        help="Comma-separated list of models to test")
    parser.add_argument("--beam-sizes", type=str,
                        help="Comma-separated list of beam sizes")
    parser.add_argument("--vad-filter", type=str,
                        help="Test VAD filter: true, false, or both")
    parser.add_argument("--compute-types", type=str,
                        help="Comma-separated list of compute types")
    parser.add_argument("--num-workers", type=str,
                        help="Comma-separated list of worker counts")
    parser.add_argument("--runs", type=int,
                        help="Number of runs per configuration")
    
    return parser.parse_args()


def apply_arg_overrides(config, args):
    """Apply command line argument overrides to config."""
    if args.models:
        config["grid"]["model"] = args.models.split(",")
    
    if args.beam_sizes:
        config["grid"]["beam_size"] = [int(x) for x in args.beam_sizes.split(",")]
    
    if args.vad_filter:
        if args.vad_filter.lower() == "both":
            config["grid"]["vad_filter"] = [True, False]
        else:
            config["grid"]["vad_filter"] = [args.vad_filter.lower() == "true"]
    
    if args.compute_types:
        config["grid"]["compute_type"] = args.compute_types.split(",")
    
    if args.num_workers:
        config["grid"]["num_workers"] = [int(x) for x in args.num_workers.split(",")]
    
    if args.runs:
        config["runs_per_config"] = args.runs
    
    return config


def main():
    args = parse_args()
    
    print("=" * 60)
    print("Whisper Benchmark Runner")
    print("=" * 60)
    
    # Load config
    config = load_config(args.config)
    config = apply_arg_overrides(config, args)
    
    # System info
    system_info = get_system_info()
    print(f"\nSystem: {system_info['hostname']}")
    print(f"CPU: {system_info['processor']} ({system_info['cpu_count']} cores)")
    print(f"Memory: {system_info['memory_gb']} GB")
    print(f"Language: {LANGUAGE}")
    
    # Load samples
    samples = load_samples(args.samples)
    if not samples:
        print("\nError: No audio samples found!")
        print(f"Add .wav/.mp3/.ogg files to: {args.samples}")
        print("Include .txt files with ground truth for WER calculation.")
        sys.exit(1)
    
    print(f"\nLoaded {len(samples)} sample(s):")
    for s in samples:
        has_gt = "✓" if s["ground_truth"] else "✗"
        print(f"  - {s['name']} (ground truth: {has_gt})")
    
    # Generate parameter combinations
    param_combinations = generate_param_combinations(config)
    runs_per_config = config.get("runs_per_config", 1)
    
    print(f"\nBenchmark configurations: {len(param_combinations)}")
    print(f"Runs per config: {runs_per_config}")
    print(f"Total benchmarks: {len(param_combinations) * len(samples) * runs_per_config}")
    
    # Run benchmarks
    print("\n" + "-" * 60)
    results = run_benchmarks(samples, param_combinations, runs_per_config)
    print("-" * 60)
    
    # Save results
    save_results(results, system_info, args.output)
    
    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
