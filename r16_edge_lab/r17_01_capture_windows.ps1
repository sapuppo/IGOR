# Read-only R17 observation. Requires Python 3 and network access to fapi.binance.com.
# Run from a checked-out copy of the r17-01-research branch.
$ErrorActionPreference = 'Stop'
$researchDir = $PSScriptRoot
$captureDir = Join-Path $env:LOCALAPPDATA 'IGOR\R17\captures'
$universeFile = Join-Path $researchDir 'R17_01_UNIVERSE.json'
$collectorFile = Join-Path $researchDir 'r17_forward_capture.py'

& py -3 $collectorFile collect --manifest $universeFile --out-dir $captureDir
if ($LASTEXITCODE -ne 0) { throw 'Falha na captura pública R17' }
& py -3 $collectorFile verify --out-dir $captureDir
if ($LASTEXITCODE -ne 0) { throw 'Falha na cadeia de hashes R17' }
