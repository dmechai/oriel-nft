from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from . import service
from .settings import ROOT, VERSION

@asynccontextmanager
async def lifespan(app):
    service.db.run("UPDATE jobs SET status='error', message='服务已重启，请重新运行任务' WHERE status IN ('queued','running')")
    yield


app = FastAPI(title="Oriel NFT", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")

DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")
else:
    @app.get("/")
    def missing_frontend() -> HTMLResponse:
        return HTMLResponse(
            """<!doctype html><meta charset="utf-8"><title>Oriel NFT</title>
            <p>界面还没有构建。在项目目录运行 <code>cd web && npm install && npm run build</code> 后重启。</p>"""
        )


def cli() -> None:
    import os
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host=os.environ.get("ORIEL_HOST", "127.0.0.1"),
        port=int(os.environ.get("ORIEL_PORT", "8787")),
        reload=False,
    )
