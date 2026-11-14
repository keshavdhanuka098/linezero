$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\backend")
if (-not (Test-Path .venv)) { py -3.11 -m venv .venv }
. .\.venv\Scripts\Activate.ps1
pip install -q -r requirements.txt
python -m app.core.init_db
if (-not (Test-Path data\seeded.flag)) { python -m app.seed.generate_demo_data --scenario all --customers 500 --seed 42 --reset; New-Item data\seeded.flag -ItemType File | Out-Null }
uvicorn app.main:app --host 127.0.0.1 --port 8000
