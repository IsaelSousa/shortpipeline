"""Fila de jobs: criação, detalhes, aprovação, refação e arquivos."""

from __future__ import annotations


import hashlib
import math
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config, db, upload
from ..providers import ProviderError
from ..worker import worker
from .common import _job_or_404, _public

router = APIRouter()

@router.get("/api/jobs")
def jobs(channel: str | None = None, kind: str | None = None, limit: int = 100):
    return {"jobs": [_public(j) for j in db.list_jobs(channel, limit, kind)], "stats": db.stats(),
            "paused": worker.paused, "running": list(worker.running)}


@router.post("/api/uploads")
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


@router.post("/api/jobs")
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
    elif kind in ("short", "long", "animado"):
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


@router.get("/api/jobs/{job_id}")
def job_detail(job_id: str, after: int = 0):
    job = _job_or_404(job_id)
    out = {"job": _public(job), "logs": db.get_logs(job_id, after)}
    if job["kind"] == "fonte":
        out["children"] = [_public(c) for c in db.list_children(job_id)]
    if job.get("parent_id"):
        parent = db.get_job(job["parent_id"])
        out["parent"] = {"id": parent["id"], "topic": parent["topic"]} if parent else None
    return out


@router.get("/api/jobs/{job_id}/transcript")
def job_transcript(job_id: str):
    from ..providers.transcribe import transcript_lines
    path = config.JOBS_DIR / job_id / "transcript.json"
    if not path.exists():
        raise HTTPException(404, "Sem transcrição")
    import json as _json
    tr = _json.loads(path.read_text())
    return {"lines": transcript_lines(tr["words"]), "provider": tr.get("provider"), "language": tr.get("language")}


@router.put("/api/jobs/{job_id}/clip")
async def edit_clip(job_id: str, body: dict = Body(...)):
    """Muda o início/fim de um corte e refaz a partir do recorte."""
    import json as _json
    from ..pipeline import clip_words
    job = _job_or_404(job_id)
    if job["kind"] != "corte":
        raise HTTPException(400, "Não é um corte")
    try:
        start, end = round(float(body["start"]), 2), round(float(body["end"]), 2)
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, "Informe o início e o fim do corte") from exc
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end - start < 3:
        raise HTTPException(400, "O corte precisa ter pelo menos 3 segundos e início válido")
    source_job = db.get_job(job["data"]["source_job"])
    source_duration = ((source_job or {}).get("data", {}).get("source") or {}).get("duration")
    if source_duration and end > source_duration + 0.05:
        raise HTTPException(400, "O fim do corte ultrapassa a duração do vídeo")
    tr_path = config.JOBS_DIR / job["data"]["source_job"] / "transcript.json"
    words = _json.loads(tr_path.read_text())["words"] if tr_path.exists() else []
    clip = {**job["data"]["clip"], "start": round(start, 2), "end": round(end, 2)}
    if "framing" in body:
        framing = body["framing"]
        mode = framing.get("mode") if isinstance(framing, dict) else None
        if mode not in ("channel", "face", "blur", "center", "manual"):
            raise HTTPException(400, "Enquadramento inválido")
        try:
            x, y = float(framing.get("x", 0.5)), float(framing.get("y", 0.5))
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Posição do recorte inválida") from exc
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise HTTPException(400, "Posição do recorte fora da imagem")
        clip["framing"] = {"mode": mode, "x": x, "y": y} if mode != "channel" else None
    await worker.stop(job_id)
    db.update_job(job_id, data={"clip": clip, "words": clip_words(words, start, end), "approved": False})
    for p in (config.JOBS_DIR / job_id / "cover").glob("bg.*"):
        p.unlink()
    db.reset_from(job_id, "recorte")
    db.log(job_id, f"Corte ajustado para {start:.1f}s – {end:.1f}s")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/approve-clips")
async def approve_clips(job_id: str, body: dict = Body(...)):
    job = _job_or_404(job_id)
    if job["kind"] != "fonte" or job["status"] != "waiting_approval" or job["stage"] != "selecao":
        raise HTTPException(409, "A seleção de cortes não está aguardando aprovação")
    candidates = job["data"].get("clip_candidates") or []
    indices = body.get("indices")
    if not isinstance(indices, list) or not indices or any(type(i) is not int or not 0 <= i < len(candidates) for i in indices):
        raise HTTPException(400, "Selecione pelo menos um corte")
    db.update_job(job_id, status="queued", data={"approved_clip_candidates": [candidates[i] for i in sorted(set(indices))]})
    db.log(job_id, f"{len(set(indices))} cortes aprovados", stage="selecao")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/clip-context")
