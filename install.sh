#!/bin/bash
set -e

# Resolve directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=== Installing Station Master DAW ==="

# Install system packages (requires sudo)
echo "Installing system packages..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv libportaudio2 libasound2-dev ffmpeg

# Create virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv .venv

# Activate and install dependencies
echo "Installing dependencies..."
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e .

# Create Desktop Launcher
echo "Creating Desktop Launcher..."
DESKTOP_FILE="$HOME/Desktop/station-master-daw.desktop"
cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=Station Master DAW
Comment=Retro 4-track Digital Audio Workstation
Exec=$DIR/.venv/bin/python3 $DIR/main.py
Icon=$DIR/Screenshot at 2026-05-06 18-52-07.png
Terminal=false
Categories=AudioVideo;Audio;
EOF
chmod +x "$DESKTOP_FILE"

echo "=== Installation Complete! ==="
echo "You can now start the DAW using the shortcut on your Desktop."
