# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec：打包后端为单 exe。

用法：
  pip install pyinstaller
  pyinstaller novel_agent.spec

产物：dist/novel-compose-server/novel-compose-server.exe
"""
import os
from pathlib import Path

block_cipher = None

# 数据文件：模板 + CSV 参考表 + 小说语料 + 写作风格指南
# config.yaml（含 api key）直接打包，让用户开箱即用
datas = [
    ('novel_agent/templates', 'novel_agent/templates'),
    ('novel_agent/references', 'novel_agent/references'),
    ('小说语料', '小说语料'),
    ('写作风格指南', '写作风格指南'),
    ('config.yaml', '.'),
    ('config.yaml.example', '.'),
]

# 隐藏导入：chromadb / sentence-transformers / langgraph 经常有动态导入
# 同时收集所有 novel_agent.* 子模块，因为 uvicorn.run("novel_agent.api.app:create_app")
# 用字符串导入，PyInstaller 静态分析检测不到
import pkgutil
import novel_agent

_novel_agent_modules = []
for m in pkgutil.walk_packages(novel_agent.__path__, 'novel_agent.'):
    _novel_agent_modules.append(m.name)

# chromadb 内部大量使用 importlib.import_module 动态加载子模块
# （telemetry.product.posthog、api、db 等），必须全量收集
_chromadb_modules = []
try:
    import chromadb
    for m in pkgutil.walk_packages(chromadb.__path__, 'chromadb.'):
        _chromadb_modules.append(m.name)
except Exception as _e:
    print(f"警告：无法遍历 chromadb 子模块: {_e}")

hiddenimports = [
    'sentence_transformers',
    'sentence_transformers.models',
    'langgraph',
    'langgraph.graph',
    'langgraph.checkpoint',
    'langgraph.checkpoint.sqlite',
    'langgraph.checkpoint.sqlite.jsonplus',
    'langgraph.checkpoint.sqlite.aio',
    'aiosqlite',
    'sse_starlette',
    'sse_starlette.sse',
    'slowapi',
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'sqlalchemy',
    'sqlalchemy.dialects.sqlite',
    'pymupdf',
    'fitz',
    'PIL',
    'PIL._tkinter_finder',
    'docx',
    'yaml',
    'dotenv',
] + _novel_agent_modules + _chromadb_modules

a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest', 'IPython', 'notebook'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='novel-compose-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='novel-compose-server',
)