async def preview_clip_context(job_id: str, index: int | None = None):
    from .. import render

    job = _job_or_404(job_id)
    if job["kind"] == "corte":
        clip = job["data"].get("clip")
        source_id = job["data"].get("source_job")
    elif job["kind"] == "fonte" and index is not None:
        candidates = job["data"].get("clip_candidates") or []
        clip = candidates[index] if 0 <= index < len(candidates) else None
        source_id = job_id
    else:
        raise HTTPException(404, "Trecho não encontrado")
    if not clip or not source_id:
        raise HTTPException(404, "Trecho não encontrado")
    source_job = _job_or_404(source_id)
    source = source_job["data"].get("source") or {}
    path = Path(source.get("path") or "").resolve()
    source_dir = (config.JOBS_DIR / source_id).resolve()
    if path.parent != source_dir or not path.is_file():
        raise HTTPException(404, "Vídeo de origem não encontrado")
    start = max(0.0, float(clip["start"]) - 3)
    end = min(float(clip["end"]) + 3, float(source.get("duration") or clip["end"] + 3))
    key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{start:.3f}:{end:.3f}".encode()).hexdigest()[:20]
    folder = config.JOBS_DIR / job_id / "clip-previews"
    folder.mkdir(exist_ok=True)
    dest = folder / f"{key}.mp4"
    if not dest.is_file():
        with TemporaryDirectory(dir=folder) as directory:
            temp = Path(directory) / dest.name
            try:
                await render.ffmpeg(["-ss", f"{start:.3f}", "-i", str(path), "-t", f"{end-start:.3f}",
                                     "-map", "0:v:0", "-map", "0:a:0?", "-vf",
                                     "scale=640:640:force_original_aspect_ratio=decrease:force_divisible_by=2",
                                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                                     "-c:a", "aac", "-movflags", "+faststart", str(temp)], timeout=90)
            except (ProviderError, TimeoutError) as exc:
                raise HTTPException(422, "Não foi possível preparar o trecho") from exc
            temp.replace(dest)
    return {"url": f"/api/jobs/{job_id}/file/clip-previews/{dest.name}", "start": start, "end": end}


@router.post("/api/jobs/{job_id}/approve")
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


@router.post("/api/jobs/{job_id}/approve-stage")
async def approve_stage(job_id: str, body: dict = Body(...)):
    job = _job_or_404(job_id)
    stage = body.get("stage")
    if (job["status"] != "waiting_approval" or stage != job["stage"]
            or stage not in config.REVIEW_AFTER_STAGES
            or job["stages"].get(stage, {}).get("status") != "review_pending"):
        raise HTTPException(409, "A etapa indicada não está aguardando revisão")
    db.update_job(job_id, status="queued", stages={stage: {"status": "done"}})
    db.log(job_id, "Revisão aprovada no painel", stage=stage)
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/publish")
def publish_now(job_id: str, body: dict = Body(default={})):
    """Envia para o YouTube um job que terminou em modo manual."""
    _job_or_404(job_id)
    mode = "draft" if body.get("draft") else "auto"
    db.update_job(job_id, data={"upload_mode_override": mode, "approved": True,
                                **({"publish_at": body["publish_at"]} if body.get("publish_at") else {})})
    db.reset_from(job_id, "upload")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/reject")
async def reject(job_id: str):
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, status="canceled", error="Rejeitado na revisão")
    db.log(job_id, "Rejeitado na revisão", "warn", "revisao")
    return {"ok": True}


@router.post("/api/jobs/{job_id}/retry")
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
    if stage == "ideia" and not job.get("topic"):
        db.update_job(job_id, data={"idea_options": []})
    if stage in ("download", "transcricao", "selecao"):
        db.update_job(job_id, data={"clip_candidates": [], "approved_clip_candidates": None})
    if stage == "imagens" and body.get("regenerate_images", True):
        shutil.rmtree(job_dir / "images", ignore_errors=True)
    if "revisao" in order and order.index(stage) <= order.index("revisao"):
        db.update_job(job_id, data={"approved": False})
    db.reset_from(job_id, stage)
    db.log(job_id, f"Refazendo a partir de: {config.STAGE_LABELS[stage]}")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/approve-idea")
async def approve_idea(job_id: str, body: dict = Body(...)):
    job = _job_or_404(job_id)
    if job["status"] != "waiting_approval" or job["stage"] != "ideia":
        raise HTTPException(409, "Este vídeo não está aguardando aprovação da pauta")
    options = job["data"].get("idea_options") or []
    index = body.get("index")
    if type(index) is not int or not 0 <= index < len(options):
        raise HTTPException(400, "Escolha uma candidata")
    idea = dict(options[index])
    topic = str(body.get("topic") or "").strip()
    if not topic or len(topic) > 900:
        raise HTTPException(400, "Escreva uma pauta de até 900 caracteres")
    source = idea.pop("source", None)
    if topic != idea["topic"]:
        idea = {"topic": topic}
        source = None
    db.update_job(job_id, topic=topic, status="queued",
                  data={"editorial_idea": idea, "idea_options": [], "source": source})
    if source:
        db.mark_source_used(job["channel"], source["link"])
    db.log(job_id, f"Pauta aprovada: {topic}", stage="ideia")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/regenerate-image/{index}")
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


@router.post("/api/jobs/{job_id}/cover")
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


@router.put("/api/jobs/{job_id}/script")
async def edit_script(job_id: str, script: dict = Body(...)):
    """Edita o roteiro e refaz da narração em diante (mantém as imagens já geradas)."""
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, data={"script": script, "approved": False, "narration_scene": None})
    db.reset_from(job_id, "narracao")
    db.log(job_id, "Roteiro editado no painel; refazendo da narração")
    worker.wake()
    return {"ok": True}


