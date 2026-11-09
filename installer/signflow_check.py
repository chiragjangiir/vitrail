#!/usr/bin/env python3
"""SignFlow — Pré-vérification des capacités d'un player (§XXIX).

Script AUTONOME (stdlib uniquement, aucune dépendance pip) à lancer SUR une machine candidate
(Linux / Windows / Raspberry Pi / macOS) pour décider si elle peut faire tourner un player
SignFlow. Produit un rapport clair (console + JSON + HTML) avec un verdict :
  VALIDÉ · VALIDÉ AVEC RÉSERVES · NON VALIDÉ

Usage :
  python3 signflow_check.py --backend https://cms.example.com --profile fhd
  python3 signflow_check.py --profile 4k --json rapport.json --html rapport.html
  # Windows : signflow-check.exe --backend https://… (packagé PyInstaller)

Profils : fhd (1080p, défaut) · 4k (2160p, exige plus de CPU/RAM + décodage matériel).
Codes de sortie : 0 = VALIDÉ · 1 = VALIDÉ AVEC RÉSERVES · 2 = NON VALIDÉ.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time

PASS, WARN, FAIL, INFO = "PASS", "WARN", "FAIL", "INFO"

# Seuils par profil. hard=True → un FAIL rend la machine NON VALIDÉE.
REQUIREMENTS = {
    "fhd": {"cores": 2, "ram_gb": 2.0, "disk_gb": 8.0},
    "4k":  {"cores": 4, "ram_gb": 4.0, "disk_gb": 16.0},
}
SUPPORTED_OS = {"Linux", "Windows", "Darwin"}


def _run(cmd: list[str], timeout: int = 6) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except Exception:
        return ""


# ── Sondes système ────────────────────────────────────────────────────────────

def cpu_cores() -> int:
    return os.cpu_count() or 0


def ram_gb() -> float | None:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names \
                and "SC_PHYS_PAGES" in os.sysconf_names:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9, 1)
    except Exception:
        pass
    if platform.system() == "Windows":
        out = _run(["wmic", "ComputerSystem", "get", "TotalPhysicalMemory"])
        for tok in out.split():
            if tok.isdigit():
                return round(int(tok) / 1e9, 1)
    return None


def disk_free_gb(path: str | None = None) -> float | None:
    try:
        target = path or ("C:\\" if platform.system() == "Windows" else "/")
        return round(shutil.disk_usage(target).free / 1e9, 1)
    except Exception:
        return None


def screen_resolution() -> str | None:
    sysname = platform.system()
    try:
        if sysname == "Linux":
            for tool in (["wlr-randr"], ["xrandr"]):
                out = _run(tool)
                for line in out.splitlines():
                    line = line.strip()
                    if "current" in line and "x" in line:  # xrandr "1920 x 1080"
                        import re
                        m = re.search(r"(\d{3,5})\s*x\s*(\d{3,5})", line)
                        if m:
                            return f"{m.group(1)}x{m.group(2)}"
                    if "current" in line.lower() and "px" in line.lower():
                        import re
                        m = re.search(r"(\d{3,5})x(\d{3,5})", line)
                        if m:
                            return f"{m.group(1)}x{m.group(2)}"
        elif sysname == "Windows":
            out = _run(["wmic", "path", "Win32_VideoController", "get",
                        "CurrentHorizontalResolution,CurrentVerticalResolution"])
            nums = [int(t) for t in out.split() if t.isdigit()]
            if len(nums) >= 2:
                return f"{nums[0]}x{nums[1]}"
        elif sysname == "Darwin":
            out = _run(["system_profiler", "SPDisplaysDataType"])
            import re
            m = re.search(r"Resolution:\s*(\d+)\s*x\s*(\d+)", out)
            if m:
                return f"{m.group(1)}x{m.group(2)}"
    except Exception:
        pass
    return None


def hw_decode_hint() -> tuple[str, str]:
    """(status, detail) — présence d'un décodage vidéo matériel (best-effort)."""
    sysname = platform.system()
    try:
        if sysname == "Linux":
            if any(os.path.exists(p) for p in ("/dev/dri/renderD128", "/dev/dri/card0")):
                extra = ""
                if os.path.exists("/dev/video10") or os.path.exists("/dev/video11"):
                    extra = " (V4L2 M2M — RPi)"
                lspci = _run(["lspci"])
                if "VGA" in lspci or "3D" in lspci or "Display" in lspci:
                    extra += " GPU présent"
                return PASS, "/dev/dri présent" + extra
            return WARN, "aucun /dev/dri — décodage logiciel probable"
        if sysname == "Windows":
            out = _run(["wmic", "path", "Win32_VideoController", "get", "Name"])
            names = [x.strip() for x in out.splitlines()[1:] if x.strip()]
            if names:
                return PASS, "GPU : " + ", ".join(names[:2])
            return WARN, "GPU non détecté"
        if sysname == "Darwin":
            return INFO, "macOS — décodage VideoToolbox supposé présent"
    except Exception:
        pass
    return WARN, "indéterminé"


