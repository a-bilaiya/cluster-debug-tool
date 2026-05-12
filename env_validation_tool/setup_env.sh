#!/bin/bash
# RVC env_validation_tool — one-shot setup for a new machine
# Usage:
#   bash /path/to/env_validation_tool/setup_env.sh
#
# Project layout expected:
#   <project_root>/
#     setup.py
#     requirements.txt
#     env_validation_tool/   ← this script lives here
#       setup_env.sh
#       cli.py, ...

set -e

TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$TOOL_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"
OUTPUT_DIR="/tool/out"

echo "=================================================="
echo "  RVC env_validation_tool — Environment Setup"
echo "=================================================="
echo ""
echo "  Project root   : $PROJECT_ROOT"
echo "  Tool package   : $TOOL_DIR"
echo "  Virtualenv     : $VENV_DIR"
echo "  Output dir     : $OUTPUT_DIR"
echo ""

# ── 1. Python check ──
echo "[1/5] Checking Python 3.8+..."
PYTHON=""
for candidate in python3.11 python3.10 python3.9 python3.8 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | awk '{print $2}')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON=$(command -v "$candidate")
            echo "  Found: $PYTHON ($ver)"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ERROR: Python 3.8+ not found. Install it first:"
    echo "    Ubuntu/Debian : sudo apt install python3 python3-venv python3-pip"
    echo "    RHEL/CentOS   : sudo yum install python3"
    echo "    macOS         : brew install python"
    exit 1
fi

# ── 2. Virtualenv ──
echo ""
echo "[2/5] Creating virtualenv at $VENV_DIR ..."
if [ -d "$VENV_DIR" ]; then
    echo "  Already exists — skipping."
else
    "$PYTHON" -m venv "$VENV_DIR"
    echo "  Created."
fi

PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# ── 3. Install dependencies ──
echo ""
echo "[3/5] Installing dependencies from requirements.txt ..."
"$PIP" install --upgrade pip --quiet
"$PIP" install -r "$PROJECT_ROOT/requirements.txt"
echo "  Done."

# ── 4. Install tool (editable) ──
echo ""
echo "[4/5] Installing env_validation_tool package ..."
cd "$PROJECT_ROOT"
"$PIP" install -e . --quiet
echo "  Done."

# ── 5. Output directory ──
echo ""
echo "[5/5] Creating output directory $OUTPUT_DIR ..."
if [ -d "$OUTPUT_DIR" ]; then
    echo "  Already exists."
elif mkdir -p "$OUTPUT_DIR" 2>/dev/null; then
    echo "  Created."
else
    sudo mkdir -p "$OUTPUT_DIR" && sudo chmod 777 "$OUTPUT_DIR"
    echo "  Created (with sudo)."
fi

# ── Done ──
echo ""
echo "=================================================="
echo "  Setup complete!"
echo "=================================================="
echo ""
echo "  Activate the virtualenv:"
echo "    source $VENV_DIR/bin/activate"
echo ""
echo "  Run interactive mode:"
echo "    python -m env_validation_tool --interactive"
echo ""
echo "  Run with config file:"
echo "    python -m env_validation_tool -c $TOOL_DIR/config_r7k_silver.yaml --mode troubleshoot"
echo ""
echo "  Run without activating venv:"
echo "    $PY -m env_validation_tool --interactive"
echo ""

echo "  Verifying install..."
"$PY" -c "import env_validation_tool; print('  Import OK — tool is ready.')"
