FROM python:3.11-slim

# Install ffmpeg and Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir requests faster-whisper

# Setup app directory
WORKDIR /app
COPY bot.py .
COPY ascoltino/run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
