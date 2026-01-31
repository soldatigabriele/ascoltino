#!/bin/bash
set -e

OPTIONS_FILE="/data/options.json"

# Read options from Home Assistant config
if [ -f "$OPTIONS_FILE" ]; then
    export BOT_TOKEN="$(jq -r '.bot_token' $OPTIONS_FILE)"
    export BOT_MODEL="$(jq -r '.model' $OPTIONS_FILE)"
    export LANGUAGE="$(jq -r '.language' $OPTIONS_FILE)"
    export BEAM_SIZE="$(jq -r '.beam_size' $OPTIONS_FILE)"
    export VAD_FILTER="$(jq -r '.vad_filter' $OPTIONS_FILE)"
    export THREADS="$(jq -r '.threads' $OPTIONS_FILE)"
    export BOT_NAME="$(jq -r '.bot_name' $OPTIONS_FILE)"
    export ADMIN_CHAT_ID="$(jq -r '.admin_chat_id' $OPTIONS_FILE)"
    export SHOW_FOOTER="$(jq -r '.show_footer' $OPTIONS_FILE)"
fi

# Signal we're running in HA environment
export HA_ADDON=true

# Ensure data directory exists
mkdir -p /data/logs

echo "Starting Ascoltino..."
echo "Model: ${BOT_MODEL} | Language: ${LANGUAGE} | Threads: ${THREADS}"

cd /app
exec python3 -u bot.py
