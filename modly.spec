# modly.spec
# Build single-file GUI app; include resources folder
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None
datas = collect_data_files('modly', includes=['resources/*'])

a = Analysis(
    ['Sims4Modly.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Sims4Modly',
    console=False,              # <- NO console window
    debug=False,
    strip=False,
    upx=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Sims4Modly'
)
