# signflow-ntp-apply.ps1 -- Configure Windows Time (w32time) for tight LAN NTP sync.
#
# Mirror of the Linux/RPi helper signflow-ntp-apply (chrony). Called by the player
# main.js when the CMS pushes an NTP role/server (LAN Sync relay designation).
# The player Scheduled Task runs with RunLevel Highest, so w32tm /config and the
# registry writes run elevated without a separate prompt (when the logon user is
# a local admin). ASCII only (PowerShell 5.1 reads non-ASCII as ANSI).
#
# Usage:
#   signflow-ntp-apply.ps1 <role> <server>
#     role=client server=<relay ip> : sync to the LAN relay (a Linux/RPi chrony
#                                      player), aggressive high-accuracy discipline.
#     role=none                      : revert to a sane standalone default.
#     role=server / other            : not applied (designate a Linux/RPi as relay).
#
# Default w32time on a workgroup PC polls every ~1024 s and slews slowly -> ~hundreds
# of ms residual, which breaks frame-accurate LAN switch (#2b). Pointing it at the
# relay with the SpecialInterval flag (0x8) + SpecialPollInterval=64 + frequent phase
# correction (Microsoft high-accuracy subset) brings it to a few tens of ms on LAN.
# If still insufficient, the fallback is Meinberg NTP (ntpd port, sub-ms) -- see EVOLUTIONS.

param(
  [string]$Role = "none",
  [string]$Server = ""
)

$ErrorActionPreference = "Continue"
$cfg = "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Config"
$ntp = "HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient"

function Set-Dword($path, $name, $val) {
  New-ItemProperty -Path $path -Name $name -Value $val -PropertyType DWord -Force | Out-Null
}

# Make sure the service is enabled and started before configuring it.
& sc.exe config w32time start= auto | Out-Null
Start-Service w32time -ErrorAction SilentlyContinue

if ($Role -eq "client" -and $Server -ne "") {
  # Manual peer = the LAN relay ; 0x8 = SpecialInterval -> use SpecialPollInterval.
  & w32tm /config /manualpeerlist:"$Server,0x8" /syncfromflags:manual /update | Out-Null

  # High-accuracy discipline (Microsoft recommended subset for sub-LAN sync).
  Set-Dword $ntp "Enabled" 1
  Set-Dword $ntp "SpecialPollInterval" 64       # poll the relay every 64 s
  Set-Dword $cfg "MinPollInterval" 6            # 2^6 = 64 s
  Set-Dword $cfg "MaxPollInterval" 6
  Set-Dword $cfg "UpdateInterval" 100           # correct the clock very often
  Set-Dword $cfg "FrequencyCorrectRate" 2
  Set-Dword $cfg "PollAdjustFactor" 5
  Set-Dword $cfg "MaxAllowedPhaseOffset" 1      # slew small offsets, step only big ones

  Restart-Service w32time -ErrorAction SilentlyContinue
  & w32tm /resync /rediscover | Out-Null
  Write-Output "ntp-apply: client -> $Server (SpecialPollInterval=64)"
}
elseif ($Role -eq "none") {
  # Revert to a sane standalone default (public pool, normal weekly poll).
  & w32tm /config /manualpeerlist:"time.windows.com,0x9" /syncfromflags:manual /update | Out-Null
  Set-Dword $ntp "SpecialPollInterval" 604800
  Restart-Service w32time -ErrorAction SilentlyContinue
  & w32tm /resync | Out-Null
  Write-Output "ntp-apply: reset to default"
}
else {
  Write-Output "ntp-apply: role=$Role not applied on Windows (designate a Linux/RPi player as NTP relay)"
}
