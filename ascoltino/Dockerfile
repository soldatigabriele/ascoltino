# Use pre-built base image with all dependencies
FROM gab9119/ascoltino-base:latest

# Setup app directory
WORKDIR /app
COPY bot.py .
COPY ascoltino/run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
