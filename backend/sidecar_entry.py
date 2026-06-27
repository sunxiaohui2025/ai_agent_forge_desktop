"""Frozen-app entry point for the FastAPI backend.

PyInstaller bundles this into a single executable the Electron shell launches
as a sidecar. It reads the port from argv/env and starts uvicorn in-process
(no `python -m uvicorn` needed inside the frozen binary).
"""
from __future__ import annotations
import os
import sys


def main() -> None:
    # Port: --port N  | $H3C_BACKEND_PORT | default 47900
    port = 47900
    for i, a in enumerate(sys.argv):
        if a == "--port" and i + 1 < len(sys.argv):
            try:
                port = int(sys.argv[i + 1])
            except ValueError:
                pass
    port = int(os.environ.get("H3C_BACKEND_PORT", port))

    import uvicorn
    from app.main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
