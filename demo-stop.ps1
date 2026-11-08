# ===========================================================================
#  SignFlow CMS — Arret propre des services dev local
#  Usage    : .\demo-stop.ps1
#  Options  : .\demo-stop.ps1 -Volumes     (supprime aussi les volumes Docker)
#             .\demo-stop.ps1 -Prune        (nettoie images/reseaux orphelins)
#             .\demo-stop.ps1 -StopDocker   (ferme aussi Docker Desktop + WSL2)
# ===========================================================================

param(
    [switch]$Volumes,
    [switch]$Prune,
    [switch]$StopDocker
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

function Write-Step { param($n, $msg) Write-Host "  [$n] $msg" -ForegroundColor Cyan }
function Write-OK   { param($msg)     Write-Host "      OK  $msg" -ForegroundColor Green }
function Write-Info { param($msg)     Write-Host "      ..  $msg" -ForegroundColor DarkGray }
function Write-Warn { param($msg)     Write-Host "      !!  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg)     Write-Host "      ERR $msg" -ForegroundColor Red; exit 1 }

Clear-Host
Write-Host ""
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host "  |   SignFlow CMS  --  Arret dev local              |" -ForegroundColor Cyan
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host ""

if ($Volumes) {
    Write-Host "  ATTENTION : mode -Volumes -- les donnees PostgreSQL et MinIO seront supprimees !" -ForegroundColor Red
    Write-Host ""
    $confirm = Read-Host "  Tapez OUI pour confirmer"
    if ($confirm -ne "OUI") { Write-Host "  Annule." -ForegroundColor Yellow; exit 0 }
}

# -- 1. Verification Docker --------------------------------------------------
Write-Step 1 "Verification Docker"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Fail "Docker Desktop introuvable." }
$savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
$dockerRunning = docker info --format "{{.ServerVersion}}" 2>$null
$ErrorActionPreference = $savedEap
if (-not $dockerRunning) { Write-Fail "Docker Desktop n'est pas demarre." }
Write-OK "Docker $dockerRunning"

# -- 2. Arret des containers ------------------------------------------------
Write-Step 2 "Arret des containers SignFlow"

$composeArgs = @("compose", "down")
if ($Volumes) {
    $composeArgs += "-v"
    Write-Info "docker compose down -v (volumes supprimes)"
} else {
    Write-Info "docker compose down (volumes conserves)"
}

Write-Host ""
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Arret code $LASTEXITCODE (peut etre normal si deja arrete)"
} else {
    Write-OK "Containers arretes"
}

# -- 3. Nettoyage optionnel -------------------------------------------------
if ($Prune) {
    Write-Host ""
    Write-Step 3 "Nettoyage Docker (images/reseaux orphelins)"
    docker system prune -f
    Write-OK "Nettoyage termine"
}

# -- 4. Verification --------------------------------------------------------
Write-Host ""
Write-Step 4 "Verification -- containers SignFlow restants"
Write-Host ""

$savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
$remaining = docker compose ps --filter "status=running" --format "{{.Name}}" 2>$null
$ErrorActionPreference = $savedEap
if ($remaining) {
    Write-Warn "Ces containers sont encore actifs :"
    $remaining | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
} else {
    Write-OK "Aucun container SignFlow actif"
}

# -- 5. Arret Docker Desktop (optionnel) ------------------------------------
if ($StopDocker) {
    Write-Host ""
    Write-Step 5 "Arret de Docker Desktop et WSL2"
    $savedEap = $ErrorActionPreference; $ErrorActionPreference = "SilentlyContinue"
    @("Docker Desktop.exe","com.docker.backend.exe","com.docker.build.exe",
      "docker-sandbox.exe","docker-agent.exe","dockerd.exe") |
        ForEach-Object { taskkill /F /IM $_ /T 2>$null | Out-Null }
    $ErrorActionPreference = $savedEap
    Start-Sleep -Seconds 2
    wsl --shutdown
    Write-OK "Docker Desktop et WSL2 arretes"
}

# -- Resume -----------------------------------------------------------------
Write-Host ""
Write-Host "  =====================================================" -ForegroundColor DarkCyan
if ($Volumes) {
    Write-Host "   ARRET COMPLET -- donnees supprimees" -ForegroundColor Red
    Write-Host "   Note : la BDD sera reinitialisee au prochain demarrage" -ForegroundColor DarkGray
} else {
    Write-Host "   ARRET PROPRE -- donnees conservees" -ForegroundColor Green
}
Write-Host "   Relance : .\demo-start.ps1" -ForegroundColor DarkGray
Write-Host "  =====================================================" -ForegroundColor DarkCyan
Write-Host ""
