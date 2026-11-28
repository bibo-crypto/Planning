# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

analysis = Analysis(
    ['updater_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules('encodings'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook.py'],
    excludes=['tkinter', 'pandas', 'numpy', 'openpyxl'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='PlanningUpdater', console=False, debug=False, strip=False, upx=False,
    icon='icon.ico',
)
