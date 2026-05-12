# RVC Cluster Debug Tool — Build standalone executable for Windows
#
# Builds a single-file .exe using PyInstaller. Output goes to dist-release/.
#
# Usage (PowerShell):
#   .\build.ps1                # build single-file .exe
#   .\build.ps1 -OneDir        # build as folder (faster startup)
#   .\build.ps1 -Clean         # remove old build artifacts first

param(
    [switch]$OneDir,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvDir     = Join-Path $ProjectRoot ".venv"
$BuildMode   = if ($OneDir) { "--onedir" } else { "--onefile" }

# ── Detect platform ──
$Arch = $env:PROCESSOR_ARCHITECTURE.ToLower()
if ($Arch -eq "amd64") { $Arch = "x86_64" }

Write-Host "================================================================"
Write-Host "  RVC Cluster Debug Tool — Build for windows-$Arch"
Write-Host "================================================================"

# ── Activate or create venv ──
if (-not (Test-Path $VenvDir)) {
    Write-Host ""
    Write-Host "[1/4] Virtualenv not found. Creating one..."
    python -m venv $VenvDir
    & "$VenvDir\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & "$VenvDir\Scripts\pip.exe" install -r (Join-Path $ProjectRoot "requirements.txt")
    & "$VenvDir\Scripts\pip.exe" install -e $ProjectRoot --quiet
}

$Py  = Join-Path $VenvDir "Scripts\python.exe"
$Pip = Join-Path $VenvDir "Scripts\pip.exe"

# ── Get version ──
$Version = & $Py -c "from env_validation_tool import __version__; print(__version__)"
Write-Host "  Tool version: $Version"

# ── Install pyinstaller if missing ──
$HasPyInstaller = & $Py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[2/4] Installing PyInstaller..."
    & $Pip install --upgrade pyinstaller --quiet
} else {
    Write-Host "[2/4] PyInstaller already installed."
}

# ── Optional clean ──
if ($Clean) {
    Write-Host ""
    Write-Host "[3/4] Cleaning old build artifacts..."
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist-release") -ErrorAction SilentlyContinue
    Get-ChildItem $ProjectRoot -Filter *.spec | Remove-Item -Force
}

# ── Build ──
Write-Host ""
Write-Host "[3/4] Building executable ($BuildMode)..."
Set-Location $ProjectRoot

$ExecName = "rvc-cluster-debug-tool"
$DistName = "$ExecName-$Version-windows-$Arch"

# NOTE: --add-data on Windows uses ';' as separator (Linux/macOS use ':')
& $Py -m PyInstaller `
    $BuildMode `
    --name $ExecName `
    --hidden-import pyVmomi `
    --hidden-import pyVim `
    --hidden-import pyVim.connect `
    --hidden-import yaml `
    --hidden-import openpyxl `
    --hidden-import fpdf `
    --hidden-import paramiko `
    --collect-submodules pyVmomi `
    --collect-submodules pyVim `
    --collect-data pyVmomi `
    --add-data "env_validation_tool/config.sample.yaml;env_validation_tool" `
    --noconfirm `
    --log-level WARN `
    run_tool.py

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller build failed"
    exit 1
}

# ── Package ──
Write-Host ""
Write-Host "[4/4] Packaging release artifact..."
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "dist-release") | Out-Null

if ($BuildMode -eq "--onefile") {
    $OutPath = Join-Path $ProjectRoot "dist-release\$DistName.exe"
    Copy-Item (Join-Path $ProjectRoot "dist\$ExecName.exe") $OutPath
    $Size = "{0:N1} MB" -f ((Get-Item $OutPath).Length / 1MB)
    Write-Host "  Built single file : $OutPath ($Size)"
} else {
    $ZipPath = Join-Path $ProjectRoot "dist-release\$DistName.zip"
    Copy-Item (Join-Path $ProjectRoot "env_validation_tool\config.sample.yaml") (Join-Path $ProjectRoot "dist\$ExecName\")
    if (Test-Path (Join-Path $ProjectRoot "README.md")) {
        Copy-Item (Join-Path $ProjectRoot "README.md") (Join-Path $ProjectRoot "dist\$ExecName\")
    }
    Compress-Archive -Path (Join-Path $ProjectRoot "dist\$ExecName") -DestinationPath $ZipPath -Force
    $Size = "{0:N1} MB" -f ((Get-Item $ZipPath).Length / 1MB)
    Write-Host "  Built folder zip : $ZipPath ($Size)"
}

# ── Smoke test ──
Write-Host ""
Write-Host "  Smoke test..."
if ($BuildMode -eq "--onefile") {
    & (Join-Path $ProjectRoot "dist-release\$DistName.exe") --version
} else {
    & (Join-Path $ProjectRoot "dist\$ExecName\$ExecName.exe") --version
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  Build complete!"
Write-Host "================================================================"
Write-Host ""
Write-Host "  Distribute the file in dist-release\ to customers."
Write-Host "  They can run it directly without installing Python:"
Write-Host ""
if ($BuildMode -eq "--onefile") {
    Write-Host "    .\$DistName.exe --version"
    Write-Host "    .\$DistName.exe interactive"
    Write-Host "    .\$DistName.exe report -c config.yaml"
} else {
    Write-Host "    Expand-Archive $DistName.zip"
    Write-Host "    .\$ExecName\$ExecName.exe interactive"
}
Write-Host ""
