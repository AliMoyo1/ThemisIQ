#!/bin/bash
# Data Protection Sentinel — macOS/Linux startup script

echo ""
echo "  ╔══════════════════════════════════════════════════════════╗"
echo "  ║       Data Protection SENTINEL  — by Ali Moyo            ║"
echo "  ╚══════════════════════════════════════════════════════════╝"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [ERROR] Python 3 not found. Install from https://python.org"
    exit 1
fi

# Create .env if missing
if [ ! -f ".env" ]; then
    echo "  [SETUP] .env not found — copying from template..."
    cp .env.example .env
    echo "  [SETUP] Edit .env with your API key, then re-run this script."
    exit 0
fi

# Install dependencies
echo "  [SETUP] Installing dependencies..."
pip3 install -r requirements.txt --quiet

echo ""
echo "  [OK] Starting on http://localhost:5000"
echo "  [OK] Press Ctrl+C to stop"
echo ""

# Open browser (macOS / Linux)
sleep 2 && (open "http://localhost:5000" 2>/dev/null || xdg-open "http://localhost:5000" 2>/dev/null) &

# Start app
python3 app.py
