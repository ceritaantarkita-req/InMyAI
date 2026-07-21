$ErrorActionPreference = "Stop"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm run setup
Write-Host "Setup complete. Start with: npm run dev" -ForegroundColor Green
