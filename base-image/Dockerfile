# Optional shared base image with all Python dependencies preinstalled.
# Build from the repo root: docker build -f base-image/Dockerfile -t gab9119/ascoltino-base .
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
