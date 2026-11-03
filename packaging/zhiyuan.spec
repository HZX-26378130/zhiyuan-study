# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（文件夹版，推荐）。

为什么用 onedir 而不是 onefile：
- onefile 每次启动都要把 ~35MB 解压到临时目录，冷启动 3-5 秒
- onefile 的"自解压"行为更容易被杀毒软件误判
- onedir 启动快、误报少，代价是「一个文件夹 + 里面的 exe」

产物：dist/知源学伴/知源学伴.exe
"""
import os

ROOT = os.path.dirname(SPECPATH)          # 项目根目录
FRONT = os.path.join(ROOT, 'frontend')
DATA = os.path.join(ROOT, 'data')

datas = [
    (FRONT, 'frontend'),
    (os.path.join(DATA, 'vocab'), 'data/vocab'),
    (os.path.join(DATA, 'knowledge'), 'data/knowledge'),
    (os.path.join(DATA, 'bank'), 'data/bank'),
    (os.path.join(DATA, 'rubrics'), 'data/rubrics'),
]

# 后端全部是标准库实现，没有需要隐藏导入的第三方包
hiddenimports = []

a = Analysis(
    [os.path.join(ROOT, 'packaging', 'run_exe.py')],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc_data', 'test'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='知源学伴',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,            # 保留控制台：显示数据目录、端口、错误，便于排障
    icon=os.path.join(ROOT, 'packaging', 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='知源学伴',
)
