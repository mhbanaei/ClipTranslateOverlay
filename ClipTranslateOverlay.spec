# -*- mode: python ; coding: utf-8 -*-
# ساخت exe:  python -m PyInstaller --noconfirm ClipTranslateOverlay.spec
# نکته‌ی مهم: WebView2Loader.dll باید همراه exe بسته شود؛ بدون آن، wx از موتور IE استفاده
# می‌کند و ترجمه‌ی درون‌صفحه‌ای (RunScriptAsync) جواب نمی‌دهد.

import os

import wx

wx_dir = os.path.dirname(wx.__file__)

a = Analysis(
    ["ClipTranslateOverlay.py"],
    pathex=[],
    binaries=[(os.path.join(wx_dir, "WebView2Loader.dll"), ".")],
    datas=[("assets", "assets")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ClipTranslateOverlay",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/42logo.ico",
)
