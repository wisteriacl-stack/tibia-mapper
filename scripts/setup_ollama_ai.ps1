$ErrorActionPreference = 'Stop'

$Model = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { 'qwen2.5:3b' }
$BaseUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL.TrimEnd('/') } else { 'http://127.0.0.1:11434' }
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

Write-Host "Configurando IA local gratuita con Ollama + $Model"

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw 'No se encontro Ollama ni winget. Instala Ollama para Windows y vuelve a ejecutar este script.'
    }

    Write-Host 'Ollama no esta instalado. Instalando con winget...'
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements

    $possiblePaths = @(
        "$env:LOCALAPPDATA\Programs\Ollama",
        "$env:ProgramFiles\Ollama"
    )
    foreach ($path in $possiblePaths) {
        if (Test-Path "$path\ollama.exe") {
            $env:Path = "$path;$env:Path"
            break
        }
    }
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'Ollama se instalo, pero ollama.exe aun no aparece en PATH. Cierra PowerShell, abre uno nuevo y ejecuta otra vez el script.'
}

$ready = $false
try {
    Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 2 | Out-Null
    $ready = $true
} catch {}

if (-not $ready) {
    Write-Host 'Iniciando servidor Ollama...'
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Hidden
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            Invoke-RestMethod -Uri "$BaseUrl/api/tags" -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch {}
    }
}

if (-not $ready) {
    throw "Ollama no respondio en $BaseUrl"
}

Write-Host "Descargando modelo $Model..."
ollama pull $Model

Write-Host 'Probando modelo...'
$body = @{
    model = $Model
    stream = $false
    format = 'json'
    messages = @(
        @{ role = 'user'; content = 'Responde solo JSON: {"ok": true}' }
    )
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/chat" -ContentType 'application/json' -Body $body -TimeoutSec 60
Write-Host "Ollama listo. Modelo: $Model"
Write-Host "Respuesta de prueba: $($response.message.content)"

Write-Host ''
Write-Host 'Preparando cache local de TibiaMaps...'
& (Join-Path $PSScriptRoot 'update_tibiamaps.ps1')

Write-Host ''
Write-Host 'IA y TibiaMaps local listos.'
Write-Host 'Ahora ejecuta:'
Write-Host '  python app.py'
Write-Host 'y abre http://127.0.0.1:5000'
Write-Host 'Prueba mapa:'
Write-Host '  http://127.0.0.1:5000/api/map/position?x=31946&y=31900&z=7'
