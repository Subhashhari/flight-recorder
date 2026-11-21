"""FastAPI app (bind to 127.0.0.1). Serves the built UI at / when UI_DIST is set, diff HTML at /diffs/."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from flightrec.api.routes import router
from flightrec.config import DOCS_DIR

app = FastAPI(title="Flight Recorder", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


if DOCS_DIR.exists():
    app.mount("/diffs", StaticFiles(directory=DOCS_DIR, html=True), name="diffs")

_ui = os.environ.get("UI_DIST")
if _ui and Path(_ui).exists():
    app.mount("/", StaticFiles(directory=_ui, html=True), name="ui")
