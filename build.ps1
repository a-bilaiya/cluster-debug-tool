# RVC Cluster Debug Tool — Build standalone executables for Windows
#
# Builds one or both single-file .exe files using PyInstaller. Output goes to
# dist-release/.
#
# Usage (PowerShell):
#   .\build.ps1                       # build both binaries (main + vminfo)
#   .\build.ps1 -Target main          # build only the main tool
#   .\build.ps1 -Target vminfo        # build only the vminfo report tool
#   .\build.ps1 -OneDir               # folder distribution (faster startup)
#   .\build.ps1 -Clean                # remove old build artifacts first

param(
    [ValidateSet("main", "vminfo", "all")]
    [string]$Target = "all",
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
Write-Host "  Target: $Target   Mode: $BuildMode"
Write-Host "================================================================"

# ── Activate or create venv ──
if (-not (Test-Path $VenvDir)) {
    Write-Host ""
    Write-Host "[setup] Virtualenv not found. Creating one..."
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
$null = & $Py -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing PyInstaller..."
    & $Pip install --upgrade pyinstaller --quiet
}

# ── Optional clean ──
if ($Clean) {
    Write-Host "  Cleaning old build artifacts..."
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "build") -ErrorAction SilentlyContinue
    Remove-Item -Recurse -Force (Join-Path $ProjectRoot "dist-release") -ErrorAction SilentlyContinue
    Get-ChildItem $ProjectRoot -Filter *.spec | Remove-Item -Force
}

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "dist-release") | Out-Null
Set-Location $ProjectRoot

# ── Build helper ──
function Build-One {
    param([string]$ExecName, [string]$EntryScript)

    $DistName = "$ExecName-$Version-windows-$Arch"

    Write-Host ""
    Write-Host "── Building: $ExecName (entry: $EntryScript) ──────────────"

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
        $EntryScript

    if ($LASTEXITCODE -ne 0) {
        Write-Error "PyInstaller build failed for $ExecName"
        exit 1
    }

    if ($BuildMode -eq "--onefile") {
        $OutPath = Join-Path $ProjectRoot "dist-release\$DistName.exe"
        Copy-Item (Join-Path $ProjectRoot "dist\$ExecName.exe") $OutPath
        $Size = "{0:N1} MB" -f ((Get-Item $OutPath).Length / 1MB)
        Write-Host "  ✓ $DistName.exe ($Size)"
    } else {
        $ZipPath = Join-Path $ProjectRoot "dist-release\$DistName.zip"
        Copy-Item (Join-Path $ProjectRoot "env_validation_tool\config.sample.yaml") (Join-Path $ProjectRoot "dist\$ExecName\") -ErrorAction SilentlyContinue
        if (Test-Path (Join-Path $ProjectRoot "README.md")) {
            Copy-Item (Join-Path $ProjectRoot "README.md") (Join-Path $ProjectRoot "dist\$ExecName\")
        }
        Compress-Archive -Path (Join-Path $ProjectRoot "dist\$ExecName") -DestinationPath $ZipPath -Force
        $Size = "{0:N1} MB" -f ((Get-Item $ZipPath).Length / 1MB)
        Write-Host "  ✓ $DistName.zip ($Size)"
    }
}

# ── Build main tool ──
if ($Target -eq "main" -or $Target -eq "all") {
    Build-One -ExecName "rvc-cluster-debug-tool" -EntryScript "run_tool.py"
}

# ── Build vminfo standalone ──
if ($Target -eq "vminfo" -or $Target -eq "all") {
    Build-One -ExecName "vminfo-report" -EntryScript "scripts/vminfo_report.py"
}

Write-Host ""
Write-Host "================================================================"
Write-Host "  Build complete — artifacts in dist-release\"
Write-Host "================================================================"
Get-ChildItem (Join-Path $ProjectRoot "dist-release") | Format-Table Name, @{N='Size';E={"{0:N1} MB" -f ($_.Length/1MB)}}
