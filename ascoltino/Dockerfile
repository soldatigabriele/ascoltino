ARG BUILD_FROM
FROM $BUILD_FROM

# Install dependencies
RUN apk add --no-cache python3 py3-pip ffmpeg \
    && pip3 install --no-cache-dir --break-system-packages requests faster-whisper

# Setup app directory
WORKDIR /app
COPY bot.py .
COPY ascoltino/run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
