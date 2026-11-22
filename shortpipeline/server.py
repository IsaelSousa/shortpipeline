"""Painel web + API. Rode com: uv run shortpipeline  (abre em http://localhost:8765)."""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, upload
from .providers import resolve_bin, ProviderError
from .worker import worker

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")
WEB_DIR = config.ROOT / "web"
PORT = int(os.environ.get("SHORTPIPELINE_PORT", "8765"))


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
        "model_stages": config.MODEL_STAGES,
        "provider_labels": config.PROVIDER_LABELS,
        "model_suggestions": config.MODEL_SUGGESTIONS,
        "fonts": sorted({p.stem.split("-")[0] for p in config.FONTS_DIR.glob("*.ttf")}),
        "effects": ["none", "terror", "vibrante"],
        "cli": cli,
        "paused": worker.paused,
    }


# ------------------------------------------------------------------ config
@app.get("/api/config")
def get_config():
    return config.load()


@app.put("/api/config")
def put_config(cfg: dict = Body(...)):
    if "channels" not in cfg or "general" not in cfg:
        raise HTTPException(400, "Config inválida")
    config.save(cfg)
    worker.wake()
    return config.load()


@app.post("/api/channels")
def add_channel(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    cid = re.sub(r"[^a-z0-9]+", "", name.lower())
    if not cid:
        raise HTTPException(400, "Nome inválido")
    cfg = config.load()
    if cid in cfg["channels"]:
        raise HTTPException(409, "Canal já existe")
    cfg["channels"][cid] = config.new_channel_config(name)
    config.save(cfg)
    (config.MUSIC_DIR / cid).mkdir(parents=True, exist_ok=True)
    return {"id": cid}


@app.delete("/api/channels/{cid}")
def delete_channel(cid: str):
    cfg = config.load()
    cfg["channels"].pop(cid, None)
    config.save(cfg)
    return {"ok": True}


@app.post("/api/config/reset-prompt/{cid}/{key}")
def reset_prompt(cid: str, key: str):
    defaults = config.channel_defaults(cid, config.load()["channels"].get(cid))
    return {"value": defaults["prompts"].get(key, "")}


# ------------------------------------------------------------------ jobs
def _public(job: dict) -> dict:
    job = dict(job)
    job["running_now"] = job["id"] in worker.running
    return job


@app.get("/api/jobs")
def jobs(channel: str | None = None, kind: str | None = None, limit: int = 100):
    return {"jobs": [_public(j) for j in db.list_jobs(channel, limit, kind)], "stats": db.stats(),
            "paused": worker.paused, "running": list(worker.running)}


@app.post("/api/uploads")
async def upload_file(file: UploadFile = File(...)):
    """Recebe um vídeo longo para cortes. Grava em disco em pedaços (arquivos grandes)."""
    import uuid

    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"):
        raise HTTPException(400, f"Formato não suportado: {ext}")
    dest_dir = config.DATA_DIR / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{uuid.uuid4().hex}{ext}"
    size = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(8 * 1024 * 1024):
            out.write(chunk)
            size += len(chunk)
    return {"id": dest.name, "name": file.filename, "size": size}


@app.post("/api/jobs")
def create_jobs(body: dict = Body(...)):
    cfg = config.load()
    cid = body.get("channel")
    if cid not in cfg["channels"]:
        raise HTTPException(400, "Canal desconhecido")
    kind = body.get("kind") or "short"
    created = []
    if kind == "cortes":
        url = (body.get("url") or "").strip()
        upload_id = body.get("upload_id")
        if not url and not upload_id:
            raise HTTPException(400, "Informe um link ou envie um arquivo")
        if upload_id:
            path = (config.DATA_DIR / "uploads" / Path(upload_id).name)
            if not path.exists():
                raise HTTPException(400, "Arquivo enviado não encontrado")
            inp = {"file": str(path), "name": body.get("file_name") or path.name}
        else:
            inp = {"url": url}
        clip_opts = {k: body[k] for k in ("count", "min_seconds", "max_seconds") if body.get(k)}
        job = db.create_job(cid, url or inp.get("name"), kind="fonte",
                            data={"input": inp, "clip_opts": clip_opts, "instructions": body.get("instructions") or ""})
        db.log(job["id"], "Fonte de cortes criada pelo painel")
        created.append(job["id"])
    elif kind in ("short", "long"):
        count = max(1, min(20, int(body.get("count") or 1)))
        topic = (body.get("topic") or "").strip() or None
        data = {"long_minutes": float(body["minutes"])} if kind == "long" and body.get("minutes") else {}
        for _ in range(count):
            job = db.create_job(cid, topic, kind=kind, data=data)
            db.log(job["id"], f"{config.KIND_LABELS[kind]} criado pelo painel" + (" com pauta manual" if topic else ""))
            created.append(job["id"])
    else:
        raise HTTPException(400, "Tipo inválido")
    worker.wake()
    return {"created": created}


def _job_or_404(job_id: str) -> dict:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str, after: int = 0):
    job = _job_or_404(job_id)
    out = {"job": _public(job), "logs": db.get_logs(job_id, after)}
    if job["kind"] == "fonte":
        out["children"] = [_public(c) for c in db.list_children(job_id)]
    if job.get("parent_id"):
        parent = db.get_job(job["parent_id"])
        out["parent"] = {"id": parent["id"], "topic": parent["topic"]} if parent else None
    return out


