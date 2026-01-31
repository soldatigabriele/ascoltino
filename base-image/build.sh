#!/bin/bash
# Build and push the base image with all dependencies
#
# Usage:
#   ./build.sh              # Build for current platform
#   ./build.sh --push       # Build multi-arch and push to Docker Hub

set -e

IMAGE="gab9119/ascoltino-base"
TAG="1.0"

cd "$(dirname "$0")"

if [[ "$1" == "--push" ]]; then
    echo "Building and pushing multi-arch image..."
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        --push \
        -t "$IMAGE:$TAG" \
        -t "$IMAGE:latest" \
        .
    echo ""
    echo "Pushed:"
    echo "  $IMAGE:$TAG"
    echo "  $IMAGE:latest"
else
    echo "Building for current platform..."
    docker build -t "$IMAGE:$TAG" -t "$IMAGE:latest" .
    echo ""
    echo "Built: $IMAGE:$TAG"
    echo ""
    echo "To push multi-arch, run: ./build.sh --push"
fi
