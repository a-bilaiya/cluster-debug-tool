#!/usr/bin/env bash
# RVC Cluster Debug Tool — Build standalone executables
#
# Builds one or both single-file executables using PyInstaller for the current
# platform (Linux or macOS). Output goes to dist-release/.
#
# Usage:
#   bash build.sh                   # build both binaries (main + vminfo)
#   bash build.sh --target main     # build only the main tool
#   bash build.sh --target vminfo   # build only the vminfo report tool
#   bash build.sh --onedir          # folder distribution (faster startup)
#   bash build.sh --clean           # remove old build artifacts first
#
# Outputs in dist-release/:
#   rvc-cluster-debug-tool-<version>-<os>-<arch>     (main tool)
#   vminfo-report-<version>-<os>-<arch>              (standalone vminfo)

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
BUILD_MODE="--onefile"
CLEAN_FIRST=0
TARGET="all"

while [ $# -gt 0 ]; do
    case "$1" in
        --onefile)  BUILD_MODE="--onefile"  ;;
        --onedir)   BUILD_MODE="--onedir"   ;;
        --clean)    CLEAN_FIRST=1           ;;
        --target)   shift; TARGET="$1"      ;;
        --target=*) TARGET="${1#*=}"        ;;
        -h|--help)
            echo "Usage: bash build.sh [--target main|vminfo|all] [--onefile|--onedir] [--clean]"
            echo "  --target main    Build the main rvc-cluster-debug-tool"
            echo "  --target vminfo  Build the standalone vminfo-report tool"
            echo "  --target all     Build both (default)"
            echo "  --onefile        Single executable (default, slower startup ~2s)"
            echo "  --onedir         Folder with executable + libs (faster startup)"
            echo "  --clean          Remove dist/ build/ dist-release/ first"
            exit 0
            ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
    shift
done

case "$TARGET" in
    main|vminfo|all) ;;
    *) echo "ERROR: --target must be 'main', 'vminfo', or 'all' (got: $TARGET)"; exit 1 ;;
esac

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
echo "  Target: ${TARGET}   Mode: ${BUILD_MODE}"
echo "================================================================"

# ── Activate or create venv ──
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "[setup] Virtualenv not found — running setup_env.sh first..."
    bash "${PROJECT_ROOT}/env_validation_tool/setup_env.sh"
fi

PY="${VENV_DIR}/bin/python"
PIP="${VENV_DIR}/bin/pip"

# ── Get version ──
VERSION=$("$PY" -c "from env_validation_tool import __version__; print(__version__)")
echo "  Tool version: $VERSION"

# ── Install pyinstaller if missing ──
if ! "$PY" -c "import PyInstaller" 2>/dev/null; then
    echo "  Installing PyInstaller..."
    "$PIP" install --upgrade pyinstaller --quiet
fi

# ── Optional clean ──
if [ "$CLEAN_FIRST" = "1" ]; then
    echo "  Cleaning old build artifacts..."
    rm -rf "${PROJECT_ROOT}/dist" "${PROJECT_ROOT}/build" "${PROJECT_ROOT}/dist-release"
    rm -f "${PROJECT_ROOT}"/*.spec
fi

mkdir -p "${PROJECT_ROOT}/dist-release"
cd "$PROJECT_ROOT"

# ── Build helper ──
# args: <exec_name> <entry_script> [extra_pyinstaller_args...]
build_one() {
    local exec_name="$1"
    local entry_script="$2"
    shift 2

    local dist_name="${exec_name}-${VERSION}-${PLATFORM_NAME}-${ARCH}"

    echo ""
    echo "── Building: $exec_name (entry: $entry_script) ──────────────"

    "$PY" -m PyInstaller \
        "$BUILD_MODE" \
        --name "$exec_name" \
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
        "$@" \
        "$entry_script"

    if [ "$BUILD_MODE" = "--onefile" ]; then
        local out_path="${PROJECT_ROOT}/dist-release/${dist_name}"
        cp "${PROJECT_ROOT}/dist/${exec_name}" "$out_path"
        chmod +x "$out_path"
        local size=$(du -h "$out_path" | cut -f1)
        echo "  ✓ ${dist_name}  ($size)"
        # Smoke test
        "${out_path}" --version 2>/dev/null || true
    else
        local tarball="${PROJECT_ROOT}/dist-release/${dist_name}.tar.gz"
        cp "${PROJECT_ROOT}/env_validation_tool/config.sample.yaml" \
           "${PROJECT_ROOT}/dist/${exec_name}/" 2>/dev/null || true
        cp "${PROJECT_ROOT}/README.md" \
           "${PROJECT_ROOT}/dist/${exec_name}/" 2>/dev/null || true
        (cd "${PROJECT_ROOT}/dist" && tar czf "$tarball" "${exec_name}")
        local size=$(du -h "$tarball" | cut -f1)
        echo "  ✓ ${dist_name}.tar.gz  ($size)"
    fi
}

# ── Build main tool ──
if [ "$TARGET" = "main" ] || [ "$TARGET" = "all" ]; then
    build_one "rvc-cluster-debug-tool" "run_tool.py"
fi

# ── Build vminfo standalone ──
if [ "$TARGET" = "vminfo" ] || [ "$TARGET" = "all" ]; then
    build_one "vminfo-report" "scripts/vminfo_report.py"
fi

echo ""
echo "================================================================"
echo "  Build complete — artifacts in dist-release/"
echo "================================================================"
ls -lh "${PROJECT_ROOT}/dist-release/"
echo ""
echo "  Quick test:"
if [ "$TARGET" = "main" ] || [ "$TARGET" = "all" ]; then
    echo "    ./dist-release/rvc-cluster-debug-tool-${VERSION}-${PLATFORM_NAME}-${ARCH} --version"
fi
if [ "$TARGET" = "vminfo" ] || [ "$TARGET" = "all" ]; then
    echo "    ./dist-release/vminfo-report-${VERSION}-${PLATFORM_NAME}-${ARCH} --help"
fi
echo ""
