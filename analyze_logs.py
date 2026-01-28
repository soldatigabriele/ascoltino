#!/usr/bin/env python3
"""
Analyze bot.log to extract transcription timing statistics.
"""

import re
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import statistics


@dataclass
class TranscriptionSession:
    """Represents one voice message transcription session."""
    start_time: datetime
    download_done_time: Optional[datetime] = None
    convert_start_time: Optional[datetime] = None
    transcribe_start_time: Optional[datetime] = None
    model_loaded_time: Optional[datetime] = None
    audio_duration_seconds: Optional[float] = None
    detected_language: Optional[str] = None
    language_probability: Optional[float] = None
    end_time: Optional[datetime] = None
    
    @property
    def total_time_seconds(self) -> Optional[float]:
        if self.end_time and self.start_time:
            return (self.end_time - self.start_time).total_seconds()
        return None
    
    @property
    def download_time_seconds(self) -> Optional[float]:
        if self.download_done_time and self.start_time:
            return (self.download_done_time - self.start_time).total_seconds()
        return None
    
    @property
    def conversion_time_seconds(self) -> Optional[float]:
        if self.transcribe_start_time and self.convert_start_time:
            return (self.transcribe_start_time - self.convert_start_time).total_seconds()
        return None
    
    @property
    def model_load_time_seconds(self) -> Optional[float]:
        if self.model_loaded_time and self.transcribe_start_time:
            return (self.model_loaded_time - self.transcribe_start_time).total_seconds()
        return None
    
    @property
    def transcription_time_seconds(self) -> Optional[float]:
        if self.end_time and self.model_loaded_time:
            return (self.end_time - self.model_loaded_time).total_seconds()
        return None
    
    @property
    def realtime_factor(self) -> Optional[float]:
        """How many seconds of processing per second of audio."""
        if self.total_time_seconds and self.audio_duration_seconds:
            return self.total_time_seconds / self.audio_duration_seconds
        return None


def parse_timestamp(line: str) -> datetime:
    """Extract timestamp from log line."""
    match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})', line)
    if match:
        return datetime.strptime(match.group(1), '%Y-%m-%d %H:%M:%S,%f')
    raise ValueError(f"Could not parse timestamp from: {line}")


def parse_audio_duration(line: str) -> float:
    """Parse audio duration from 'Processing audio with duration MM:SS.mmm' line."""
    match = re.search(r'duration (\d{2}):(\d{2}\.\d+)', line)
    if match:
        minutes = int(match.group(1))
        seconds = float(match.group(2))
        return minutes * 60 + seconds
    return 0.0


def parse_language(line: str) -> tuple[str, float]:
    """Parse detected language and probability."""
    match = re.search(r"Detected language '(\w+)' with probability (\d+\.\d+)", line)
    if match:
        return match.group(1), float(match.group(2))
    return "", 0.0


def parse_log_file(filepath: str) -> list[TranscriptionSession]:
    """Parse the log file and extract transcription sessions."""
    sessions = []
    current_session = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            try:
                timestamp = parse_timestamp(line)
            except ValueError:
                continue
            
            if 'Voice message received' in line:
                # Start a new session
                if current_session and current_session.end_time:
                    sessions.append(current_session)
                current_session = TranscriptionSession(start_time=timestamp)
            
            elif current_session:
                if 'File downloaded!' in line:
                    current_session.download_done_time = timestamp
                
                elif 'Converting storage/' in line:
                    current_session.convert_start_time = timestamp
                
                elif 'Transcribing file: model size' in line:
                    current_session.transcribe_start_time = timestamp
                
                elif 'Transcribing file: model from whisper' in line:
                    current_session.model_loaded_time = timestamp
                
                elif 'Processing audio with duration' in line:
                    current_session.audio_duration_seconds = parse_audio_duration(line)
                
                elif 'Detected language' in line:
                    lang, prob = parse_language(line)
                    current_session.detected_language = lang
                    current_session.language_probability = prob
                
                elif 'Sending message' in line:
                    current_session.end_time = timestamp
                    sessions.append(current_session)
                    current_session = None
    
    # Don't forget the last session if it was completed
    if current_session and current_session.end_time:
        sessions.append(current_session)
    
    return sessions


def calculate_stats(values: list[float]) -> dict:
    """Calculate statistics for a list of values."""
    if not values:
        return {}
    
    return {
        'count': len(values),
        'min': min(values),
        'max': max(values),
        'mean': statistics.mean(values),
        'median': statistics.median(values),
        'stdev': statistics.stdev(values) if len(values) > 1 else 0,
    }


def format_duration(seconds: float) -> str:
    """Format seconds as human-readable duration."""
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}m {secs:.2f}s"


def print_stats(name: str, stats: dict):
    """Print statistics in a nice format."""
    if not stats:
        print(f"  {name}: No data")
        return
    
    print(f"  {name}:")
    print(f"    Count:  {stats['count']}")
    print(f"    Min:    {format_duration(stats['min'])}")
    print(f"    Max:    {format_duration(stats['max'])}")
    print(f"    Mean:   {format_duration(stats['mean'])}")
    print(f"    Median: {format_duration(stats['median'])}")
    if stats['stdev'] > 0:
        print(f"    StdDev: {format_duration(stats['stdev'])}")


