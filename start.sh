#!/usr/bin/env bash
# One-command launcher untuk Linux VPS / macOS.
# Pakai:  chmod +x start.sh && ./start.sh
cd "$(dirname "$0")"

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python tidak ditemukan. Install: sudo apt install python3 python3-pip -y"
    exit 1
fi

# Pakai virtual environment jika ada
if [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
fi

exec "$PYTHON" start.py "$@"