@app.get("/api/jobs/{job_id}/transcript")
def job_transcript(job_id: str):
    from .providers.transcribe import transcript_lines
    path = config.JOBS_DIR / job_id / "transcript.json"
    if not path.exists():
        raise HTTPException(404, "Sem transcrição")
    import json as _json
    tr = _json.loads(path.read_text())
    return {"lines": transcript_lines(tr["words"]), "provider": tr.get("provider"), "language": tr.get("language")}


@app.put("/api/jobs/{job_id}/clip")
async def edit_clip(job_id: str, body: dict = Body(...)):
    """Muda o início/fim de um corte e refaz a partir do recorte."""
    import json as _json
    from .pipeline import clip_words
    job = _job_or_404(job_id)
    if job["kind"] != "corte":
        raise HTTPException(400, "Não é um corte")
    start, end = float(body["start"]), float(body["end"])
    if end - start < 3:
        raise HTTPException(400, "Corte curto demais")
    tr_path = config.JOBS_DIR / job["data"]["source_job"] / "transcript.json"
    words = _json.loads(tr_path.read_text())["words"] if tr_path.exists() else []
    await worker.stop(job_id)
    clip = {**job["data"]["clip"], "start": round(start, 2), "end": round(end, 2)}
    db.update_job(job_id, data={"clip": clip, "words": clip_words(words, start, end), "approved": False})
    for p in (config.JOBS_DIR / job_id / "cover").glob("bg.*"):
        p.unlink()
    db.reset_from(job_id, "recorte")
    db.log(job_id, f"Corte ajustado para {start:.1f}s – {end:.1f}s")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/approve")
def approve(job_id: str, body: dict = Body(default={})):
    job = _job_or_404(job_id)
    data = {"approved": True}
    if body.get("upload_mode") in ("auto", "manual", "draft"):
        data["upload_mode_override"] = body["upload_mode"]
    if body.get("publish_at"):
        data["publish_at"] = body["publish_at"]
    if body.get("title") or body.get("description"):
        script = job["data"].get("script") or {}
        script.update({k: body[k] for k in ("title", "description") if body.get(k)})
        data["script"] = script
    db.update_job(job_id, data=data, status="queued")
    db.log(job_id, "Aprovado no painel", stage="revisao")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/publish")
def publish_now(job_id: str, body: dict = Body(default={})):
    """Envia para o YouTube um job que terminou em modo manual."""
    _job_or_404(job_id)
    mode = "draft" if body.get("draft") else "auto"
    db.update_job(job_id, data={"upload_mode_override": mode, "approved": True,
                                **({"publish_at": body["publish_at"]} if body.get("publish_at") else {})})
    db.reset_from(job_id, "upload")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/reject")
