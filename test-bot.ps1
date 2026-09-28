# Lance PompesBot en mode test :
#   - sur une copie des données (data\test), jamais sur les vraies ;
#   - dans le salon DEV_CHANNEL_ID du .env ;
#   - avec /test_partie pour générer de fausses fins de partie.
#
# Usage :  .\test-bot.ps1          (réutilise data\test s'il existe)
#          .\test-bot.ps1 -Reset   (repart d'une copie fraîche des vraies données)
param([switch]$Reset)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$data   = Join-Path $PSScriptRoot "data\test"

if (-not (Select-String -Path .env -Pattern '^DEV_CHANNEL_ID=\d+' -Quiet)) {
    Write-Error "Ajoute DEV_CHANNEL_ID=<id du salon de test> dans .env (le mode test ne poste jamais dans le vrai salon)."
}

if ($Reset -and (Test-Path $data)) { Remove-Item -Recurse -Force $data }
if (-not (Test-Path $data)) {
    New-Item -ItemType Directory -Force $data | Out-Null
    Copy-Item players.json $data
    if (Test-Path pompesbot.db) {
        # Sauvegarde SQLite : copie cohérente même si le bot de production tourne.
        & $python -c "import sqlite3, sys; s = sqlite3.connect('pompesbot.db'); d = sqlite3.connect(sys.argv[1]); s.backup(d)" (Join-Path $data "pompesbot.db")
    }
    Write-Host "Copie des données créée dans $data"
}

$env:POMPESBOT_DEV      = "1"
$env:POMPESBOT_DATA_DIR = $data
& $python main.py
