FROM python:3.11-slim

RUN apt-get update
RUN apt-get install -y git ffmpeg
RUN pip install --no-cache-dir git+https://github.com/openai/whisper.git
RUN pip install --no-cache-dir requests
RUN pip install --no-cache-dir faster-whisper
RUN apt-get clean

WORKDIR /app

COPY . .

CMD ["python", "bot.py"]