@router.put("/api/jobs/{job_id}/scenes/{index}/narration")
async def edit_scene_narration(job_id: str, index: int, body: dict = Body(...)):
    from ..providers.tts import strip_tags

    job = _job_or_404(job_id)
    if job["status"] in ("queued", "running") or job_id in worker.running:
        raise HTTPException(409, "Aguarde o processamento antes de editar a narração")
    script = job["data"].get("script") or {}
    scenes = script.get("scenes") or []
    text = str(body.get("text") or "").strip()
    if job["kind"] not in ("short", "long") or not 0 <= index < len(scenes):
        raise HTTPException(404, "Cena não encontrada")
    if not strip_tags(text) or len(text) > 10000:
        raise HTTPException(400, "Informe um texto de narração válido")
    folder = config.JOBS_DIR / job_id
    if not (folder / "timings.json").is_file() or not all((folder / "audio" / f"{i:02d}.mp3").is_file() for i in range(len(scenes))):
        raise HTTPException(409, "Gere a narração completa antes de refazer uma cena")
    scenes[index]["narration"] = text
    script["scenes"] = scenes
    order = config.stages_for(job["kind"])
    pending = {stage: {"status": "pending", "started": None, "ended": None, "error": None, "detail": None}
               for stage in ("narracao", *order[order.index("legendas"):])}
    db.update_job(job_id, status="queued", stage=None, error=None, stages=pending,
                  data={"script": script, "narration_scene": index, "approved": False, "approved_render": False})
    db.log(job_id, f"Refazendo a locução da cena {index + 1}")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/cancel")
async def cancel(job_id: str):
    _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, status="canceled")
    return {"ok": True}


@router.delete("/api/jobs/{job_id}")
async def delete(job_id: str):
    await worker.stop(job_id)
    db.delete_job(job_id)
    shutil.rmtree(config.JOBS_DIR / job_id, ignore_errors=True)
    return {"ok": True}


@router.post("/api/jobs/{job_id}/upload-thumbnail")
async def upload_thumbnail_now(job_id: str):
    """Reenvia a capa como thumbnail para o vídeo já enviado ao YouTube."""
    job = _job_or_404(job_id)
    pub = job.get("data", {}).get("publish") or {}
    video_id = pub.get("video_id")
    if not video_id:
        raise HTTPException(400, "Vídeo ainda não foi enviado ao YouTube")
    cov = job.get("data", {}).get("cover") or {}
    cov_path = cov.get("jpg") or cov.get("image")
    if not cov_path or not Path(cov_path).exists():
        raise HTTPException(400, "Capa não encontrada no disco")
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    creds = upload._credentials(job["channel"])
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    mimetype = "image/png" if Path(cov_path).suffix.lower() == ".png" else "image/jpeg"
    try:
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(cov_path), mimetype=mimetype, resumable=True)).execute()
        pub["thumbnail"] = True
        pub.pop("thumbnail_error", None)
        db.update_job(job_id, data={"publish": pub})
        db.log(job_id, "Capa enviada como thumbnail para o YouTube com sucesso")
        return {"ok": True}
    except Exception as e:
        err = str(e)[:300]
        pub["thumbnail_error"] = err
        db.update_job(job_id, data={"publish": pub})
        raise HTTPException(500, f"Falha ao enviar thumbnail: {err}")


@router.post("/api/jobs/{job_id}/publish-instagram")
async def publish_instagram_now(job_id: str, body: dict = Body(default={})):
    """Publica ou envia o vídeo renderizado para o Instagram Reels."""
    from .. import instagram
    job = _job_or_404(job_id)
    d = job.get("data") or {}
    video_path = d.get("video")
    if not video_path or not Path(video_path).exists():
        job_dir = config.JOBS_DIR / job_id
        if (job_dir / "final.mp4").exists():
            video_path = str(job_dir / "final.mp4")
        elif (job_dir / "reframed.mp4").exists():
            video_path = str(job_dir / "reframed.mp4")
        else:
            raise HTTPException(400, "Vídeo final não encontrado no disco")

    cfg = config.load()
    ch = config.channel(cfg, job["channel"])
    meta = dict(d.get("script") or {})
    opts = dict(ch.get("upload") or {})

    try:
        ig_res = await instagram.upload(
            job["channel"],
            Path(video_path),
            meta,
            opts,
        )
        pub = d.get("publish") or {}
        pub["instagram"] = ig_res
        pub.pop("instagram_error", None)
        db.update_job(job_id, data={"publish": pub})
        db.log(job_id, f"Vídeo publicado no Instagram Reels: {ig_res.get('permalink')}")
        return {"ok": True, "result": ig_res}
    except Exception as e:
        err = str(e)[:300]
        pub = d.get("publish") or {}
        pub["instagram_error"] = err
        db.update_job(job_id, data={"publish": pub})
        raise HTTPException(500, f"Falha no upload para o Instagram Reels: {err}")


@router.get("/api/jobs/{job_id}/file/{name:path}")
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
