#!/bin/bash

echo "============================================"
echo "  BOBCHAT WEB - Starting Server..."
echo "============================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 is not installed!"
    echo "Please install Python from https://python.org"
    exit 1
fi

# Install requirements if needed
if [ ! -f "installed.flag" ]; then
    echo "Installing required packages..."
    pip3 install -r requirements.txt
    touch installed.flag
    echo "Packages installed!"
    echo ""
fi

echo "Starting BobChat Server..."
echo ""
echo "============================================"
echo "  CHAT LINKS:"
echo "============================================"
echo "  Your Link: http://localhost:5000"
echo ""
echo "  To share with friend on same WiFi:"
echo "  1. Find your IP: Open Terminal"
echo "  2. Type: ifconfig (Mac) or ip addr (Linux)"
echo "  3. Look for your IP address"
echo "  4. Share: http://YOUR_IP:5000"
echo ""
echo "  For internet access, install ngrok:"
echo "  https://ngrok.com/download"
echo "  Then run: ngrok http 5000"
echo "============================================"
echo ""

python3 app.py
