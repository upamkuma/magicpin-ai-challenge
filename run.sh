#!/bin/bash
# ──────────────────────────────────────────
#  Vera Bot — One-command startup
#  Usage: bash run.sh
# ──────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     VERA BOT — Starting up...            ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Step 1: Kill any existing process on port 8080
echo "  [1/4] Clearing port 8080..."
OTHER_PIDS=$(lsof -ti:8080 2>/dev/null)
if [ -n "$OTHER_PIDS" ]; then
    echo "$OTHER_PIDS" | xargs kill -9 2>/dev/null
    sleep 2
fi

# Step 2: Start the bot server in the background
echo "  [2/4] Starting bot server..."
python3 -m uvicorn bot:app --host 0.0.0.0 --port 8080 &
SERVER_PID=$!
echo "         PID: $SERVER_PID"

# Step 3: Wait for server to be ready
echo "  [3/4] Waiting for server..."
for i in {1..15}; do
    if curl -s http://localhost:8080/v1/healthz > /dev/null 2>&1; then
        echo "         Server ready! ✅"
        break
    fi
    sleep 1
done

# Check if server actually started
if ! curl -s http://localhost:8080/v1/healthz > /dev/null 2>&1; then
    echo "         ❌ Server failed to start!"
    exit 1
fi

# Step 4: Load the dataset
echo "  [4/4] Loading dataset..."
python3 load_dataset.py

echo ""
echo "══════════════════════════════════════════"
echo "  ✅ Bot running at http://localhost:8080"
echo "  🛡️  Quality Gate: ACTIVE"
echo ""
echo "  Open in browser:"
echo "    http://localhost:8080          → Dashboard"
echo "    http://localhost:8080/v1/healthz → Health check"
echo ""
echo "  To stop: pkill -f uvicorn"
echo "══════════════════════════════════════════"
echo ""

# Keep the server running in foreground
wait $SERVER_PID