async def reject(job_id: str):
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, status="canceled", error="Rejeitado na revisão")
    db.log(job_id, "Rejeitado na revisão", "warn", "revisao")
    return {"ok": True}


@app.post("/api/jobs/{job_id}/retry")
async def retry(job_id: str, body: dict = Body(default={})):
    job = _job_or_404(job_id)
    stage = body.get("from_stage")
    order = config.stages_for(job["kind"])
    if not stage:  # primeira etapa que não terminou
        stage = next((s for s in order if job["stages"][s].get("status") != "done"), order[0])
    if stage not in order:
        raise HTTPException(400, "Etapa inválida")
    await worker.stop(job_id)
    job_dir = config.JOBS_DIR / job_id
    if stage == "imagens" and body.get("regenerate_images", True):
        shutil.rmtree(job_dir / "images", ignore_errors=True)
    if "revisao" in order and order.index(stage) <= order.index("revisao"):
        db.update_job(job_id, data={"approved": False})
    db.reset_from(job_id, stage)
    db.log(job_id, f"Refazendo a partir de: {config.STAGE_LABELS[stage]}")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/regenerate-image/{index}")
async def regenerate_image(job_id: str, index: int, body: dict = Body(default={})):
    job = _job_or_404(job_id)
    await worker.stop(job_id)
    idir = config.JOBS_DIR / job_id / "images"
    for p in idir.glob(f"{index:02d}.*"):
        p.unlink()
    if body.get("image_prompt"):
        script = job["data"]["script"]
        script["scenes"][index]["image_prompt"] = body["image_prompt"]
        db.update_job(job_id, data={"script": script})
    db.update_job(job_id, data={"approved": False})
    db.reset_from(job_id, "imagens")
    db.log(job_id, f"Regerando imagem {index + 1}")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cover")
async def redo_cover(job_id: str, body: dict = Body(default={})):
    """Refaz a capa: com texto novo e/ou nova imagem de fundo. Depois refaz o render."""
    _job_or_404(job_id)
    await worker.stop(job_id)
    if body.get("new_image"):
        for p in (config.JOBS_DIR / job_id / "cover").glob("bg.*"):
            p.unlink()
    if "text" in body and body["text"] is not None:
        db.update_job(job_id, data={"cover_text_override": body["text"].strip()})
    db.update_job(job_id, data={"approved": False})
    db.reset_from(job_id, "capa")
    db.log(job_id, "Refazendo a capa" + (" com nova imagem" if body.get("new_image") else ""))
    worker.wake()
    return {"ok": True}


@app.put("/api/jobs/{job_id}/script")
async def edit_script(job_id: str, script: dict = Body(...)):
    """Edita o roteiro e refaz da narração em diante (mantém as imagens já geradas)."""
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, data={"script": script, "approved": False})
    db.reset_from(job_id, "narracao")
    db.log(job_id, "Roteiro editado no painel; refazendo da narração")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, status="canceled")
    return {"ok": True}


