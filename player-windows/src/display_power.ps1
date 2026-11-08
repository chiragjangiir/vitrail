# Vitrail player - video output power (non-controllable screen fallback).
# Called by main.js: powershell -ExecutionPolicy Bypass -File display_power.ps1 -Mode off|on
#
# OFF strategy (in order):
#   1. DDC/CI monitor standby (VCP 0xD6 = 4, fallback 5). The GPU KEEPS outputting a
#      signal; the monitor sleeps BY COMMAND -> wake is instant and always reversible.
#      This is the PC-monitor equivalent of HDMI-CEC (VESA MCCS over the video cable).
#   2. If DDC/CI unsupported: SC_MONITORPOWER broadcast (healthy GPU drivers only).
#      Exit code 10 tells main.js the SC fallback was used.
# ON: DDC/CI power on + SC_MONITORPOWER -1 + ChangeDisplaySettingsEx mode reset
#     + ES_DISPLAY_REQUIRED pulse + synthetic input (F15 + mouse jiggle).
#     Multiple levers because some drivers (e.g. Intel HD 6000) ignore part of them.
#
# ASCII only (PowerShell 5.1 reads this file as ANSI).
param([string]$Mode = "on")

$src = @"
using System;
using System.Runtime.InteropServices;
public class SFDP {
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int x; public int y; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct PHYSICAL_MONITOR { public IntPtr h; [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string d; }
  [DllImport("user32.dll")] public static extern IntPtr MonitorFromPoint(POINT pt, uint f);
  [DllImport("dxva2.dll")] public static extern bool GetNumberOfPhysicalMonitorsFromHMONITOR(IntPtr m, out uint n);
  [DllImport("dxva2.dll")] public static extern bool GetPhysicalMonitorsFromHMONITOR(IntPtr m, uint n, [Out] PHYSICAL_MONITOR[] a);
  [DllImport("dxva2.dll")] public static extern bool SetVCPFeature(IntPtr h, byte c, uint v);
  [DllImport("dxva2.dll")] public static extern bool DestroyPhysicalMonitor(IntPtr h);
  // SendNotifyMessageW: non-blocking broadcast. A plain SendMessage(HWND_BROADCAST) BLOCKS
  // until every top-level window answers -> hung 30s on the AOpen (a window stopped pumping
  // messages after the output cut) and the wake never ran (player log: ETIMEDOUT).
  [DllImport("user32.dll")] public static extern bool SendNotifyMessageW(IntPtr h, int m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, int f, int e);
  [DllImport("user32.dll")] public static extern void mouse_event(int f, int dx, int dy, int d, int e);
  [DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint f);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)]
  public static extern int ChangeDisplaySettingsExW(string dev, IntPtr mode, IntPtr hwnd, uint flags, IntPtr p);
  // Sets VCP 0xD6 (power mode) on every physical monitor of the primary HMONITOR.
  // Returns the number of monitors that accepted the command (-1 = enumeration failed).
  public static int VcpPower(uint val, uint alt) {
    POINT p; p.x = 0; p.y = 0;
    IntPtr hm = MonitorFromPoint(p, 1);
    uint n;
    if (!GetNumberOfPhysicalMonitorsFromHMONITOR(hm, out n) || n == 0) return -1;
    PHYSICAL_MONITOR[] a = new PHYSICAL_MONITOR[n];
    if (!GetPhysicalMonitorsFromHMONITOR(hm, n, a)) return -1;
    int ok = 0;
    for (int i = 0; i < n; i++) {
      bool r = SetVCPFeature(a[i].h, 0xD6, val);
      if (!r && alt != 0) r = SetVCPFeature(a[i].h, 0xD6, alt);
      if (r) ok++;
      DestroyPhysicalMonitor(a[i].h);
    }
    return ok;
  }
}
"@
Add-Type -TypeDefinition $src

if ($Mode -eq "off") {
    $n = [SFDP]::VcpPower(4, 5)
    if ($n -gt 0) { Write-Output "ddc-off:$n"; exit 0 }
    [SFDP]::SendNotifyMessageW([IntPtr]0xffff, 0x0112, [IntPtr]0xF170, [IntPtr]2) | Out-Null
    Write-Output "scmonitor-off"
    exit 10
} else {
    $ddc = [SFDP]::VcpPower(1, 0)
    [SFDP]::SendNotifyMessageW([IntPtr]0xffff, 0x0112, [IntPtr]0xF170, [IntPtr](-1)) | Out-Null
    # Force a mode-set from registry settings: re-engages the GPU output on drivers
    # where SC_MONITORPOWER -1 alone does nothing (rescue lever, harmless elsewhere).
    [SFDP]::ChangeDisplaySettingsExW($null, [IntPtr]::Zero, [IntPtr]::Zero, 0, [IntPtr]::Zero) | Out-Null
    [SFDP]::SetThreadExecutionState([uint32]2147483651) | Out-Null
    [SFDP]::keybd_event(126, 0, 0, 0); [SFDP]::keybd_event(126, 0, 2, 0)
    [SFDP]::mouse_event(1, 5, 5, 0, 0); [SFDP]::mouse_event(1, -5, -5, 0, 0)
    Start-Sleep -Milliseconds 500
    [SFDP]::SetThreadExecutionState([uint32]2147483648) | Out-Null
    Write-Output "on:ddc=$ddc"
    exit 0
}
