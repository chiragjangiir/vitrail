# -*- mode: python ; coding: utf-8 -*-
# Spec PyInstaller pour l'installeur terrain SignFlow (§XXIX) -> signflow-provision.exe (onefile).
#
# Build (Windows, avec pywinrm installé pour le canal WinRM) :
#   pip install -r requirements.txt pyinstaller
#   pyinstaller --clean signflow-provision.spec
#   -> dist/signflow-provision.exe
#
# Le driver Windows importe `winrm` de façon PARESSEUSE (pour ne pas imposer pywinrm aux autres
# OS) -> PyInstaller ne le voit pas par analyse statique. On force donc la collecte de toute la
# chaîne WinRM (winrm + requests_ntlm + spnego + xmltodict + requests) en hidden imports.

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for _pkg in ("winrm", "requests_ntlm", "spnego", "xmltodict", "requests"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:  # paquet absent au build (ex. pas de pywinrm) -> exe sans canal WinRM
        pass

a = Analysis(
    ["signflow-provision.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PySide2", "matplotlib", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="signflow-provision",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
