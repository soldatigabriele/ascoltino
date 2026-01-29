#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Run with: python3 compare_results.py results/*.json
"""
Compare benchmark results from multiple machines.

Usage:
    python compare_results.py results_machine1.json results_machine2.json ...
    
Or compare all JSON files in results directory:
    python compare_results.py results/*.json
"""

import json
import sys
from pathlib import Path


def load_results(filepath):
    """Load results from JSON file."""
    with open(filepath) as f:
        return json.load(f)


def get_config_key(params):
    """Create a hashable key from params dict."""
    return (
        params.get('model', ''),
        params.get('num_workers', 1),
        params.get('beam_size', 1),
        params.get('vad_filter', False),
    )


def format_config(params):
    """Format config for display."""
    model = str(params.get('model', '?')).ljust(6)
    workers = params.get('num_workers', '?')
    return f"{model} w={workers}"


def compare_machines(result_files):
    """Compare results across machines."""
    machines = {}
    
    for filepath in result_files:
        path = Path(filepath)
        if not path.exists():
            print(f"Warning: {filepath} not found, skipping")
            continue
            
        data = load_results(filepath)
        hostname = data.get('system', {}).get('hostname', path.stem)
        cpu = data.get('system', {}).get('processor', 'unknown')
        cores = data.get('system', {}).get('cpu_count', '?')
        memory = data.get('system', {}).get('memory_gb', '?')
        
        machines[hostname] = {
            'file': str(path),
            'cpu': cpu,
            'cores': cores,
            'memory': memory,
            'benchmarks': {}
        }
        
        for bench in data.get('benchmarks', []):
            key = get_config_key(bench.get('params', {}))
            machines[hostname]['benchmarks'][key] = {
                'time': bench.get('avg_transcribe_time_s'),
                'wer': bench.get('avg_wer'),
                'memory': bench['samples'][0].get('memory_mb') if bench.get('samples') else None,
                'params': bench.get('params', {})
            }
    
    return machines


def print_comparison(machines):
    """Print comparison table."""
    if not machines:
        print("No results to compare")
        return
    
    machine_names = list(machines.keys())
    
    # Header
    print("\n" + "=" * 80)
    print("CROSS-MACHINE BENCHMARK COMPARISON")
    print("=" * 80)
    
    # Machine info
    print("\n## Machines\n")
    for name, info in machines.items():
        print(f"**{name}**")
        print(f"  CPU: {info['cpu']} ({info['cores']} cores)")
        print(f"  Memory: {info['memory']} GB")
        print()
    
    # Get all configs tested
    all_configs = set()
    for m in machines.values():
        all_configs.update(m['benchmarks'].keys())
    
    if not all_configs:
        print("No benchmark configurations found")
        return
    
    # Sort configs by model, then workers
    sorted_configs = sorted(all_configs, key=lambda x: (x[0], x[1]))
    
    # Comparison table
    print("\n## Performance Comparison (Time in seconds)\n")
    
    # Header row
    header = f"{'Config':<18}"
    for name in machine_names:
        header += f" | {name[:12]:>12}"
    header += " | Winner"
    print(header)
    print("-" * len(header))
    
    for config in sorted_configs:
        row = f"{format_config({'model': config[0], 'num_workers': config[1]}):<18}"
        
        times = {}
        for name, info in machines.items():
            bench = info['benchmarks'].get(config)
            if bench and bench['time']:
                times[name] = bench['time']
                row += f" | {bench['time']:>12.3f}"
            else:
                row += f" | {'N/A':>12}"
        
        # Determine winner
        if times:
            winner = min(times, key=times.get)
            if len(times) > 1:
                fastest = times[winner]
                slowest = max(times.values())
                speedup = ((slowest - fastest) / slowest) * 100
                row += f" | {winner} ({speedup:.0f}% faster)"
            else:
                row += f" | {winner}"
        else:
            row += " | -"
        
        print(row)
    
    # Threading analysis per machine
    print("\n\n## Threading Efficiency\n")
    
    for name, info in machines.items():
        print(f"**{name}**")
        
        models = set(c[0] for c in info['benchmarks'].keys())
        for model in sorted(models):
            # Get times for this model at different worker counts
            worker_times = {}
            for config, bench in info['benchmarks'].items():
                if config[0] == model and bench['time']:
                    worker_times[config[1]] = bench['time']
            
            if 1 in worker_times:
                baseline = worker_times[1]
                print(f"  {model}:")
                for workers in sorted(worker_times.keys()):
                    time = worker_times[workers]
                    if workers == 1:
                        print(f"    {workers} worker:  {time:.3f}s (baseline)")
                    else:
                        speedup = ((baseline - time) / baseline) * 100
                        indicator = "↑" if speedup > 0 else "↓"
                        print(f"    {workers} workers: {time:.3f}s ({indicator} {abs(speedup):.1f}%)")
        print()
    
    # Best config per machine
    print("\n## Recommendations\n")
    
    for name, info in machines.items():
        print(f"**{name}**")
        
        # Best speed
        valid_benches = [(k, v) for k, v in info['benchmarks'].items() if v['time']]
        if valid_benches:
            fastest = min(valid_benches, key=lambda x: x[1]['time'])
            print(f"  Fastest: {fastest[0][0]} with {fastest[0][1]} workers ({fastest[1]['time']:.3f}s)")
            
            # Best accuracy
            with_wer = [(k, v) for k, v in valid_benches if v['wer'] is not None]
            if with_wer:
                most_accurate = min(with_wer, key=lambda x: x[1]['wer'])
                print(f"  Most accurate: {most_accurate[0][0]} (WER: {most_accurate[1]['wer']:.2%})")
        print()


def main():
    if len(sys.argv) < 2:
        print("Usage: python compare_results.py <results1.json> [results2.json] ...")
        print("\nOr use glob pattern:")
        print("  python compare_results.py results/*.json")
        sys.exit(1)
    
    result_files = sys.argv[1:]
    machines = compare_machines(result_files)
    print_comparison(machines)


if __name__ == "__main__":
    main()