def ntp_sync() -> tuple[str, str]:
    sysname = platform.system()
    try:
        if sysname == "Linux":
            out = _run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"]) \
                or _run(["timedatectl"])
            if "yes" in out.lower() or "synchronized: yes" in out.lower():
                return PASS, "horloge synchronisée (NTP)"
            return WARN, "NTP non confirmé — la sync LAN inter-players l'exige"
        if sysname == "Windows":
            out = _run(["w32tm", "/query", "/status"])
            if "Source" in out:
                return PASS, "service de temps Windows actif"
            return WARN, "temps Windows non confirmé"
    except Exception:
        pass
    return INFO, "non vérifié"


def backend_reachability(url: str) -> list[tuple[str, str, str]]:
    """DNS + TCP + HTTP /health + latence. Renvoie une liste de (nom, status, detail)."""
    import urllib.parse
    import urllib.request
    res: list[tuple[str, str, str]] = []
    p = urllib.parse.urlparse(url)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)

    # DNS
    try:
        ip = socket.gethostbyname(host)
        res.append(("Résolution DNS", PASS, f"{host} → {ip}"))
    except Exception as e:
        res.append(("Résolution DNS", FAIL, f"échec : {e}"))
        return res
    # TCP
    try:
        t0 = time.time()
        with socket.create_connection((host, port), timeout=6):
            ms = int((time.time() - t0) * 1000)
        res.append(("Connexion TCP", PASS, f"{host}:{port} ({ms} ms)"))
    except Exception as e:
        res.append(("Connexion TCP", FAIL, f"{host}:{port} injoignable : {e}"))
        return res
    # HTTP /health
    try:
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        t0 = time.time()
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=8, context=ctx) as r:
            ms = int((time.time() - t0) * 1000)
            code = r.status
        st = PASS if code == 200 else WARN
        res.append(("Backend /health", st, f"HTTP {code} ({ms} ms)"))
    except Exception as e:
        res.append(("Backend /health", WARN, f"non joignable : {e}"))
    return res


# ── Orchestration ──────────────────────────────────────────────────────────────

def build_report(profile: str, backend: str | None) -> dict:
    req = REQUIREMENTS[profile]
    checks: list[dict] = []

    def add(name, status, detail, value=None, hard=False):
        checks.append({"name": name, "status": status, "detail": detail,
                       "value": value, "hard": hard})

    sysname = platform.system()
    arch = platform.machine()
    add("Système d'exploitation",
        PASS if sysname in SUPPORTED_OS else FAIL,
        f"{sysname} {platform.release()} ({arch})", f"{sysname}/{arch}", hard=True)

    cores = cpu_cores()
    add("Cœurs CPU", PASS if cores >= req["cores"] else FAIL,
        f"{cores} (min {req['cores']})", cores, hard=True)

    ram = ram_gb()
    if ram is None:
        add("Mémoire RAM", WARN, "indéterminée", None)
    else:
        add("Mémoire RAM", PASS if ram >= req["ram_gb"] else FAIL,
            f"{ram} Go (min {req['ram_gb']} Go)", ram, hard=True)

    disk = disk_free_gb()
    if disk is None:
        add("Espace disque libre", WARN, "indéterminé", None)
    else:
        add("Espace disque libre", PASS if disk >= req["disk_gb"] else FAIL,
            f"{disk} Go libre (min {req['disk_gb']} Go)", disk, hard=True)

    reso = screen_resolution()
    if reso:
        w = int(reso.split("x")[0]) if "x" in reso else 0
        need = 3840 if profile == "4k" else 1920
        add("Résolution écran", PASS if w >= need else WARN,
            f"{reso} (cible {need}px de large)", reso)
    else:
        add("Résolution écran", INFO, "non détectée (écran branché ?)", None)

    st, detail = hw_decode_hint()
    # En 4K, l'absence de décodage matériel est bloquante-mou (WARN fort) ; en FHD, info.
    add("Décodage vidéo matériel",
        st if profile != "4k" else (st if st == PASS else WARN), detail)

    st, detail = ntp_sync()
    add("Synchronisation horloge (NTP)", st, detail)

    if backend:
        for name, status, detail in backend_reachability(backend):
            add(name, status, detail)

    hard_fail = any(c["status"] == FAIL and c["hard"] for c in checks)
    any_fail = any(c["status"] == FAIL for c in checks)
    any_warn = any(c["status"] == WARN for c in checks)
    if hard_fail or any_fail:
        verdict, code = "NON VALIDÉ", 2
    elif any_warn:
        verdict, code = "VALIDÉ AVEC RÉSERVES", 1
    else:
        verdict, code = "VALIDÉ", 0

    return {
        "tool": "signflow-check", "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hostname": platform.node(), "profile": profile,
        "verdict": verdict, "exit_code": code, "checks": checks,
    }


