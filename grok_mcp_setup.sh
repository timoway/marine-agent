#!/bin/bash

# This script helps you connect your Marine Agent to Grok via Remote MCP

echo "--- Marine Agent: Grok Remote MCP Setup ---"

# 1. Start the server (if not already running)
# Note: The server should be running on port 8000
# /Users/timo-mbp/Documents/Github/marine-agent/venv/bin/python3 marine_server.py --web

# 2. Instructions for Tunneling
echo ""
echo "To connect to Grok, you need to expose your local server to the internet."
echo "We recommend using ngrok:"
echo ""
echo "Step A: Install ngrok (if not installed)"
echo "   brew install ngrok/ngrok/ngrok"
echo ""
echo "Step B: Start the tunnel"
echo "   ngrok http 8000"
echo ""
echo "Step C: Configure Grok"
echo "   In Grok, add a new MCP server with this URL:"
echo "   [YOUR_NGROK_URL]/mcp/sse"
echo ""
echo "Once connected, you can ask Grok:"
echo "'Is it safe to paddle at Venice Beach right now?'"
echo "------------------------------------------"
