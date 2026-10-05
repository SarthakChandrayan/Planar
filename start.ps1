# Start Planar locally: API on :8000, UI on :5173. Ollama must already be running.
# Usage (PowerShell, from the project root):  .\start.ps1
$root = $PSScriptRoot

Start-Process powershell -ArgumentList '-NoExit', '-Command', `
  "Set-Location '$root\backend'; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList '-NoExit', '-Command', `
  "Set-Location '$root\frontend'; npm run dev"

Start-Sleep -Seconds 4
Start-Process 'http://localhost:5173'