# ── Rendu ──────────────────────────────────────────────────────────────────────

_C = {PASS: "\033[32m", WARN: "\033[33m", FAIL: "\033[31m", INFO: "\033[36m"}
_R = "\033[0m"
_ICON = {PASS: "OK ", WARN: "!! ", FAIL: "XX ", INFO: ".. "}


def print_console(rep: dict) -> None:
    color = sys.stdout.isatty()
    print(f"\n  Vitrail — Vérification de capacités  ·  {rep['hostname']}  ·  "
          f"profil {rep['profile']}")
    print("  " + "-" * 62)
    for c in rep["checks"]:
        ico = _ICON[c["status"]]
        line = f"  {ico}{c['name']:<32} {c['detail']}"
        if color and c["status"] in _C:
            line = f"  {_C[c['status']]}{ico}{_R}{c['name']:<32} {c['detail']}"
        print(line)
    print("  " + "-" * 62)
    v = rep["verdict"]
    vc = {"VALIDÉ": PASS, "VALIDÉ AVEC RÉSERVES": WARN, "NON VALIDÉ": FAIL}[v]
    tag = f"  VERDICT : {v}"
    print(f"{_C[vc]}{tag}{_R}\n" if color else f"{tag}\n")


def html_report(rep: dict) -> str:
    rows = ""
    palette = {PASS: "#2E7D32", WARN: "#E65100", FAIL: "#C62828", INFO: "#1565C0"}
    for c in rep["checks"]:
        col = palette[c["status"]]
        rows += (f"<tr><td><b style='color:{col}'>{c['status']}</b></td>"
                 f"<td>{c['name']}</td><td>{c['detail']}</td></tr>")
    vcol = {"VALIDÉ": "#2E7D32", "VALIDÉ AVEC RÉSERVES": "#E65100",
            "NON VALIDÉ": "#C62828"}[rep["verdict"]]
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Vitrail — Capacités {rep['hostname']}</title>
<style>body{{font-family:Inter,system-ui,sans-serif;color:#1C1E2A;background:#F8F7F5;
padding:28px;max-width:760px;margin:auto}}h1{{font-size:18px}}table{{width:100%;
border-collapse:collapse;background:#fff;border:1px solid #e5e7eb;border-radius:8px;
overflow:hidden}}td{{padding:8px 12px;border-bottom:1px solid #f1f1f1;font-size:14px}}
.verdict{{margin-top:16px;padding:12px 16px;border-radius:8px;color:#fff;font-weight:600;
background:{vcol}}}small{{color:#6b7280}}</style></head><body>
<h1>Vitrail — Vérification de capacités</h1>
<small>{rep['hostname']} · profil {rep['profile']} · {rep['generated_at']}</small>
<table>{rows}</table>
<div class="verdict">VERDICT : {rep['verdict']}</div>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(prog="signflow-check",
                                 description="Vérifie qu'une machine peut faire tourner SignFlow.")
    ap.add_argument("--backend", help="URL du CMS à tester (réseau/latence)")
    ap.add_argument("--profile", choices=["fhd", "4k"], default="fhd")
    ap.add_argument("--json", help="Écrit le rapport JSON dans ce fichier")
    ap.add_argument("--html", help="Écrit un rapport HTML dans ce fichier")
    ap.add_argument("--quiet", action="store_true", help="Pas de sortie console")
    args = ap.parse_args(argv)

    rep = build_report(args.profile, args.backend)
    if not args.quiet:
        print_console(rep)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        if not args.quiet:
            print(f"  → JSON écrit : {args.json}")
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(html_report(rep))
        if not args.quiet:
            print(f"  → HTML écrit : {args.html}")
    return rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
