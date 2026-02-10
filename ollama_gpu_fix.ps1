# Stop any running Ollama instance
Write-Host "Stopping Ollama..."
taskkill /IM "ollama_app.exe" /F 2>$null
taskkill /IM "ollama.exe" /F 2>$null

# Wait a moment
Start-Sleep -Seconds 2

# Set Environment Variable for RDNA3/4 compatibility
# User suggested gfx1201 -> 12.0.1
$env:HSA_OVERRIDE_GFX_VERSION = "12.0.1"

# OLLAMA_DEBUG=1 to see what's happening
$env:OLLAMA_DEBUG = "1"

Write-Host "Environment variables set: HSA_OVERRIDE_GFX_VERSION=$env:HSA_OVERRIDE_GFX_VERSION"

# Start Ollama in background
Write-Host "Starting Ollama..."
Start-Process -FilePath "ollama" -ArgumentList "serve" -NoNewWindow

Write-Host "Ollama restarted. Waiting for it to initialize..."
Start-Sleep -Seconds 5

# Check if responding
Write-Host "Checking version..."
ollama --version
