# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the H3C Agent backend sidecar.
# Build:  pyinstaller sidecar.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Packages that ship data files / use dynamic imports — pull everything.
for pkg in (
    "uvicorn", "fastapi", "starlette", "pydantic", "pydantic_settings",
    "anyio", "click", "h11", "sqlalchemy", "aiosqlite", "claude_agent_sdk",
    "openai", "cryptography", "passlib", "jose", "jwt", "yaml", "httpx",
    "aiofiles", "pypdf", "docx", "openpyxl", "bs4", "Crypto",
    # Conditional / transitive deps that PyInstaller static analysis misses:
    "python_multipart",   # starlette → formparsers.py (try/except)
    "multipart",          # alternate import name (some starlette versions)
    "et_xmlfile",         # openpyxl → xmlfile writer
    "lxml",               # python-docx → oxml
    "soupsieve",          # beautifulsoup4 → CSS selectors
):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception:
        pass

# uvicorn's protocol/loop implementations are imported by string name.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "app.main",
]

# Bundle our own app package source explicitly.
datas += [("app", "app")]

# Bundle the built-in experts so a fresh install ships with them. Lands at the
# PyInstaller root as builtin_agents.json and is consumed on first boot by
# app.main._seed_builtin_agents (bindings resolved by stable code). Optional —
# absent in the public repo build, which then ships only the bare default agent.
import os as _os
_agents_json = _os.path.join("builtin_agents.json")
if _os.path.isfile(_agents_json):
    datas += [(_agents_json, ".")]

# Bundle the built-in Skill packages so a fresh install ships with them. They
# land under _internal/skills/ and are copied to DATA_DIR/skills on first boot
# (see app.main._seed_builtin_skills). Skip the dotfiles git/Finder leave behind.
_skills_src = _os.path.join("..", "storage", "skills")
if _os.path.isdir(_skills_src):
    for _name in _os.listdir(_skills_src):
        _p = _os.path.join(_skills_src, _name)
        if _name.startswith(".") or not _os.path.isdir(_p):
            continue
        datas += [(_p, _os.path.join("skills", _name))]

a = Analysis(
    ["sidecar_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="h3c-agent-backend",
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="h3c-agent-backend",
)
