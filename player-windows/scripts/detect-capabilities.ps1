# Detection des capacites de decodage (Windows / D3D11) -> capabilities.json.
# Reprend la detection de install.ps1 (Win32_VideoController). Le player lit
# capabilities.json au boot et le remonte ; la commande 'detect_capabilities' (CMS)
# relance ce script.
#
# Usage : powershell -ExecutionPolicy Bypass -File detect-capabilities.ps1 [chemin\capabilities.json]
# Sans argument -> %APPDATA%\<package.json name>\capabilities.json (userData Electron).
# Override : $env:SF_HW_DECODE = auto|on|off
param([string]$OutPath = "")

$ErrorActionPreference = "SilentlyContinue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$playerDir = Split-Path -Parent $scriptDir

$sfHwDecode = $env:SF_HW_DECODE
if (-not $sfHwDecode) { $sfHwDecode = "auto" }

if (-not $OutPath) {
  $pkgName = "signflow-player-windows"
  try { $pkgName = (Get-Content (Join-Path $playerDir "package.json") -Raw | ConvertFrom-Json).name } catch {}
  $OutPath = Join-Path (Join-Path $env:APPDATA $pkgName) "capabilities.json"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutPath) | Out-Null

$gpuVendor = "unknown"; $gpuModel = ""; $compat = ""
try {
  $vc = Get-CimInstance Win32_VideoController -ErrorAction Stop | Select-Object -First 1
  if ($vc) {
    $gpuModel = "$($vc.Name)"
    $compat = "$($vc.AdapterCompatibility) $($vc.Name)"
    if ($compat -match "Intel") { $gpuVendor = "intel" }
    elseif ($compat -match "AMD|Advanced Micro|ATI|Radeon") { $gpuVendor = "amd" }
    elseif ($compat -match "NVIDIA|GeForce") { $gpuVendor = "nvidia" }
  }
} catch {}
# « Microsoft Basic Display Adapter » = pas de vrai pilote GPU -> pas de decodage HW.
$basic = ($gpuModel -match "Basic Display") -or ($compat -match "Microsoft Basic Display") -or ($gpuVendor -eq "unknown")
$hwMethod = "d3d11"; $hwActive = $true
if ($basic) { $hwMethod = "none"; $hwActive = $false }
if ($sfHwDecode -eq "off") { $hwMethod = "none"; $hwActive = $false }
if ($sfHwDecode -eq "on") { $hwMethod = "d3d11"; $hwActive = $true }

$caps = [ordered]@{
  gpu_vendor       = $gpuVendor
  gpu_model        = $gpuModel
  hw_decode        = $hwMethod
  hw_decode_active = $hwActive
  codecs           = @("h264", "hevc", "vp9")
  gl_backend       = "angle"
  sf_hw_decode     = $sfHwDecode
  chromium_flags   = @()
  detection_source = "manual"
  detected_at      = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}
[System.IO.File]::WriteAllText($OutPath, ($caps | ConvertTo-Json -Depth 4))
Write-Host "[detect] $OutPath -> $gpuVendor method=$hwMethod active=$hwActive"
