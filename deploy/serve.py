"""The deployed app: JADE's API with the built frontend served from the same origin.

Every API route lives under /api, so the UI is mounted at / after them and the browser never makes a
cross-origin request. Used by the Dockerfile; local development keeps `make api` and the Vite proxy.
"""

from pathlib import Path

from fastapi.staticfiles import StaticFiles

from tpa.api import app

UI = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app.mount("/", StaticFiles(directory=UI, html=True), name="ui")
