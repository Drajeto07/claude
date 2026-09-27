# A throwaway SmartDoc API for trying the app in a browser: a fresh SQLite
# database and asset folder in a temporary directory -- never the real database
# (backend/scripts/e2e_server.py). Serves http://127.0.0.1:8100.
Set-Location (Join-Path $PSScriptRoot "..\..\backend")
& .\venv\Scripts\python.exe -m scripts.e2e_server
