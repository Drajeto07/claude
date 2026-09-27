# The frontend in development mode against the throwaway API
# (throwaway-backend.ps1) on :8100, at http://localhost:3100.
$env:NEXT_DIST_DIR = ".next-preview"
$env:NEXT_PUBLIC_API_BASE_URL = "http://localhost:8100"
Set-Location (Join-Path $PSScriptRoot "..\..\frontend")
npx next dev --port 3100
