# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

project = Path(SPECPATH)

rapidocr_datas, rapidocr_binaries, rapidocr_hidden = collect_all('rapidocr_onnxruntime')
onnx_datas, onnx_binaries, onnx_hidden = collect_all('onnxruntime')
dxcam_datas, dxcam_binaries, dxcam_hidden = collect_all('dxcam')

a = Analysis(
    ['launcher.py'],
    pathex=[str(project)],
    binaries=rapidocr_binaries + onnx_binaries + dxcam_binaries,
    datas=[
        (str(project / 'templates'), 'templates'),
        (str(project / 'static'), 'static'),
    ] + rapidocr_datas + onnx_datas + dxcam_datas,
    hiddenimports=[
        'pyautogui',
        'PIL',
        'PIL.Image',
        'PIL.ImageChops',
        'flask',
        'rapidocr_onnxruntime',
        'onnxruntime',
        'numpy',
        'dxcam',
    ] + rapidocr_hidden + onnx_hidden + dxcam_hidden,
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
    [],
    exclude_binaries=True,
    name='tibia-mapper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='tibia-mapper',
)
