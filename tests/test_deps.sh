#!/bin/bash

# Test script to verify dependency resolution consistency
# This script ensures that all dependency combinations resolve to the same lock file

set -e

echo "🧪 Testing dependency resolution consistency..."
echo "This test verifies that:"
echo "1. uv sync --extra all"
echo "2. uv sync --extra [all individual extras]"
echo "Both resolve to the same lock file"
echo ""

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed. Please install uv first."
    echo "Visit: https://docs.astral.sh/uv/getting-started/installation/"
    exit 1
fi

# Function to discover individual extras from pyproject.toml
discover_extras() {
    local pyproject_file="$1"
    if [ ! -f "$pyproject_file" ]; then
        echo "❌ Error: pyproject.toml not found at $pyproject_file"
        exit 1
    fi
    
    # Extract individual extras (excluding 'all') using grep and sed
    # This looks for lines like "mcp = [" and extracts the extra name
    local extras=$(grep -E '^[[:space:]]*[a-zA-Z0-9_-]+[[:space:]]*=' "$pyproject_file" | \
                   sed -E 's/^[[:space:]]*([a-zA-Z0-9_-]+)[[:space:]]*=.*/\1/' | \
                   grep -v '^all$' | \
                   tr '\n' ' ')
    
    if [ -z "$extras" ]; then
        echo "❌ Error: No individual extras found in pyproject.toml"
        exit 1
    fi
    
    echo "$extras"
}

# Create temporary directories
TEMP_DIR1=$(mktemp -d)
TEMP_DIR2=$(mktemp -d)

echo "📁 Created temporary directories:"
echo "  - $TEMP_DIR1"
echo "  - $TEMP_DIR2"

# Function to cleanup temporary directories
cleanup() {
    echo "🧹 Cleaning up temporary directories..."
    rm -rf "$TEMP_DIR1" "$TEMP_DIR2"
}

# Set trap to cleanup on exit
trap cleanup EXIT

# Copy project files to temporary directories
echo "📋 Copying project files..."
for item in pyproject.toml README.md LICENSE; do
    if [ -f "$item" ]; then
        cp "$item" "$TEMP_DIR1/"
        cp "$item" "$TEMP_DIR2/"
    fi
done

# Copy the lkr directory
if [ -d "lkr" ]; then
    cp -r lkr "$TEMP_DIR1/"
    cp -r lkr "$TEMP_DIR2/"
fi

# Discover individual extras
echo "🔍 Discovering individual extras..."
INDIVIDUAL_EXTRAS=$(discover_extras "pyproject.toml")
echo "📦 Found individual extras: $INDIVIDUAL_EXTRAS"

# Test 1: uv sync --extra all
echo ""
echo "🔄 Running: uv sync --extra all"
cd "$TEMP_DIR1"
uv sync --extra all
LOCK_FILE1="$TEMP_DIR1/uv.lock"
HASH1=$(sha256sum "$LOCK_FILE1" | cut -d' ' -f1)
echo "✅ Lock file 1 hash: $HASH1"

# Test 2: uv sync --extra [all individual extras]
echo ""
echo "🔄 Running: uv sync --extra $INDIVIDUAL_EXTRAS"
cd "$TEMP_DIR2"
# Build the uv sync command with all individual extras
UV_CMD="uv sync"
for extra in $INDIVIDUAL_EXTRAS; do
    UV_CMD="$UV_CMD --extra $extra"
done
eval $UV_CMD
LOCK_FILE2="$TEMP_DIR2/uv.lock"
HASH2=$(sha256sum "$LOCK_FILE2" | cut -d' ' -f1)
echo "✅ Lock file 2 hash: $HASH2"

# Compare hashes
echo ""
if [ "$HASH1" = "$HASH2" ]; then
    echo "🎉 SUCCESS: All dependency combinations resolve to the same lock file!"
    echo "✅ Dependency resolution is consistent"
    exit 0
else
    echo "❌ FAILURE: Lock files are different!"
    echo "Hash 1 (--extra all): $HASH1"
    echo "Hash 2 (--extra $INDIVIDUAL_EXTRAS): $HASH2"
    echo ""
    echo "This indicates that the dependency combinations do not resolve to the same set of packages."
    echo "Please check your pyproject.toml configuration."
    exit 1
fi 