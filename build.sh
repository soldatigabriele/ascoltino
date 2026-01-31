#!/bin/bash
set -e

IMAGE="gab9119/ascoltino-bot"
VERSION=""
ARCH="arm64"  # Default to arm64, can specify "amd64"
NO_CACHE=""

# Parse arguments
for arg in "$@"; do
    case $arg in
        --no-cache)
            NO_CACHE="--no-cache"
            ;;
        amd64|arm64)
            ARCH="$arg"
            ;;
        *)
            VERSION="$arg"
            ;;
    esac
done

if [ -z "$VERSION" ]; then
    echo "Usage: ./build.sh <version> [arch] [--no-cache]"
    echo ""
    echo "Examples:"
    echo "  ./build.sh v11              # Build arm64 (default, with cache)"
    echo "  ./build.sh v11 amd64        # Build amd64"
    echo "  ./build.sh v11 --no-cache   # Build without cache (for updating deps)"
    exit 1
fi

# Determine tag suffix based on arch
if [ "$ARCH" = "amd64" ]; then
    TAG="${IMAGE}:amd_${VERSION}"
else
    TAG="${IMAGE}:arm_${VERSION}"
fi

echo "=========================================="
echo "Building Ascoltino"
echo "  Version: $VERSION"
echo "  Arch:    $ARCH"
echo "  Tag:     $TAG"
[ -n "$NO_CACHE" ] && echo "  Cache:   disabled"
echo "=========================================="

docker build \
    $NO_CACHE \
    --platform "linux/${ARCH}" \
    -f Dockerfile \
    -t "$TAG" \
    .

echo ""
echo "Build complete: $TAG"
echo ""

# Ask to push
read -p "Push to Docker Hub? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker push "$TAG"
    echo "Pushed: $TAG"
fi
