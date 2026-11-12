# -*- mode: python ; coding: utf-8 -*-
import re
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo

# app.py의 VERSION을 읽어 exe 파일 속성(자세히 탭)의 버전으로 넣는다
VERSION = re.search(r'^VERSION = "([\d.]+)"$', open('app.py', encoding='utf-8').read(), re.M).group(1)
numbers = tuple(int(part) for part in VERSION.split('.')) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo([StringTable('041204B0', [
            StringStruct('ProductName', 'Shorts Maker Pro'),
            StringStruct('FileDescription', 'Shorts Maker Pro'),
            StringStruct('FileVersion', VERSION),
            StringStruct('ProductVersion', VERSION),
            StringStruct('OriginalFilename', 'ShortMaker.exe'),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0412, 1200])]),
    ],
)


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=collect_data_files('sv_ttk'),
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
    [],
    exclude_binaries=True,
    name='ShortMaker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ShortMaker',
)
