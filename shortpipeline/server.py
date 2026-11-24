"""Painel web + API. Rode com: uv run shortpipeline  (abre em http://localhost:8765)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, upload, tiktok
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


def build_timeline(job: dict) -> dict:
    job_id = job["id"]
    job_dir = config.JOBS_DIR / job_id
    d = job.get("data") or {}
    script = d.get("script") or {}
    scenes_raw = script.get("scenes") or []
    durations = d.get("durations") or []
    total_dur = float(d.get("duration") or sum(durations) or 0.0)

    cfg = config.load()
    ch = config.channel(cfg, job["channel"])
    cr = ch.get("creative") or {}
    cov_cfg = ch.get("cover") or {}
    is_long = job.get("kind") == "long"
    is_corte = job.get("kind") == "corte"
    cut_every = float(cr.get("cut_every_long" if is_long else "cut_every") or 0)

    from .pipeline import plan_shots, rating_on, find_word_time, Ctx

    scenes = []
    all_captions = []

    if is_corte:
        clip = d.get("clip") or {}
        clip_dur = float(d.get("duration") or (clip.get("end", 0) - clip.get("start", 0)) or 10.0)
        total_dur = clip_dur
        words = d.get("words") or []
        words_abs = [{"text": w["text"], "start": float(w["start"]), "end": float(w["end"])} for w in words]
        chunk = []
        for w in words_abs:
            chunk.append(w)
            if len(chunk) >= 3 or w["text"].endswith((".", "!", "?", ",", ":")):
                all_captions.append({
                    "start": round(chunk[0]["start"], 3),
                    "end": round(chunk[-1]["end"], 3),
                    "text": " ".join(x["text"] for x in chunk)
                })
                chunk = []
        if chunk:
            all_captions.append({
                "start": round(chunk[0]["start"], 3),
                "end": round(chunk[-1]["end"], 3),
                "text": " ".join(x["text"] for x in chunk)
            })
        scenes.append({
            "index": 0,
            "scene_num": 1,
            "start": 0.0,
            "end": round(clip_dur, 2),
            "duration": round(clip_dur, 2),
            "narration": " ".join(w["text"] for w in words),
            "image_prompt": "",
            "image_url": None,
            "audio_url": None,
            "beat": "",
            "sfx": [],
            "ambience": "",
            "chapter": "",
            "shots": [],
            "words": words_abs,
        })
    else:
        timings_path = job_dir / "timings.json"
        timings = json.loads(timings_path.read_text()) if timings_path.exists() else []
        t_offset = 0.0
        for i, sc in enumerate(scenes_raw):
            dur = durations[i] if i < len(durations) else 0.0
            start = round(t_offset, 3)
            end = round(start + dur, 3)

            img_name = None
            for p in (job_dir / "images").glob(f"{i:02d}.*"):
                if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    img_name = f"images/{p.name}"
                    break
            if not img_name and d.get("images") and i < len(d["images"]) and d["images"][i]:
                img_p = Path(d["images"][i])
                if img_p.exists():
                    img_name = f"images/{img_p.name}"

            audio_name = None
            if (job_dir / "audio" / f"{i:02d}.mp3").exists():
                audio_name = f"audio/{i:02d}.mp3"

            sc_words = timings[i] if i < len(timings) else []
            words_abs = [
                {"text": w["text"], "start": round(start + w["start"], 3), "end": round(start + w["end"], 3)}
                for w in sc_words
            ]

            chunk = []
            for w in words_abs:
                chunk.append(w)
                if len(chunk) >= 3 or w["text"].endswith((".", "!", "?", ",", ":")):
                    all_captions.append({
                        "start": round(chunk[0]["start"], 3),
                        "end": round(chunk[-1]["end"], 3),
                        "text": " ".join(x["text"] for x in chunk)
                    })
                    chunk = []
            if chunk:
                all_captions.append({
                    "start": round(chunk[0]["start"], 3),
                    "end": round(chunk[-1]["end"], 3),
                    "text": " ".join(x["text"] for x in chunk)
                })

            shots = plan_shots(sc_words, dur, cut_every) if cut_every > 0 else []

            scenes.append({
                "index": i,
                "scene_num": i + 1,
                "start": start,
                "end": end,
                "duration": round(dur, 2),
                "narration": sc.get("narration") or "",
                "image_prompt": sc.get("image_prompt") or "",
                "image_url": f"/api/jobs/{job_id}/file/{img_name}" if img_name else None,
                "audio_url": f"/api/jobs/{job_id}/file/{audio_name}" if audio_name else None,
                "beat": sc.get("beat") or "",
                "sfx": sc.get("sfx") or [],
                "ambience": sc.get("ambience") or "",
                "chapter": sc.get("chapter") or "",
                "shots": shots,
                "words": words_abs,
            })
            t_offset += dur

    snd_data = d.get("sound") or {}
    events = snd_data.get("events")
    beds = snd_data.get("beds")

    if not isinstance(events, list):
        events = []
        t_off = 0.0
        timings_path = job_dir / "timings.json"
        timings = json.loads(timings_path.read_text()) if timings_path.exists() else []
        for i, sc in enumerate(scenes_raw):
            dur = durations[i] if i < len(durations) else 0.0
            words = timings[i] if i < len(timings) else []
            if i > 0 and cr.get("whoosh", True):
                events.append({"type": "whoosh", "label": "Whoosh (transição)", "at": round(max(0.0, t_off - 0.3), 2), "scene": i + 1})
            beat = (sc.get("beat") or "").lower()
            if beat in ("scare", "reveal") and cr.get("beat_fx", True):
                first_sfx = next((x for x in sc.get("sfx") or [] if x.get("word")), None)
                rel = find_word_time(words, first_sfx["word"]) if first_sfx else None
                if rel is None:
                    rel = words[len(words) // 2]["start"] if words else dur / 2
                events.append({"type": "impact", "label": f"Impacto ({'susto' if beat == 'scare' else 'revelação'})", "at": round(t_off + rel, 2), "scene": i + 1})
            for x in (sc.get("sfx") or [])[:2]:
                if x.get("sound"):
                    rel = find_word_time(words, x.get("word") or "")
                    if rel is not None:
                        events.append({"type": "sfx", "label": x["sound"], "word": x.get("word"), "at": round(t_off + rel, 2), "scene": i + 1})
            t_off += dur
        if rating_on(Ctx(job, cfg)) and script.get("rating") is not None:
            at = max(0.0, total_dur - float(cr.get("rating_seconds") or 2.4))
            events.append({"type": "blip", "label": "Selo de nota", "at": round(at, 2)})
        if cr.get("sonic_logo"):
            events.append({"type": "sonic_logo", "label": "Assinatura sonora", "at": round(max(0.0, total_dur - 0.75), 2)})

    if not isinstance(beds, list):
        beds = []
        t_off = 0.0
        for i, sc in enumerate(scenes_raw):
            dur = durations[i] if i < len(durations) else 0.0
            if sc.get("ambience"):
                beds.append({"sound": sc["ambience"], "start": round(t_off, 2), "dur": round(dur, 2), "scene": i + 1})
            t_off += dur

    cov = d.get("cover") or {}
    cov_image_url = None
    if (job_dir / "cover" / "cover.png").exists():
        cov_image_url = f"/api/jobs/{job_id}/file/cover/cover.png"
    elif cov.get("image"):
        cov_image_url = f"/api/jobs/{job_id}/file/cover/cover.png"

    in_video_seconds = float(cov_cfg.get("in_video_seconds") or 0.3) if cov_cfg.get("in_video") and not is_long else 0.0

    meter = None
    if script.get("rating") is not None and cr.get("rating_meter") and not is_long:
        r_sec = float(cr.get("rating_seconds") or 2.4)
        meter = {
            "score": script["rating"],
            "label": cr.get("rating_label") or "NOTA",
            "start": round(max(0.0, total_dur - r_sec), 2),
            "end": round(total_dur, 2),
        }

    has_narration_wav = (job_dir / "narration.wav").exists()
    has_sfx_wav = (job_dir / "sfx.wav").exists()
    has_final_mp4 = (job_dir / "final.mp4").exists()
    has_reframed = (job_dir / "reframed.mp4").exists()

    video_url = None
    if has_final_mp4:
        video_url = f"/api/jobs/{job_id}/file/final.mp4"
    elif is_corte and has_reframed:
        video_url = f"/api/jobs/{job_id}/file/reframed.mp4"

    return {
        "job_id": job_id,
        "kind": job["kind"],
        "channel": job["channel"],
        "title": script.get("title") or job.get("topic") or "Vídeo",
        "total_duration": round(total_dur, 2),
        "scenes": scenes,
        "captions": all_captions,
        "sound_events": events,
        "sound_beds": beds,
        "cover": {
            "image_url": cov_image_url,
            "text": d.get("cover_text_override") or cov.get("text") or script.get("cover_text") or "",
            "in_video_seconds": in_video_seconds,
        },
        "meter": meter,
        "audio": {
            "narration_url": f"/api/jobs/{job_id}/file/narration.wav" if has_narration_wav else None,
            "sfx_url": f"/api/jobs/{job_id}/file/sfx.wav" if has_sfx_wav else None,
        },
        "video_url": video_url,
        "status": {
            "is_waiting_render": job.get("status") == "waiting_approval" and job.get("stage") == "render",
            "is_rendered": has_final_mp4,
            "ready_to_render": (len(scenes) > 0 and (has_narration_wav or is_corte)),
            "approved_render": bool(d.get("approved_render")),
        }
    }


@app.get("/api/jobs/{job_id}/timeline")
def job_timeline(job_id: str):
    job = _job_or_404(job_id)
    return build_timeline(job)


@app.post("/api/jobs/{job_id}/start-render")
async def start_render(job_id: str):
    """Aprova a timeline e inicia a renderização do vídeo."""
    job = _job_or_404(job_id)
    await worker.stop(job_id)
    db.update_job(job_id, data={"approved_render": True}, status="queued")
    db.log(job_id, "Timeline aprovada; iniciando renderização", stage="render")
    worker.wake()
    return {"ok": True}


@app.post("/api/jobs/{job_id}/ai-correct")
async def ai_correct(job_id: str, body: dict = Body(...)):
    """Aplica uma correção solicitada pelo usuário no roteiro, imagens, som ou capa via IA."""
    job = _job_or_404(job_id)
    instruction = (body.get("instruction") or "").strip()
    if not instruction:
        raise HTTPException(400, "Instrução de correção vazia")
    script = job.get("data", {}).get("script")
    if not script:
        raise HTTPException(400, "Job ainda não possui roteiro para corrigir")

    cfg = config.load()
    ch = config.channel(cfg, job["channel"])
    from .providers import llm
    from .pipeline import Ctx
    c = Ctx(job, cfg)
    cover_text = job.get("data", {}).get("cover_text_override") or script.get("cover_text") or ""
    prompt = f"""Você é o editor e diretor de criação do canal "{ch['name']}" ({ch.get('niche', '')}).
