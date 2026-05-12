#!/usr/bin/env bash
# RVC Cluster Debug Tool — Build standalone executable
#
# Builds a single-file executable using PyInstaller for the current platform
# (Linux or macOS). Output goes to dist-release/.
#
# Usage:
#   bash build.sh                 # build for current platform
#   bash build.sh --onedir        # build as folder (faster startup)
#   bash build.sh --clean         # remove old build artifacts first

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
BUILD_MODE="--onefile"
CLEAN_FIRST=0

for arg in "$@"; do
    case "$arg" in
        --onefile)  BUILD_MODE="--onefile"  ;;
        --onedir)   BUILD_MODE="--onedir"   ;;
        --clean)    CLEAN_FIRST=1           ;;
        -h|--help)
            echo "Usage: bash build.sh [--onefile|--onedir] [--clean]"
            echo "  --onefile  Single executable (default, slower startup ~2s)"
            echo "  --onedir   Folder with executable + libs (faster startup)"
            echo "  --clean    Remove dist/ build/ dist-release/ first"
            exit 0
            ;;
    esac
done

# ── Detect platform ──
PLATFORM=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$PLATFORM" in
    linux)  PLATFORM_NAME="linux"  ;;
    darwin) PLATFORM_NAME="macos"  ;;
    *)      PLATFORM_NAME="$PLATFORM" ;;
esac

echo "================================================================"
echo "  RVC Cluster Debug Tool — Build for ${PLATFORM_NAME}-${ARCH}"
echo "================================================================"

# ── Activate or create venv ──
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "[1/4] Virtualenv not found — running setup_env.sh first..."
    bash "${PROJECT_ROOT}/env_validation_tool/setup_env.sh"
fi

PY="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"

# ── Get version ──
VERSION=$("$PY" -c "from env_validation_tool import __version__; print(__version__)")
echo "  Tool version: $VERSION"

# ── Install pyinstaller if missing ──
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo ""
    echo "[2/4] Installing PyInstaller..."
    "$PIP" install --upgrade pyinstaller --quiet
else
    echo "[2/4] PyInstaller already installed."
fi

# ── Optional clean ──
if [ "$CLEAN_FIRST" = "1" ]; then
    echo ""
    echo "[3/4] Cleaning old build artifacts..."
    rm -rf "${PROJECT_ROOT}/dist" "${PROJECT_ROOT}/build" "${PROJECT_ROOT}/dist-release"
    rm -f "${PROJECT_ROOT}"/*.spec
fi

# ── Build ──
echo ""
echo "[3/4] Building executable (${BUILD_MODE})..."
cd "$PROJECT_ROOT"

EXEC_NAME="rvc-cluster-debug-tool"
DIST_NAME="${EXEC_NAME}-${VERSION}-${PLATFORM_NAME}-${ARCH}"

"$PY" -m PyInstaller \
    "$BUILD_MODE" \
    --name "$EXEC_NAME" \
    --hidden-import pyVmomi \
    --hidden-import pyVim \
    --hidden-import pyVim.connect \
    --hidden-import yaml \
    --hidden-import openpyxl \
    --hidden-import fpdf \
    --hidden-import paramiko \
    --collect-submodules pyVmomi \
    --collect-submodules pyVim \
    --collect-data pyVmomi \
    --add-data "env_validation_tool/config.sample.yaml:env_validation_tool" \
    --noconfirm \
    --log-level WARN \
    run_tool.py

# ── Package ──
echo ""
echo "[4/4] Packaging release artifact..."
mkdir -p "${PROJECT_ROOT}/dist-release"

if [ "$BUILD_MODE" = "--onefile" ]; then
    OUT_PATH="${PROJECT_ROOT}/dist-release/${DIST_NAME}"
    cp "${PROJECT_ROOT}/dist/${EXEC_NAME}" "$OUT_PATH"
    chmod +x "$OUT_PATH"
    SIZE=$(du -h "$OUT_PATH" | cut -f1)
    echo "  Built single file : $OUT_PATH ($SIZE)"
else
    TARBALL="${PROJECT_ROOT}/dist-release/${DIST_NAME}.tar.gz"
    cp "${PROJECT_ROOT}/env_validation_tool/config.sample.yaml" "${PROJECT_ROOT}/dist/${EXEC_NAME}/"
    cp "${PROJECT_ROOT}/README.md" "${PROJECT_ROOT}/dist/${EXEC_NAME}/" 2>/dev/null || true
    cd "${PROJECT_ROOT}/dist"
    tar czf "$TARBALL" "${EXEC_NAME}"
    cd "$PROJECT_ROOT"
    SIZE=$(du -h "$TARBALL" | cut -f1)
    echo "  Built folder tarball : $TARBALL ($SIZE)"
fi

# ── Smoke test ──
echo ""
echo "  Smoke test..."
if [ "$BUILD_MODE" = "--onefile" ]; then
    "${PROJECT_ROOT}/dist-release/${DIST_NAME}" --version
else
    "${PROJECT_ROOT}/dist/${EXEC_NAME}/${EXEC_NAME}" --version
fi

echo ""
echo "================================================================"
echo "  Build complete!"
echo "================================================================"
echo ""
echo "  Distribute the file in dist-release/ to customers."
echo "  They can run it directly without installing Python:"
if [ "$BUILD_MODE" = "--onefile" ]; then
    echo ""
    echo "    ./${DIST_NAME} --version"
    echo "    ./${DIST_NAME} interactive"
    echo "    ./${DIST_NAME} report -c config.yaml"
else
    echo ""
    echo "    tar xzf ${DIST_NAME}.tar.gz"
    echo "    ./${EXEC_NAME}/${EXEC_NAME} interactive"
fi
echo ""
