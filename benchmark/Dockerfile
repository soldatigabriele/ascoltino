FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Set up working directory
WORKDIR /benchmark

# Copy benchmark files
COPY benchmark_runner.py .
COPY config.yaml .

# Create directories for samples and results
RUN mkdir -p /benchmark/samples /benchmark/results

ENTRYPOINT ["python", "benchmark_runner.py"]
