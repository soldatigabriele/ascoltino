FROM python:3.11-slim

# Audio is decoded in-process with PyAV (bundled with faster-whisper), so no ffmpeg binary.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Optional: bake models into the image so the first start does not download anything.
# Example: docker build --build-arg PRELOAD_MODELS=parakeet,base .
ARG PRELOAD_MODELS=""
WORKDIR /app
COPY engines.py .
RUN if [ -n "$PRELOAD_MODELS" ]; then \
      python -c "import engines; [engines.create_engine(m.strip(), 1) for m in '$PRELOAD_MODELS'.split(',') if m.strip()]"; \
    fi

COPY . .

CMD ["python", "bot.py"]
