# -*- mode: python ; coding: utf-8 -*-
# Spec de PyInstaller para Dictador (menu bar app, sin ventana).
# Build:  ~/.dictador/venv/bin/pyinstaller Dictador.spec

block_cipher = None

hiddenimports = [
    "pynput.keyboard._darwin",
    "pynput.mouse._darwin",
    "pynput._util.darwin",
    "rumps",
    "AppKit",
    "Quartz",
    "ApplicationServices",
    "Cocoa",
    "sounddevice",
    "webrtcvad",
    "numpy",
    "yaml",
    "requests",
    "anthropic",
]

datas = [
    ("config.yaml", "."),
    (".env.example", "."),
]

a = Analysis(
    ["entry.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "tkinter"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dictador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # app de menu bar: sin consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="Dictador",
)

# .app bundle (LSUIElement para menu bar sin icono en Dock)
app = BUNDLE(
    coll,
    name="Dictador.app",
    plist={
        "CFBundleName": "Dictador",
        "CFBundleDisplayName": "Dictador",
        "CFBundleIdentifier": "com.eduardocrovetto.dictador",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,        # app de menu bar: sin Dock, sin menú principal
        "NSMicrophoneUsageDescription": "Dictador necesita el micrófono para transcribir tu voz.",
        "NSSpeechRecognitionUsageDescription": "Dictador transcribe localmente lo que dictas.",
    },
)