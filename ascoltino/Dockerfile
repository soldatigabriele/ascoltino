FROM python:3.11-slim

# jq parses /data/options.json in run.sh. Audio decoding is done in-process (PyAV), no ffmpeg.
RUN apt-get update && \
    apt-get install -y --no-install-recommends jq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /app
COPY bot.py engines.py ./
COPY ascoltino/run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
