# ===========================================================================
#  Vitrail — Demarrage dev local (Windows / Docker Desktop)
#  Usage    : .\demo-start.ps1
#  Options  : .\demo-start.ps1 -Quick    (DB + MinIO + Backend uniquement, pour les tests)
#             .\demo-start.ps1 -Full     (+ Mailpit)
#             .\demo-start.ps1 -Force    (recrée les containers)
# ===========================================================================

param(
    [switch]$Quick,
    [switch]$Full,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step { param($n, $msg) Write-Host "`n  [$n] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg)     Write-Host "      OK  $msg" -ForegroundColor Green }
function Write-Info { param($msg)     Write-Host "      ..  $msg" -ForegroundColor DarkGray }
function Write-Warn { param($msg)     Write-Host "      !!  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg)     Write-Host "`n      ERR $msg" -ForegroundColor Red; exit 1 }

function Get-PortProcess {
    param([int]$Port)
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if (-not $conn) { return $null }
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    return @{ Pid = $conn.OwningProcess; Name = if ($proc) { $proc.Name } else { "inconnu" } }
}

Clear-Host
Write-Host ""
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host "  |   Vitrail      --  Demarrage dev local          |" -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host ""

$mode = if ($Quick) { "RAPIDE (DB + MinIO + Backend)" } `
        elseif ($Full) { "COMPLET (+ Mailpit)" } `
        else { "STANDARD (Backend + Workers + Frontend)" }
Write-Host "  Mode : $mode" -ForegroundColor Yellow
if ($Force) { Write-Host "  Flag : -Force (recreation des containers)" -ForegroundColor Yellow }

# ===========================================================================
Write-Step 1 "Verification Docker Desktop"
# ===========================================================================

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Fail "Docker Desktop introuvable. Installez-le depuis https://docker.com/products/docker-desktop"
}

$savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
$dockerVersion = docker info --format "{{.ServerVersion}}" 2>$null
$ErrorActionPreference = $savedEap
if ($LASTEXITCODE -ne 0 -or -not $dockerVersion) {
    Write-Warn "Docker Desktop non demarre -- tentative de lancement automatique..."

    $ddPaths = @(
        "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
        "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
    )
    $ddExe = $ddPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $ddExe) { Write-Fail "Docker Desktop introuvable. Lancez-le manuellement puis relancez." }

    Write-Info "Nettoyage processus bloques..."
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    @("Docker Desktop.exe","com.docker.backend.exe","com.docker.build.exe","dockerd.exe") |
        ForEach-Object { taskkill /F /IM $_ /T 2>$null | Out-Null }
    wsl --shutdown 2>$null | Out-Null
    $ErrorActionPreference = $savedEap
    Start-Sleep -Seconds 2

    Write-Info "Lancement Docker Desktop..."
    Start-Process $ddExe

    $waited = 0
    while ($waited -lt 90) {
        Start-Sleep -Seconds 5; $waited += 5
        $savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
        $dockerVersion = docker info --format "{{.ServerVersion}}" 2>$null
        $ErrorActionPreference = $savedEap
        if ($LASTEXITCODE -eq 0 -and $dockerVersion) { break }
        Write-Info "Attente daemon Docker... ($waited s / 90s)"
    }
    if (-not $dockerVersion) { Write-Fail "Docker Desktop non demarre en 90s. Lancez-le manuellement." }
}
Write-OK "Docker $dockerVersion"

# ===========================================================================
Write-Step 2 "Verification configuration"
# ===========================================================================

if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Warn ".env cree depuis .env.example -- verifiez CMS_JWT_SECRET et les mots de passe"
    } else {
        Write-Fail ".env absent et .env.example introuvable."
    }
} else {
    $envContent = Get-Content ".env" -Raw
    if ($envContent -match "change-me-in-production|changeme") {
        Write-Warn ".env contient des valeurs template -- OK en dev local"
    } else {
        Write-OK ".env present"
    }
    if ($envContent -notmatch "MINIO_PUBLIC_ENDPOINT\s*=\s*\S") {
        Write-Warn "MINIO_PUBLIC_ENDPOINT absent du .env -- vignettes et lecture video seront cassees !"
        Write-Warn "Ajoutez : MINIO_PUBLIC_ENDPOINT=localhost:9000 (dev) ou IP_SERVEUR:9000 (prod)"
    }
}

$hasOverride = Test-Path "docker-compose.override.yml"
if ($hasOverride) {
    Write-OK "Override detecte (ports : postgres->5433, redis->6380, backend->8010)"
} else {
    Write-Warn "docker-compose.override.yml absent -- ports standard (5432/6379/8000)"
    Write-Warn "Si une autre stack tourne aussi, creer l'override pour eviter les conflits de ports."
}

# ===========================================================================
Write-Step 3 "Verification des ports"
# ===========================================================================

$dockerInternal = @("wslrelay","com.docker.backend","com.docker.build","docker-proxy","dockerd")

$portsToCheck = if ($hasOverride) {
    [ordered]@{ 5433 = "PostgreSQL"; 6380 = "Redis"; 9000 = "MinIO"; 9001 = "MinIO Console"; 8010 = "Backend API" }
} else {
    [ordered]@{ 5432 = "PostgreSQL"; 6379 = "Redis"; 9000 = "MinIO"; 9001 = "MinIO Console"; 8000 = "Backend API" }
}

foreach ($port in $portsToCheck.Keys) {
    $label = $portsToCheck[$port]
    $info = Get-PortProcess -Port $port
    if (-not $info) {
        Write-OK "Port $port ($label) libre"
    } elseif ($dockerInternal | Where-Object { $info.Name -match $_ }) {
        Write-Info "Port $port ($label) : $($info.Name) (infra Docker -- OK)"
    } else {
        Write-Warn "Port $port ($label) occupe par $($info.Name) (PID $($info.Pid))"
    }
}

# ===========================================================================
Write-Step 4 "Selection et demarrage des services"
# ===========================================================================

$baseServices   = @("postgres", "redis", "minio", "postgres-test-db", "backend")
$workerServices = @("celery-worker", "celery-media", "celery-beat", "frontend")
$extraServices  = @("mailpit")

$services = if ($Quick)  { $baseServices }
            elseif ($Full) { $baseServices + $workerServices + $extraServices }
            else { $baseServices + $workerServices }

Write-Info "Services : $($services -join ', ')"

$composeArgs = @("compose", "up", "-d")
if ($Force) { $composeArgs += "--force-recreate" }
$composeArgs += $services

Write-Host ""
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Fail "Echec docker compose up (code $LASTEXITCODE). Verifiez : docker compose logs --tail 30"
}

# Port effectif du backend (lit la redirection reelle)
$savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
$portMapping = docker compose port backend 8000 2>$null | Select-Object -First 1
$ErrorActionPreference = $savedEap
$backendPort = if ($portMapping -match ":(\d+)$") { [int]$Matches[1] } else { if ($hasOverride) { 8010 } else { 8000 } }

# ===========================================================================
Write-Step 5 "Attente du backend (max 60s)"
# ===========================================================================

$maxWait = 60; $elapsed = 0; $healthy = $false
while ($elapsed -lt $maxWait) {
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    $code = & "curl.exe" -s --output NUL -w "%{http_code}" --max-time 3 `
                "http://localhost:$backendPort/health" 2>$null
    $ErrorActionPreference = $savedEap
    if ($code -eq "200") { $healthy = $true; break }
    Write-Host "      [${elapsed}s] Backend en demarrage..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 5; $elapsed += 5
}

if ($healthy) { Write-OK "Backend healthy (http://localhost:$backendPort/health)" }
else          { Write-Warn "Backend non healthy apres ${elapsed}s -- verifiez : docker compose logs backend --tail 30" }

# ===========================================================================
Write-Step 6 "Migrations Alembic + bucket MinIO"
# ===========================================================================

if ($healthy) {
    Write-Info "Alembic upgrade head..."
    docker compose exec -T backend alembic upgrade head
    if ($LASTEXITCODE -eq 0) { Write-OK "Migrations appliquees" }
    else                     { Write-Warn "Alembic : code $LASTEXITCODE -- DB peut-etre deja a jour" }

    Write-Info "Creation bucket signflow-media..."
    docker compose exec -T backend python /app/scripts/create_bucket.py
    Write-OK "Bucket MinIO pret"
} else {
    Write-Warn "Backend non disponible -- lancez 'make dev-init' manuellement apres le demarrage."
}

# ===========================================================================
Write-Step 7 "Smoke test API"
# ===========================================================================

$fail = 0
function Test-Endpoint {
    param([string]$Label, [string]$Url, [int]$Expected)
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    $code = & "curl.exe" -s --output NUL -w "%{http_code}" --max-time 5 $Url 2>$null
    $code = if ($code -match '^\d+$') { [int]$code } else { 0 }
    $ErrorActionPreference = $savedEap
    if ($code -eq $Expected) { Write-OK "  $Label -> $code" }
    else { Write-Host "      FAIL  $Label -> $code (attendu $Expected)" -ForegroundColor Red; $script:fail++ }
}

if ($healthy) {
    $api = "http://localhost:$backendPort/api/v1"
    Test-Endpoint "GET /health"     "http://localhost:$backendPort/health" 200
    Test-Endpoint "GET /players"    "$api/players/"                         401
    Test-Endpoint "GET /media"      "$api/media/"                           401
    Test-Endpoint "GET /templates"  "$api/templates"                        401
    Test-Endpoint "GET /playlists"  "$api/playlists/"                       401
    Test-Endpoint "GET /schedules"  "$api/schedules"                        401

    Write-Host ""
    if ($fail -eq 0) { Write-OK "Smoke test : 6/6 OK" }
    else             { Write-Host "      $fail endpoint(s) en echec -- verifiez les routes" -ForegroundColor Red }
} else {
    Write-Warn "Backend non disponible -- smoke test ignore"
}

# ===========================================================================
Write-Step 8 "Statut des containers"
# ===========================================================================

Write-Host ""
docker compose ps --format "table {{.Name}}\t{{.Status}}" | ForEach-Object {
    if     ($_ -match "running.*healthy") { Write-Host "  $_" -ForegroundColor Green }
    elseif ($_ -match "starting|health")  { Write-Host "  $_" -ForegroundColor Yellow }
    elseif ($_ -match "Exited \(0\)")     { Write-Host "  $_" -ForegroundColor DarkGray }
    elseif ($_ -match "Exited|Error")     { Write-Host "  $_" -ForegroundColor Red }
    else                                  { Write-Host "  $_" -ForegroundColor White }
}

$mailpitPort  = if ($hasOverride) { 8026 } else { 8025 }
$frontendPort = if ($hasOverride) { 3010 } else { 3000 }

Write-Host ""
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host "   SIGNFLOW PRET -- Acces" -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host ""
Write-Host "   Backend API    : http://localhost:$backendPort" -ForegroundColor White
Write-Host "   API Docs       : http://localhost:$backendPort/api/docs" -ForegroundColor White
Write-Host "   MinIO Console  : http://localhost:9001  (minioadmin / minioadmin)" -ForegroundColor White
if (-not $Quick) {
    Write-Host "   Frontend       : http://localhost:$frontendPort" -ForegroundColor White
}
if ($Full) {
    Write-Host "   Mailpit        : http://localhost:$mailpitPort" -ForegroundColor White
}
Write-Host ""
Write-Host "   Tests          : make test" -ForegroundColor DarkGray
Write-Host "   Logs backend   : docker compose logs -f backend" -ForegroundColor DarkGray
Write-Host "   Arret          : .\demo-stop.ps1" -ForegroundColor DarkGray
Write-Host ""