def main():
    import sys
    
    filepath = sys.argv[1] if len(sys.argv) > 1 else 'logs/bot.log'
    
    print(f"Analyzing: {filepath}")
    print("=" * 60)
    
    sessions = parse_log_file(filepath)
    
    if not sessions:
        print("No transcription sessions found!")
        return
    
    # Extract timing data
    total_times = [s.total_time_seconds for s in sessions if s.total_time_seconds]
    download_times = [s.download_time_seconds for s in sessions if s.download_time_seconds]
    conversion_times = [s.conversion_time_seconds for s in sessions if s.conversion_time_seconds]
    model_load_times = [s.model_load_time_seconds for s in sessions if s.model_load_time_seconds]
    transcription_times = [s.transcription_time_seconds for s in sessions if s.transcription_time_seconds]
    audio_durations = [s.audio_duration_seconds for s in sessions if s.audio_duration_seconds]
    realtime_factors = [s.realtime_factor for s in sessions if s.realtime_factor]
    
    # Print summary
    print(f"\nTotal transcription sessions: {len(sessions)}")
    
    # Date range
    start_date = min(s.start_time for s in sessions)
    end_date = max(s.start_time for s in sessions)
    print(f"Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
    
    # Language distribution
    languages = {}
    for s in sessions:
        if s.detected_language:
            languages[s.detected_language] = languages.get(s.detected_language, 0) + 1
    
    if languages:
        print(f"\nLanguages detected:")
        for lang, count in sorted(languages.items(), key=lambda x: -x[1]):
            pct = (count / len(sessions)) * 100
            print(f"  {lang}: {count} ({pct:.1f}%)")
    
    # Timing statistics
    print("\n" + "=" * 60)
    print("TIMING STATISTICS")
    print("=" * 60)
    
    print("\n[End-to-End Processing Time]")
    print_stats("Total time (received → sent)", calculate_stats(total_times))
    
    print("\n[Breakdown by Phase]")
    print_stats("Download time", calculate_stats(download_times))
    print_stats("Conversion time (OGA → WAV)", calculate_stats(conversion_times))
    print_stats("Model loading time", calculate_stats(model_load_times))
    print_stats("Actual transcription time", calculate_stats(transcription_times))
    
    print("\n[Audio Duration]")
    print_stats("Audio length", calculate_stats(audio_durations))
    
    # Total audio processed
    if audio_durations:
        total_audio = sum(audio_durations)
        print(f"\n  Total audio processed: {format_duration(total_audio)}")
    
    # Realtime factor
    print("\n[Performance: Realtime Factor]")
    print("  (processing time / audio duration - lower is better, <1.0 means faster than realtime)")
    rt_stats = calculate_stats(realtime_factors)
    if rt_stats:
        print(f"    Min:    {rt_stats['min']:.2f}x")
        print(f"    Max:    {rt_stats['max']:.2f}x")
        print(f"    Mean:   {rt_stats['mean']:.2f}x")
        print(f"    Median: {rt_stats['median']:.2f}x")
    
    # Efficiency analysis
    if total_times and audio_durations:
        total_processing = sum(total_times)
        total_audio = sum(audio_durations)
        overall_efficiency = total_processing / total_audio
        print(f"\n  Overall efficiency: {overall_efficiency:.2f}x realtime")
    
    # Distribution of processing times
    print("\n" + "=" * 60)
    print("PROCESSING TIME DISTRIBUTION")
    print("=" * 60)
    
    if total_times:
        buckets = [0, 5, 10, 15, 20, 30, 60, float('inf')]
        bucket_labels = ['0-5s', '5-10s', '10-15s', '15-20s', '20-30s', '30-60s', '>60s']
        bucket_counts = [0] * (len(buckets) - 1)
        
        for t in total_times:
            for i in range(len(buckets) - 1):
                if buckets[i] <= t < buckets[i + 1]:
                    bucket_counts[i] += 1
                    break
        
        print("\n  Processing time histogram:")
        max_count = max(bucket_counts) if bucket_counts else 1
        for label, count in zip(bucket_labels, bucket_counts):
            bar_len = int((count / max_count) * 30) if max_count > 0 else 0
            bar = '█' * bar_len
            pct = (count / len(total_times)) * 100
            print(f"    {label:>8}: {bar:<30} {count:>4} ({pct:>5.1f}%)")
    
    # Top 5 slowest transcriptions
    print("\n" + "=" * 60)
    print("TOP 5 SLOWEST TRANSCRIPTIONS")
    print("=" * 60)
    
    sorted_sessions = sorted(
        [s for s in sessions if s.total_time_seconds],
        key=lambda s: s.total_time_seconds,
        reverse=True
    )[:5]
    
    for i, s in enumerate(sorted_sessions, 1):
        print(f"\n  {i}. {s.start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"     Total time: {format_duration(s.total_time_seconds)}")
        print(f"     Audio duration: {format_duration(s.audio_duration_seconds) if s.audio_duration_seconds else 'N/A'}")
        if s.realtime_factor:
            print(f"     Realtime factor: {s.realtime_factor:.2f}x")
    
    # Trends over time (if we have enough data)
    print("\n" + "=" * 60)
    print("DAILY TRENDS")
    print("=" * 60)
    
    daily_stats = {}
    for s in sessions:
        if s.total_time_seconds:
            day = s.start_time.strftime('%Y-%m-%d')
            if day not in daily_stats:
                daily_stats[day] = []
            daily_stats[day].append(s.total_time_seconds)
    
    if daily_stats:
        print("\n  Average processing time by day:")
        for day in sorted(daily_stats.keys()):
            avg = statistics.mean(daily_stats[day])
            count = len(daily_stats[day])
            print(f"    {day}: {format_duration(avg)} (n={count})")


if __name__ == '__main__':
    main()
