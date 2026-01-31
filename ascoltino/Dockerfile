ARG BUILD_FROM
FROM $BUILD_FROM

# Install build dependencies, then Python packages, then cleanup build deps
RUN apk add --no-cache \
        python3 \
        py3-pip \
        ffmpeg \
    && apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        pkgconfig \
        ffmpeg-dev \
    && pip3 install --no-cache-dir --break-system-packages requests faster-whisper \
    && apk del .build-deps

# Setup app directory
WORKDIR /app
COPY bot.py .
COPY ascoltino/run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
