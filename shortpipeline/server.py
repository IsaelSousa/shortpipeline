"""Painel web + API. Rode com: uv run shortpipeline  (abre em http://localhost:8765)."""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .providers import resolve_bin, ProviderError
from .routes import channels, integrations, jobs, timeline
from .routes.common import PORT
from .worker import worker

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
WEB_DIR = config.ROOT / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.load()
    task = asyncio.create_task(worker.loop())
    yield
    task.cancel()
    for t in list(worker.running.values()):
        t.cancel()


app = FastAPI(title="ShortPipeline", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
for _r in (channels, jobs, timeline, integrations):
    app.include_router(_r.router)


@app.get("/", response_class=HTMLResponse)
def index():
    return (WEB_DIR / "index.html").read_text()


# ------------------------------------------------------------------ meta
@app.get("/api/meta")
def meta():
    cli = {}
    for name in ("claude", "codex", "agy", "ffmpeg", "ffprobe"):
        try:
            cli[name] = resolve_bin(name)
        except ProviderError:
            cli[name] = None
    return {
        "stages": config.STAGES,
        "kind_stages": config.KIND_STAGES,
        "kind_labels": config.KIND_LABELS,
        "stage_labels": config.STAGE_LABELS,
        "review_after_stages": config.REVIEW_AFTER_STAGES,
        "model_stages": config.MODEL_STAGES,
        "provider_labels": config.PROVIDER_LABELS,
        "model_suggestions": config.MODEL_SUGGESTIONS,
        "fonts": sorted({p.stem.split("-")[0] for p in config.FONTS_DIR.glob("*.ttf")}),
        "effects": ["none", "terror", "vibrante"],
        "cli": cli,
        "paused": worker.paused,
    }


def main():
    import logging

    import uvicorn

    # avisos dos módulos (logging.getLogger(__name__)) saem no terminal
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("shortpipeline").setLevel(logging.INFO)
    print(f"ShortPipeline em http://localhost:{PORT}")
    uvicorn.run(app, host=os.environ.get("SHORTPIPELINE_HOST", "127.0.0.1"), port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