O usuário está visualizando a timeline do vídeo antes de renderizar e solicitou a seguinte correção:

"{instruction}"

Roteiro atual do vídeo:
{json.dumps(script, ensure_ascii=False, indent=2)}

Texto da capa atual: "{cover_text}"

Analise cuidadosamente o pedido e determine quais modificações devem ser feitas:
- Se for sobre imagem/visual de cena: ajuste o "image_prompt" da cena correspondente e inclua o índice da cena (base 0) em "regenerate_image_indexes", com "restart_from": "imagens".
- Se for sobre narração/fala: ajuste o texto em "narration" da cena, com "restart_from": "narracao".
- Se for sobre capa: defina "new_cover_text" ou "new_cover_image": true, com "restart_from": "capa".
- Se for sobre efeitos sonoros/susto/ambiente: ajuste os campos "sfx", "beat" ou "ambience" da cena, com "restart_from": "som".
- Se for sobre o tema ou estrutura geral: ajuste o roteiro e defina "restart_from" apropriado.

Responda APENAS um objeto JSON com a seguinte estrutura:
{{
  "explanation": "Explicação amigável em português do que você alterou e o que será refeito",
  "restart_from": "imagens" | "narracao" | "capa" | "som" | "roteiro",
  "regenerate_image_indexes": [],
  "new_cover_text": null,
  "new_cover_image": false,
  "script": {{ ... roteiro completo atualizado ... }}
}}
"""
    try:
        out = await c.text("critica", prompt)
        parsed = llm.extract_json(out)
    except ProviderError as e:
        raise HTTPException(502, f"Falha no provedor de IA ao processar correção: {e}")

    explanation = parsed.get("explanation") or "Correção aplicada com sucesso"
    restart_from = parsed.get("restart_from") or "imagens"
    new_script = parsed.get("script") or script
    regen_indexes = parsed.get("regenerate_image_indexes") or []
    new_cov_text = parsed.get("new_cover_text")
    new_cov_img = parsed.get("new_cover_image")

    await worker.stop(job_id)
    job_dir = config.JOBS_DIR / job_id
    data_updates = {"script": new_script, "approved": False, "approved_render": False}

    if new_cov_text is not None:
        data_updates["cover_text_override"] = str(new_cov_text).strip()
    if new_cov_img:
        for p in (job_dir / "cover").glob("bg.*"):
            p.unlink()

    if regen_indexes:
        idir = job_dir / "images"
        for idx in regen_indexes:
            if isinstance(idx, int):
                for p in idir.glob(f"{idx:02d}.*"):
                    p.unlink()

    if restart_from == "imagens" and not regen_indexes:
        old_scenes = script.get("scenes") or []
        new_scenes = new_script.get("scenes") or []
        idir = job_dir / "images"
        for i, (osc, nsc) in enumerate(zip(old_scenes, new_scenes)):
            if osc.get("image_prompt") != nsc.get("image_prompt"):
                for p in idir.glob(f"{i:02d}.*"):
                    p.unlink()

    db.update_job(job_id, data=data_updates)
    order = config.stages_for(job["kind"])
    if restart_from not in order:
        restart_from = "imagens" if "imagens" in order else order[0]
    db.reset_from(job_id, restart_from)
    db.log(job_id, f"Correção pela IA: {explanation}", stage=restart_from)
    worker.wake()
    return {"ok": True, "explanation": explanation, "restart_from": restart_from}


@app.post("/api/jobs/{job_id}/upload-thumbnail")
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


def _get_sound_elements(job: dict) -> tuple[list[dict], list[dict]]:
    d = job.get("data") or {}
    snd = d.get("sound") or {}
    events = snd.get("events")
    beds = snd.get("beds")
    if isinstance(events, list) and isinstance(beds, list):
        return list(events), list(beds)
    tl = build_timeline(job)
    return list(tl.get("sound_events") or []), list(tl.get("sound_beds") or [])


@app.post("/api/jobs/{job_id}/delete-sfx")
async def delete_sfx(job_id: str, body: dict = Body(...)):
    """Remove um efeito sonoro específico da timeline e remixa sfx.wav."""
    job = _job_or_404(job_id)
    at = body.get("at")
    label = body.get("label")
    idx = body.get("index")

    d = job.get("data") or {}
    events, beds = _get_sound_elements(job)

    removed_event = None
    if idx is not None and 0 <= int(idx) < len(events):
        removed_event = events.pop(int(idx))
    elif at is not None:
        at_f = float(at)
        for i, ev in enumerate(events):
            if abs(float(ev.get("at", 0)) - at_f) < 0.05 and (not label or ev.get("label") == label):
                removed_event = events.pop(i)
                break

    if not removed_event:
        raise HTTPException(404, "Efeito sonoro não encontrado")

    d.setdefault("sound", {})["events"] = events
    d["sound"]["beds"] = beds

    # Re-mix sfx.wav
    job_dir = config.JOBS_DIR / job_id
    mix = job_dir / "sfx.wav"
    total_dur = d.get("script", {}).get("total_duration") or 30.0
    cfg = config.load()
    style = d.get("sound", {}).get("style") or "neutro"
    from . import sound

    rebuild_events = []
    for ev in events:
        file_path = ev.get("file")
        if file_path and Path(file_path).exists():
            rebuild_events.append({"file": Path(file_path), "at": ev["at"], "volume": ev.get("volume", 0.5)})
        else:
            try:
                f = await sound.library_sound(ev.get("type", "sfx"), style, cfg["providers"])
                rebuild_events.append({"file": f, "at": ev["at"], "volume": ev.get("volume", 0.5)})
            except Exception:
                pass

    rebuild_beds = []
    for b in beds:
        file_path = b.get("file")
        if file_path and Path(file_path).exists():
            rebuild_beds.append({"file": Path(file_path), "start": b["start"], "dur": b["dur"], "volume": b.get("volume", 0.15)})

    try:
        await sound.build_mix(rebuild_events, rebuild_beds, float(total_dur), mix)
    except Exception:
        pass

    db.update_job(job_id, data=d)
    name = removed_event.get("label") or removed_event.get("type") or "som"
    db.log(job_id, f"Efeito sonoro '{name}' removido da timeline")
    return {"ok": True, "timeline": build_timeline(db.get_job(job_id))}


@app.post("/api/jobs/{job_id}/delete-ambience")
async def delete_ambience(job_id: str, body: dict = Body(...)):
    """Remove um bloco de som ambiente da timeline e remixa sfx.wav."""
    job = _job_or_404(job_id)
    start = body.get("start")
    sound_name = body.get("sound")
    idx = body.get("index")

    d = job.get("data") or {}
    events, beds = _get_sound_elements(job)

    removed_bed = None
    if idx is not None and 0 <= int(idx) < len(beds):
        removed_bed = beds.pop(int(idx))
    elif start is not None:
        st_f = float(start)
        for i, b in enumerate(beds):
            if abs(float(b.get("start", 0)) - st_f) < 0.05 and (not sound_name or b.get("sound") == sound_name):
                removed_bed = beds.pop(i)
                break

    if not removed_bed:
        raise HTTPException(404, "Som ambiente não encontrado")

    d.setdefault("sound", {})["events"] = events
    d["sound"]["beds"] = beds

    # Re-mix sfx.wav
    job_dir = config.JOBS_DIR / job_id
    mix = job_dir / "sfx.wav"
    total_dur = d.get("script", {}).get("total_duration") or 30.0
    from . import sound
    cfg = config.load()
    style = d.get("sound", {}).get("style") or "neutro"

    rebuild_events = []
    for ev in events:
        file_path = ev.get("file")
        if file_path and Path(file_path).exists():
            rebuild_events.append({"file": Path(file_path), "at": ev["at"], "volume": ev.get("volume", 0.5)})
        else:
            try:
                f = await sound.library_sound(ev.get("type", "sfx"), style, cfg["providers"])
                rebuild_events.append({"file": f, "at": ev["at"], "volume": ev.get("volume", 0.5)})
            except Exception:
                pass

    rebuild_beds = []
    for b in beds:
        file_path = b.get("file")
        if file_path and Path(file_path).exists():
            rebuild_beds.append({"file": Path(file_path), "start": b["start"], "dur": b["dur"], "volume": b.get("volume", 0.15)})

    try:
        await sound.build_mix(rebuild_events, rebuild_beds, float(total_dur), mix)
    except Exception:
        pass

    db.update_job(job_id, data=d)
    name = removed_bed.get("sound") or "ambiente"
    db.log(job_id, f"Som ambiente '{name}' removido da timeline")
    return {"ok": True, "timeline": build_timeline(db.get_job(job_id))}


@app.post("/api/jobs/{job_id}/delete-scene")
async def delete_scene(job_id: str, body: dict = Body(...)):
    """Remove uma cena do roteiro e reajusta o vídeo a partir da narração."""
    job = _job_or_404(job_id)
    scene_idx = body.get("scene_index")
    scene_num = body.get("scene_num")

    d = job.get("data") or {}
    script = d.get("script") or {}
    scenes = script.get("scenes") or []
    if len(scenes) <= 1:
        raise HTTPException(400, "O vídeo não pode ter menos de 1 cena")

    idx = None
    if scene_idx is not None and 0 <= int(scene_idx) < len(scenes):
        idx = int(scene_idx)
    elif scene_num is not None:
        idx = next((i for i, s in enumerate(scenes) if s.get("scene_num") == int(scene_num)), None)

    if idx is None or idx < 0 or idx >= len(scenes):
        raise HTTPException(404, "Cena não encontrada")

    scenes.pop(idx)
    for i, sc in enumerate(scenes):
        sc["scene_num"] = i + 1
    script["scenes"] = scenes

    await worker.stop(job_id)
    job_dir = config.JOBS_DIR / job_id
    idir = job_dir / "images"
    if idir.exists():
        import shutil
        shutil.rmtree(idir)
        idir.mkdir(parents=True, exist_ok=True)

    db.update_job(job_id, data={"script": script, "approved": False, "approved_render": False})
    db.reset_from(job_id, "narracao")
    db.log(job_id, f"Cena {idx + 1} removida pelo usuário da timeline", stage="narracao")
    worker.wake()
    return {"ok": True, "explanation": f"Cena {idx + 1} removida. Vídeo sendo reajustado a partir da narração."}


@app.post("/api/jobs/{job_id}/publish-tiktok")
async def publish_tiktok_now(job_id: str, body: dict = Body(default={})):
    """Publica ou envia o vídeo renderizado para o TikTok."""
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
    cov_cfg = ch.get("cover") or {}
    is_long = bool(job.get("kind") == "long" or d.get("is_long"))
    opts["cover_in_video"] = bool(cov_cfg.get("in_video", True) and not is_long)
    if opts["cover_in_video"]:
        opts["cover_timestamp_ms"] = int(float(cov_cfg.get("in_video_seconds") or 0.3) * 1000 / 2)
    if body.get("privacy"):
        opts["tiktok_privacy"] = body["privacy"]

    try:
        tt_res = await tiktok.upload(
            job["channel"],
            Path(video_path),
            meta,
            opts,
        )
        pub = d.get("publish") or {}
        pub["tiktok"] = tt_res
        pub.pop("tiktok_error", None)
        db.update_job(job_id, data={"publish": pub})
        db.log(job_id, f"Vídeo enviado para o TikTok: {tt_res.get('status')}")
        return {"ok": True, "result": tt_res}
    except Exception as e:
        err = str(e)[:300]
        pub = d.get("publish") or {}
        pub["tiktok_error"] = err
        db.update_job(job_id, data={"publish": pub})
        raise HTTPException(500, f"Falha no upload para o TikTok: {err}")


@app.post("/api/jobs/{job_id}/publish-instagram")
async def publish_instagram_now(job_id: str, body: dict = Body(default={})):
    """Publica ou envia o vídeo renderizado para o Instagram Reels."""
    from . import instagram
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


@app.post("/api/jobs/{job_id}/add-sfx")
async def add_sfx_to_timeline(job_id: str, body: dict = Body(...)):
    """Adiciona um efeito sonoro (SFX) pontual na timeline e re-mixa o áudio."""
    job = _job_or_404(job_id)
    d = job.get("data") or {}
    durations = d.get("durations") or []
    total = sum(durations) if durations else 45.0
    cfg = config.load()
    snd = d.get("sound") or {}
    style = snd.get("style") or "neutro"

    at = float(body.get("at", 0.0))
    sfx_type = str(body.get("type", "whoosh")).lower()
    text = body.get("text") or sfx_type
    vol = float(body.get("volume", 0.55))

    from . import sound
    try:
        if sfx_type in ("whoosh", "impact", "riser"):
            sfile = await sound.library_sound(sfx_type, style, cfg.get("providers", {}))
        else:
            sfile = await sound.generate(text, cfg.get("providers", {}), duration=1.2)
    except Exception:
        sfile = await sound.library_sound("whoosh", style, cfg.get("providers", {}))

    events, beds = _get_sound_elements(job)
    new_event = {
        "file": str(sfile),
        "at": round(at, 2),
        "volume": vol,
        "type": sfx_type,
        "text": text,
    }
    events.append(new_event)
    events.sort(key=lambda x: x.get("at", 0))

    clean_events = [{"file": Path(e["file"]), "at": float(e["at"]), "volume": float(e.get("volume", 0.55))} for e in events if e.get("file")]
    clean_beds = [{"file": Path(b["file"]), "start": float(b["start"]), "dur": float(b["dur"]), "volume": float(b.get("volume", 0.16))} for b in beds if b.get("file")]

    job_dir = config.JOBS_DIR / job_id
    mix_dest = job_dir / "sfx_mix.wav"
    await sound.build_mix(clean_events, clean_beds, total, mix_dest)

    snd["events"] = events
    snd["beds"] = beds
    snd["mix"] = str(mix_dest)
    db.update_job(job_id, data={"sound": snd})
    db.log(job_id, f"Efeito '{sfx_type}' adicionado aos {at:.1f}s na timeline")
    return {"ok": True, "event": new_event}


@app.post("/api/jobs/{job_id}/adjust-audio-levels")
async def adjust_audio_levels(job_id: str, body: dict = Body(...)):
    """Ajusta os multiplicadores de volume (voz, música, sfx) e salva no job."""
    job = _job_or_404(job_id)
    d = job.get("data") or {}
    video_cfg = dict(d.get("video") or {})

    voice = max(0.0, min(2.0, float(body.get("voice", 1.0))))
    bgm = max(0.0, min(2.0, float(body.get("bgm", 1.0))))
    sfx = max(0.0, min(2.0, float(body.get("sfx", 1.0))))

    levels = {"voice": voice, "bgm": bgm, "sfx": sfx}
    d["audio_levels"] = levels
    video_cfg["audio_levels"] = levels
    db.update_job(job_id, data={"audio_levels": levels, "video": video_cfg})
    db.log(job_id, f"Níveis de áudio atualizados: Voz {voice:.1f}x, Música {bgm:.1f}x, SFX {sfx:.1f}x")
    return {"ok": True, "levels": levels}


@app.get("/api/trends")
async def get_trends(geo: str = "BR"):
    """Retorna tópicos em alta do Google Trends."""
    from . import trends
    return await trends.fetch_trends(geo)


@app.post("/api/notifications/test")
async def test_notification_endpoint(body: dict = Body(...)):
    """Envia notificação de teste para Telegram ou Discord."""
    from . import notify
    cfg = config.load()
    target = body.get("target") or body.get("service")

    if target == "telegram":
        tg = cfg.get("notifications", {}).get("telegram", {})
        token = tg.get("bot_token")
        chat_id = tg.get("chat_id")
        if not token or not chat_id:
            raise HTTPException(400, "Bot Token ou Chat ID do Telegram não configurados")
        ok = await notify.send_telegram(token, chat_id, "🔔 <b>Teste do ShortPipeline:</b> Notificações via Telegram conectadas com sucesso!")
        if not ok:
            raise HTTPException(502, "Falha ao enviar mensagem de teste pelo Telegram")
        return {"ok": True, "target": "telegram"}

    elif target == "discord":
        dc = cfg.get("notifications", {}).get("discord", {})
        webhook_url = dc.get("webhook_url")
        if not webhook_url:
            raise HTTPException(400, "Webhook URL do Discord não configurada")
        ok = await notify.send_discord(webhook_url, "Notificações via Discord Webhook conectadas com sucesso!", title="🔔 Teste do ShortPipeline", color=0x10B981)
        if not ok:
            raise HTTPException(502, "Falha ao enviar mensagem de teste pelo Discord")
        return {"ok": True, "target": "discord"}

    raise HTTPException(400, "Target inválido (deve ser 'telegram' ou 'discord')")


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


# ------------------------------------------------------------------ tiktok
@app.get("/api/tiktok")
def tiktok_status_all():
    cfg = config.load()
    return {cid: tiktok.status(cfg, cid) for cid in cfg.get("channels", {})}


@app.get("/api/tiktok/connect/{cid}")
def tiktok_connect(cid: str, request: Request):
    cfg = config.load()
    redirect = f"http://localhost:{request.url.port or PORT}/api/tiktok/callback"
    try:
        return RedirectResponse(tiktok.start_auth(cfg, cid, redirect))
    except ValueError as e:
        return HTMLResponse(f"<p>{e}</p><p>Veja as instruções na aba Provedores.</p>", status_code=400)


@app.get("/api/tiktok/callback")
async def tiktok_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code or not state:
        return HTMLResponse(f"<p>Autorização do TikTok cancelada: {error}</p><a href='/'>voltar</a>")
    cfg = config.load()
    redirect = f"http://localhost:{request.url.port or PORT}/api/tiktok/callback"
    try:
        cid = await tiktok.finish_auth(cfg, state, code, redirect)
        return RedirectResponse(f"/#canais/{cid}")
    except Exception as e:
        return HTMLResponse(f"<p>Falha no login do TikTok: {e}</p><a href='/'>voltar</a>", 400)


@app.delete("/api/tiktok/{cid}")
def tiktok_disconnect(cid: str):
    tiktok.disconnect(cid)
    return {"ok": True}


# ------------------------------------------------------------------ diagnóstico
@app.get("/api/diagnostics")
async def api_diagnostics(channel_id: str | None = None):
    """Executa diagnóstico em tempo real das APIs e integrações."""
    from . import tiktok
    from .providers import tts
    cfg = config.load()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "youtube": {},
        "tiktok": {},
        "instagram": {},
        "elevenlabs": {},
        "notifications": {},
        "cli": {},
    }

    # 1. YouTube
    cids = [channel_id] if channel_id and channel_id in cfg.get("channels", {}) else list(cfg.get("channels", {}).keys())
    for cid in cids:
        st = upload.status(cfg, cid)
        if not st.get("client_secret"):
            results["youtube"][cid] = {
                "status": "unconfigured",
                "api": "YouTube Data API",
                "version": "v3",
                "error": "client_secret.json não encontrado (veja Provedores)",
            }
        elif not st.get("connected"):
            results["youtube"][cid] = {
                "status": "disconnected",
                "api": "YouTube Data API",
                "version": "v3",
                "error": "Canal não conectado ao YouTube",
            }
        else:
            results["youtube"][cid] = await asyncio.to_thread(upload.check_connection, cid)

    # 2. TikTok
    for cid in cids:
        results["tiktok"][cid] = await tiktok.check_connection(cfg, cid)

    # 3. Instagram Reels
    from . import instagram
    for cid in cids:
        results["instagram"][cid] = await instagram.check_connection(cfg, cid)

    # 4. ElevenLabs
    results["elevenlabs"] = await tts.check_connection(cfg.get("providers", {}))

    # 5. Notificações
    notif = cfg.get("notifications") or {}
    results["notifications"] = {
        "telegram": bool(notif.get("telegram", {}).get("enabled") and notif.get("telegram", {}).get("bot_token")),
        "discord": bool(notif.get("discord", {}).get("enabled") and notif.get("discord", {}).get("webhook_url")),
    }

    # 4. CLIs locais
    for name in ("ffmpeg", "claude", "codex", "agy"):
        try:
            path = resolve_bin(name)
            results["cli"][name] = {"status": "ok", "path": path}
        except ProviderError:
            results["cli"][name] = {"status": "missing", "error": "Não encontrado no PATH"}

    return results


def main():
    import uvicorn

    print(f"ShortPipeline em http://localhost:{PORT}")
    uvicorn.run(app, host=os.environ.get("SHORTPIPELINE_HOST", "127.0.0.1"), port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
