# ==============================================================================
# Setup Qdrant Native Binary as Service on Windows Server (Air-gapped ready)
# ==============================================================================

param(
    [string]$InstallDir = "C:\Qdrant",
    [string]$Version = "v1.9.2",
    [int]$Port = 6333
)

$ErrorActionPreference = "Stop"

Write-Host "=== Setting up Native Qdrant Binary on Windows ===" -ForegroundColor Cyan

# 1. Create install and storage directories
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
}
$StorageDir = Join-Path $InstallDir "storage"
$SnapshotsDir = Join-Path $InstallDir "snapshots"
New-Item -ItemType Directory -Path $StorageDir -Force | Out-Null
New-Item -ItemType Directory -Path $SnapshotsDir -Force | Out-Null

$QdrantExe = Join-Path $InstallDir "qdrant.exe"

# 2. Check if binary already exists
if (-not (Test-Path $QdrantExe)) {
    $ZipUrl = "https://github.com/qdrant/qdrant/releases/download/$Version/qdrant-x86_64-pc-windows-msvc.zip"
    $ZipFile = Join-Path $InstallDir "qdrant.zip"

    Write-Host "Downloading Qdrant $Version binary from $ZipUrl..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile
        Expand-Archive -Path $ZipFile -DestinationPath $InstallDir -Force
        Remove-Item $ZipFile -Force
        Write-Host "Qdrant binary extracted to $QdrantExe" -ForegroundColor Green
    }
    catch {
        Write-Warning "Could not download directly (Air-gapped machine?). Please manually copy 'qdrant.exe' to '$InstallDir'."
    }
} else {
    Write-Host "Found existing qdrant.exe at $QdrantExe" -ForegroundColor Green
}

# 3. Create config.yaml for native Qdrant
$ConfigFile = Join-Path $InstallDir "config.yaml"
$ConfigContent = @"
service:
  host: 0.0.0.0
  http_port: $Port
  grpc_port: 6334

storage:
  storage_path: ./storage
  snapshots_path: ./snapshots
  on_disk_payload: true

telemetry_disabled: true
"@

Set-Content -Path $ConfigFile -Value $ConfigContent -Encoding UTF8
Write-Host "Created configuration file at $ConfigFile" -ForegroundColor Green

# 4. Create run script
$RunBat = Join-Path $InstallDir "run_qdrant.bat"
$BatContent = @"
@echo off
cd /d "$InstallDir"
echo Starting Qdrant Native on port $Port...
qdrant.exe --config-path config.yaml
pause
"@
Set-Content -Path $RunBat -Value $BatContent -Encoding ASCII
Write-Host "Created startup batch script at $RunBat" -ForegroundColor Green

Write-Host "`n[SUCCESS] Setup complete!" -ForegroundColor Cyan
Write-Host "To run Qdrant manually, execute: $RunBat"
Write-Host "To register as a Windows Service (NSSM recommended):"
Write-Host "  nssm install QdrantService `"$QdrantExe`" `"--config-path config.yaml`""
Write-Host "  nssm start QdrantService"
