# NiftyMind - Local Development Startup Script (Windows)
# Usage: .\start.ps1

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# Load .env file if present
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]+)=(.*)$') {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim()
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
    Write-Host "Loaded .env" -ForegroundColor Green
} else {
    Write-Warning ".env not found. Copy .env.example to .env and fill in your values."
    exit 1
}

if (-not $env:DATABASE_URL) {
    Write-Warning "DATABASE_URL is not set in .env"
    exit 1
}

# Start API server in a new terminal window
Write-Host "Starting API server on port 8080..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$Root'; `$env:DATABASE_URL='$env:DATABASE_URL'; `$env:PORT='8080'; pnpm --filter @workspace/api-server run dev"
)

Start-Sleep -Seconds 2

# Start Expo web app in a new terminal window
Write-Host "Starting Expo app on port 8082..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "cd '$Root/artifacts/mobile'; pnpm run dev"
)

Write-Host ""
Write-Host "Services starting..." -ForegroundColor Green
Write-Host "  App:  http://localhost:8082" -ForegroundColor Yellow
Write-Host "  API:  http://localhost:8080/api/healthz" -ForegroundColor Yellow
Write-Host ""
Write-Host "Open http://localhost:8082 in your browser once Metro is ready."