@app.delete("/api/jobs/{job_id}")
async def delete(job_id: str):
    await worker.stop(job_id)
    db.delete_job(job_id)
    shutil.rmtree(config.JOBS_DIR / job_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/file/{name:path}")
def job_file(job_id: str, name: str, download: bool = False):
    base = (config.JOBS_DIR / job_id).resolve()
    path = (base / name).resolve()
    if not path.is_file() or base not in path.parents:
        raise HTTPException(404)
    filename = None
    if download:
        title = ((db.get_job(job_id) or {}).get("data", {}).get("script") or {}).get("title") or job_id
        filename = re.sub(r"[^\w\- ]+", "", title).strip()[:60] + path.suffix
    return FileResponse(path, filename=filename)


@app.get("/api/elevenlabs/voices")
async def el_voices():
    from .providers import tts
    try:
        return {"voices": await tts.elevenlabs_voices(config.load()["providers"])}
    except ProviderError as e:
        raise HTTPException(400, str(e))


@app.get("/api/elevenlabs/usage")
async def el_usage():
    from .providers import tts
    try:
        return await tts.elevenlabs_usage(config.load()["providers"])
    except ProviderError as e:
        raise HTTPException(400, str(e))


@app.post("/api/tts/preview")
async def tts_preview(body: dict = Body(...)):
    """Gera um trecho curto com a voz configurada do canal, para ouvir no painel."""
    from .providers import tts
    cfg = config.load()
    ch = config.channel(cfg, body["channel"])
    opts = {**ch["models"]["narracao"], **(body.get("opts") or {})}
    out = config.DATA_DIR / "previews" / f"{body['channel']}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = body.get("text") or "Naquela noite, a porta do porão se abriu sozinha. E alguém desceu a escada."
    try:
        await tts.synthesize(text[:300], out, opts, cfg["providers"])
    except ProviderError as e:
        raise HTTPException(400, str(e))
    return FileResponse(out, media_type="audio/mpeg")


# ------------------------------------------------------------------ worker
@app.post("/api/worker/{action}")
def worker_action(action: str):
    if action not in ("pause", "resume"):
        raise HTTPException(400)
    worker.paused = action == "pause"
    worker.wake()
    return {"paused": worker.paused}


# ------------------------------------------------------------------ youtube
@app.get("/api/youtube")
def youtube_status():
    cfg = config.load()
    return {cid: upload.status(cfg, cid) for cid in cfg["channels"]}


@app.get("/api/youtube/connect/{cid}")
def youtube_connect(cid: str, request: Request):
    cfg = config.load()
    redirect = f"http://localhost:{request.url.port or PORT}/api/youtube/callback"
    try:
        return RedirectResponse(upload.start_auth(cfg, cid, redirect))
    except FileNotFoundError as e:
        return HTMLResponse(f"<p>{e}</p><p>Veja as instruções na aba Provedores.</p>", status_code=400)


@app.get("/api/youtube/callback")
def youtube_callback(state: str, code: str | None = None, error: str | None = None):
    if error or not code:
        return HTMLResponse(f"<p>Autorização cancelada: {error}</p><a href='/'>voltar</a>")
    try:
        upload.finish_auth(state, code)
    except KeyError:
        return HTMLResponse("<p>Sessão de login expirou; tente de novo.</p><a href='/'>voltar</a>", 400)
    return RedirectResponse("/#canais")


@app.get("/api/analytics/{cid}")
async def channel_analytics(cid: str, days: int = 28, refresh: bool = False):
    from . import analytics
    cfg = config.load()
    if cid not in cfg["channels"]:
        raise HTTPException(404, "Canal desconhecido")
    st = upload.status(cfg, cid)
    if not st["connected"]:
        return {"state": "disconnected"}
    if not analytics.has_scope(cid):
        return {"state": "needs_reconnect"}
    try:
        return {"state": "ok", **(await analytics.report(cid, max(7, min(days, 365)), refresh))}
    except Exception as e:
        msg = str(e)
        if "accessNotConfigured" in msg or "has not been used" in msg or "is disabled" in msg:
            msg = "A YouTube Analytics API não está ativada no projeto do Google Cloud."
        raise HTTPException(502, msg[:500])


@app.get("/api/learn/{cid}")
def learn_get(cid: str):
    from . import learn
    return {**learn.load(cid), "running": learn.running(cid)}


@app.post("/api/learn/{cid}")
async def learn_now(cid: str):
    from . import analytics, learn
    if cid not in config.load()["channels"]:
        raise HTTPException(404, "Canal desconhecido")
    if not analytics.has_scope(cid):
        raise HTTPException(400, "Conecte o YouTube deste canal com acesso ao Analytics primeiro")
    try:
        return await learn.run(cid)
    except Exception as e:
        raise HTTPException(502, str(e)[:500])


@app.delete("/api/learn/{cid}")
def learn_clear(cid: str):
    from . import learn
    learn.path(cid).unlink(missing_ok=True)
    return {"ok": True}


@app.delete("/api/youtube/{cid}")
def youtube_disconnect(cid: str):
    upload.disconnect(cid)
    return {"ok": True}


def main():
    import uvicorn

    print(f"ShortPipeline em http://localhost:{PORT}")
    uvicorn.run(app, host=os.environ.get("SHORTPIPELINE_HOST", "127.0.0.1"), port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
