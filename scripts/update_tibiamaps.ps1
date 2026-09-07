param(
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$TargetRoot = Join-Path $ProjectRoot 'data\tibia-map-data'
$RepoUrl = 'https://github.com/tibiamaps/tibia-map-data.git'

function Assert-Git {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'Git no está instalado o no está disponible en PATH.'
    }
}

Assert-Git

if ($Force -and (Test-Path $TargetRoot)) {
    Write-Host "Eliminando cache local existente: $TargetRoot"
    Remove-Item -Recurse -Force $TargetRoot
}

if (-not (Test-Path (Join-Path $TargetRoot '.git'))) {
    if (Test-Path $TargetRoot) {
        throw "Existe $TargetRoot pero no es un repositorio Git. Usa -Force para recrearlo."
    }

    New-Item -ItemType Directory -Force -Path (Split-Path $TargetRoot -Parent) | Out-Null
    Write-Host 'Clonando tibiamaps/tibia-map-data...'
    git clone --depth 1 $RepoUrl $TargetRoot
    if ($LASTEXITCODE -ne 0) { throw 'git clone falló.' }
} else {
    Write-Host 'Actualizando tibia-map-data...'
    git -C $TargetRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'git pull falló.' }
}

$Bounds = Join-Path $TargetRoot 'data\bounds.json'
$Markers = Join-Path $TargetRoot 'data\markers.json'
$Floor7 = Join-Path $TargetRoot 'data\floor-07-map.png'
$Path7 = Join-Path $TargetRoot 'data\floor-07-pathfinding.png'

foreach ($Required in @($Bounds, $Markers, $Floor7, $Path7)) {
    if (-not (Test-Path $Required)) {
        throw "Descarga incompleta: falta $Required"
    }
}

Write-Host ''
Write-Host 'TibiaMaps local listo.'
Write-Host "Ruta: $TargetRoot"
Write-Host 'Prueba sugerida:'
Write-Host '  http://127.0.0.1:5000/api/map/position?x=31946&y=31900&z=7'
