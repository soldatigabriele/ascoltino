FROM python:3.11-slim

# Install system dependencies and Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir requests faster-whisper

# Pre-download the base whisper model to speed up first run (optional)
# RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"
