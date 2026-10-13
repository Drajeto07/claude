# The throwaway SmartDoc API (throwaway-backend.ps1) with e-mail turned off, as the Vercel
# image runs it until a sending domain exists (EMAIL_BACKEND=disabled): a fresh SQLite
# database in a temporary directory, never the real one. Serves http://127.0.0.1:8100.
$env:E2E_EMAIL_BACKEND = "disabled"
& (Join-Path $PSScriptRoot "throwaway-backend.ps1")
