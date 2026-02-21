#!/bin/bash
# Build EIA Track macOS app
# Run this from the project directory: ./build_mac.sh

echo "=========================================="
echo "  Building EIA Track for macOS..."
echo "=========================================="

# Clean previous builds
rm -rf build dist

# Build using the spec file
pyinstaller eia_track.spec --clean

echo ""
echo "=========================================="
if [ -d "dist/EIA Track.app" ]; then
    echo "  BUILD SUCCESSFUL!"
    echo ""
    echo "  Your app is at:"
    echo "  dist/EIA Track.app"
    echo ""
    echo "  To share with your team:"
    echo "  1. Right-click 'EIA Track.app' → Compress"
    echo "  2. Send the .zip to your team"
    echo "  3. They unzip it and double-click to run"
    echo "=========================================="

    # Open the dist folder
    open dist/
else
    echo "  BUILD FAILED — check errors above"
    echo "=========================================="
fi
