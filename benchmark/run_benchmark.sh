#!/bin/bash
# Run Whisper benchmark with Docker (no docker-compose required)
#
# Usage:
#   ./run_benchmark.sh              # Pull image and run
#   ./run_benchmark.sh --build      # Build locally instead of pulling

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="gab9119/whisper-benchmark:amd64"

# Check if we should build locally instead of pulling
if [[ "$1" == "--build" ]]; then
    echo "Building Docker image locally..."
    docker build -t "$IMAGE_NAME" "$SCRIPT_DIR"
    shift
else
    echo "Pulling Docker image from registry..."
    docker pull "$IMAGE_NAME"
fi

# Create results directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/results"

echo ""
echo "Running benchmark..."
echo "Samples: $SCRIPT_DIR/samples/"
echo "Results will be saved to: $SCRIPT_DIR/results/"
echo ""

# Run the benchmark
docker run --rm \
    -v "$SCRIPT_DIR/samples:/benchmark/samples:ro" \
    -v "$SCRIPT_DIR/results:/benchmark/results" \
    -v whisper-benchmark-cache:/root/.cache \
    "$IMAGE_NAME" "$@"

echo ""
echo "Done! Check results in: $SCRIPT_DIR/results/"
