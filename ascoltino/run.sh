#!/usr/bin/with-contenv bashio

# Export all options as environment variables
export BOT_TOKEN="$(bashio::config 'bot_token')"
export BOT_MODEL="$(bashio::config 'model')"
export LANGUAGE="$(bashio::config 'language')"
export BEAM_SIZE="$(bashio::config 'beam_size')"
export VAD_FILTER="$(bashio::config 'vad_filter')"
export THREADS="$(bashio::config 'threads')"
export BOT_NAME="$(bashio::config 'bot_name')"
export ADMIN_CHAT_ID="$(bashio::config 'admin_chat_id')"

# Signal we're running in HA environment
export HA_ADDON=true

# Ensure data directory exists
mkdir -p /data/logs

bashio::log.info "Starting Ascoltino v1.1.0..."
bashio::log.info "Model: ${BOT_MODEL} | Language: ${LANGUAGE} | Threads: ${THREADS}"

cd /app
exec python3 -u bot.py
