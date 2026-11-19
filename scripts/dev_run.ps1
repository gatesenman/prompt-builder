$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
Set-Location $Root
python -m pip install -q -r requirements.txt
python run.py
