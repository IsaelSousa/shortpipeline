"""Timeline do vídeo antes do render: faixas, mídia das cenas, sons e correção por IA."""

from __future__ import annotations


import asyncio
import hashlib
import json
import math
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .. import config, db
from .. import sound as sound_mod
from ..providers import ProviderError
from ..worker import worker
from .common import _job_or_404

router = APIRouter()


def _edited(job_id: str) -> None:
    """Marca que a timeline mudou depois do último render (o painel pede para renderizar de novo)."""
    db.update_job(job_id, data={"timeline_edited_at": time.time()})

def _sound_key(item: dict) -> str:
    """Identifica o som pelo arquivo e pela posição, para um link antigo não tocar o som errado."""
    raw = f"{item.get('file')}|{item.get('at', item.get('start'))}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _audio_url(job_id: str, track: str, i: int, item: dict) -> str | None:
    if not _timeline_sound_path(item, job_id):
        return None
    return f"/api/jobs/{job_id}/timeline/audio/{track}/{i}?k={_sound_key(item)}"


def _timeline_sound_path(item: dict, job_id: str) -> Path | None:
    from .. import sound

    filename = item.get("file")
    if not filename:
        return None
    path = Path(filename).resolve()
    if path.suffix not in sound.AUDIO_SUFFIXES or not path.is_file():
        return None
    if path.parent in {sound.CACHE.resolve(), (config.JOBS_DIR / job_id).resolve() / "imported-audio"} or (
        sound.in_library(path) and path.name == Path(filename).name
    ):
        return path
    return None


def build_timeline(job: dict) -> dict:
    from ..quality import scene_image
    from ..render import scene_media_path

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

    from ..pipeline import plan_shots, rating_on, find_word_time, Ctx

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
            source_name = img_name
            if img_name:
                img_name = scene_image(job_dir / img_name, job_dir, sc).relative_to(job_dir).as_posix()
            upscale_active = img_name != source_name
            media = sc.get("media") or {}
            replacement = scene_media_path(job_dir, media.get("file"))
            media_info = None
            if replacement:
                poster = replacement if media.get("kind") == "image" else scene_media_path(job_dir, media.get("poster"))
                if poster:
                    img_name = f"scene-media/{poster.name}"
                media_info = {**media, "url": f"/api/jobs/{job_id}/file/scene-media/{replacement.name}"}

            audio_name = None
            audio_file = job_dir / "audio" / f"{i:02d}.mp3"
            if audio_file.is_file():
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
            if media_info and media_info["kind"] == "video":
                shots = []

            scenes.append({
                "index": i,
                "scene_num": i + 1,
                "start": start,
                "end": end,
                "duration": round(dur, 2),
                "narration": sc.get("narration") or "",
                "image_prompt": sc.get("image_prompt") or "",
                "direction": sc["direction"] if isinstance(sc.get("direction"), dict) else {},
                "image_url": f"/api/jobs/{job_id}/file/{img_name}" if img_name else None,
                "original_image_url": f"/api/jobs/{job_id}/file/{source_name}" if source_name else None,
                "upscale_active": upscale_active,
                "media": media_info,
                "motion": sc.get("motion"),
                "audio_url": f"/api/jobs/{job_id}/file/{audio_name}?v={audio_file.stat().st_mtime_ns}" if audio_name else None,
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
    mix_path = Path(snd_data["mix"]) if snd_data.get("mix") else job_dir / "sfx.wav"
    has_sfx_wav = mix_path.parent.resolve() == job_dir.resolve() and mix_path.is_file()
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
        "sound_events": [
            {**item, "audio_url": _audio_url(job_id, "events", i, item)}
            for i, item in enumerate(events)
        ],
        "sound_beds": [
            {**item, "audio_url": _audio_url(job_id, "beds", i, item)}
            for i, item in enumerate(beds)
        ],
        "cover": {
            "image_url": cov_image_url,
            "text": d.get("cover_text_override") or cov.get("text") or script.get("cover_text") or "",
            "in_video_seconds": in_video_seconds,
        },
        "meter": meter,
        "audio": {
            "narration_url": f"/api/jobs/{job_id}/file/narration.wav" if has_narration_wav else None,
            "sfx_url": f"/api/jobs/{job_id}/file/{mix_path.name}" if has_sfx_wav else None,
        },
        "video_url": video_url,
        "status": {
            "is_waiting_render": (job.get("status") == "waiting_approval" and job.get("stage") == "render"
                                  and job["stages"].get("render", {}).get("status") != "review_pending"),
            "is_rendered": has_final_mp4,
            "needs_render": has_final_mp4 and float(d.get("timeline_edited_at") or 0)
            > (job_dir / "final.mp4").stat().st_mtime,
            "ready_to_render": (len(scenes) > 0 and (has_narration_wav or is_corte)),
            "approved_render": bool(d.get("approved_render")),
        }
    }


@router.get("/api/jobs/{job_id}/timeline")
async def job_timeline(job_id: str):
    job = _job_or_404(job_id)
    snd = (job.get("data") or {}).get("sound") or {}
    if ((snd.get("events") or snd.get("beds")) and snd.get("mix_version") != sound_mod.MIX_VERSION
            and job_id not in worker.running and job.get("status") != "queued" and job["data"].get("durations")):
        # mix salvo com uma versão antiga da mixagem: o player da timeline tocaria o som antigo
        try:
            cr = config.channel(config.load(), job["channel"]).get("creative") or {}
        except KeyError:
            cr = {}
        async with _timeline_sound_lock:
            new = await sound_mod.remix_saved(snd, sum(job["data"]["durations"]), config.JOBS_DIR / job_id / "sfx.wav",
                                              cr.get("ambience_volume"))
            db.update_job(job_id, data={"sound": new})
        db.log(job_id, "Trilha de efeitos refeita com a mixagem atual (ambiente nivelado)")
        _edited(job_id)
        job = db.get_job(job_id)
    return build_timeline(job)


@router.post("/api/jobs/{job_id}/check-render")
async def check_render(job_id: str):
    from .. import quality

    job = _job_or_404(job_id)
    path = config.JOBS_DIR / job_id / "final.mp4"
    if job_id in worker.running or not path.is_file():
        raise HTTPException(409, "Aguarde o render terminar para checar o vídeo")
    data = job["data"]
    durations = data.get("durations") or []
    duration = sum(durations) or data.get("duration")
    frame = (1920, 1080) if job["kind"] == "long" else (1080, 1920)
    try:
        report = await quality.inspect_render(path, frame, duration)
    except (ProviderError, TimeoutError) as exc:
        raise HTTPException(422, str(exc) or "A checagem excedeu o tempo disponível") from exc
    creative = config.channel(config.load(), job["channel"]).get("creative") or {}
    if creative.get("sound", True) and creative.get("ambience_volume") != 0:
        scenes = (data.get("script") or {}).get("scenes") or []
        beds = (data.get("sound") or {}).get("beds") or []
        start = 0.0
        for i, (scene, length) in enumerate(zip(scenes, durations)):
            has_ambience = any(
                bed.get("volume", 0) > 0 and Path(bed.get("file") or "").is_file()
                and bed["start"] < start + length and bed["start"] + bed["dur"] > start + min(length / 2, 0.5)
                for bed in beds
            )
            if scene.get("ambience") and not has_ambience:
                report["warnings"].append({"at": start, "message": f"Cena {i + 1} pede ambiência, mas não tem um bloco de áudio correspondente na timeline."})
            start += length
    return report


def _scene_visuals(job_id: str, index: int) -> tuple[dict, dict, Path, Path]:
    job = _job_or_404(job_id)
    if job_id in worker.running or job["status"] == "queued":
        raise HTTPException(409, "Aguarde o processamento para editar a cena")
    data = job["data"]
    script = data.get("script") or {}
    scenes = script.get("scenes") or []
    images = data.get("images") or []
    folder = (config.JOBS_DIR / job_id).resolve()
    if job["kind"] not in ("short", "long") or not 0 <= index < min(len(scenes), len(images)):
        raise HTTPException(404, "Cena com imagem não encontrada")
    source = Path(images[index] or "").resolve()
    if source.parent != folder / "images" or not source.is_file():
        raise HTTPException(404, "Imagem da cena não encontrada")
    return job, script, source, folder


def _motion_settings(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("template") not in ("comparison", "highlight", "reveal"):
        raise HTTPException(400, "Escolha uma animação disponível")
    text = {key: str(value.get(key) or "").strip()[:80] for key in ("title", "detail")}
    if value["template"] == "comparison" and not all(text.values()):
        raise HTTPException(400, "Preencha os dois valores da comparação")
    try:
        focus = {key: float(value.get(key, 0.5)) for key in ("focus_x", "focus_y")}
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Ponto focal inválido") from exc
    if not all(0 <= coord <= 1 for coord in focus.values()):
        raise HTTPException(400, "O ponto focal deve ficar dentro da imagem")
    return {"template": value["template"], **text, **focus}


_SCENE_IMAGE_FORMATS = {".jpg": "image2", ".jpeg": "image2", ".png": "image2", ".webp": "image2"}
_SCENE_VIDEO_FORMATS = {".mp4": "mov", ".mov": "mov", ".webm": "matroska", ".mkv": "matroska"}


@router.post("/api/jobs/{job_id}/scenes/{index}/media")
async def import_scene_media(job_id: str, index: int, file: UploadFile = File(...),
                             credit: str = Form(""), source_url: str = Form("")):
    from .. import render

    job, script, source, folder = _scene_visuals(job_id, index)
    original_scene = script["scenes"][index]
    stamp = source.stat().st_mtime_ns
    source_url = source_url.strip()
    if source_url:
        try:
            parsed = urlsplit(source_url)
            valid = parsed.scheme in ("https", "http") and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid or len(source_url) > 1000:
            raise HTTPException(400, "Informe uma URL de fonte HTTP ou HTTPS")
    suffix = Path(file.filename or "").suffix.lower()
    kind = "image" if suffix in _SCENE_IMAGE_FORMATS else "video"
    demuxer = (_SCENE_IMAGE_FORMATS if kind == "image" else _SCENE_VIDEO_FORMATS).get(suffix)
    if not demuxer:
        raise HTTPException(400, "Use JPG, PNG, WebP, MP4, MOV, WebM ou MKV")
    limit = 100 * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise HTTPException(413, "O arquivo deve ter até 100 MiB")
    media_dir = folder / "scene-media"
    media_dir.mkdir(exist_ok=True)
    key = uuid4().hex
    with TemporaryDirectory(dir=media_dir) as directory:
        temp = Path(directory)
        uploaded = temp / ("input" + suffix)
        size = 0
        with uploaded.open("wb") as stream:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, "O arquivo deve ter até 100 MiB")
                stream.write(chunk)
        args = ["-protocol_whitelist", "file", "-f", demuxer, "-i", str(uploaded), "-map", "0:v:0", "-an"]
        poster = temp / f"{key}.jpg"
        asset = poster if kind == "image" else temp / f"{key}.mp4"
        try:
            if kind == "video":
                await render.ffmpeg([*args, "-t", "120", "-vf",
                                     "scale='min(1920,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
                                     "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                                     "-movflags", "+faststart", str(asset)], timeout=180)
                args = ["-i", str(asset), "-map", "0:v:0", "-an"]
            await render.ffmpeg([*args, "-frames:v", "1", "-vf",
                                 "scale='min(2048,iw)':'min(2048,ih)':force_original_aspect_ratio=decrease",
                                 "-q:v", "2", str(poster)], timeout=60)
            if not asset.is_file() or not poster.is_file():
                raise ProviderError("Arquivo sem imagem")
        except (ProviderError, TimeoutError) as exc:
            raise HTTPException(422, "Não foi possível preparar esta mídia") from exc

        _, current, current_source, _ = _scene_visuals(job_id, index)
        if current_source != source or source.stat().st_mtime_ns != stamp or current["scenes"][index] != original_scene:
            raise HTTPException(409, "A cena mudou durante a importação. Tente de novo.")
        asset.replace(media_dir / asset.name)
        if kind == "video":
            poster.replace(media_dir / poster.name)
        current["scenes"][index]["media"] = {
            "kind": kind, "file": asset.name, "poster": poster.name,
            "name": Path(file.filename or "").name[:160], "credit": credit.strip()[:240], "source_url": source_url,
        }
        db.update_job(job_id, data={"script": current})
    _edited(job_id)
    db.log(job_id, f"Mídia externa aplicada à cena {index + 1}")
    return {"ok": True}


@router.delete("/api/jobs/{job_id}/scenes/{index}/media")
def remove_scene_media(job_id: str, index: int):
    _, script, _, _ = _scene_visuals(job_id, index)
    script["scenes"][index].pop("media", None)
    db.update_job(job_id, data={"script": script})
    _edited(job_id)
    return {"ok": True}


@router.post("/api/jobs/{job_id}/scenes/{index}/motion-preview")
async def preview_motion(job_id: str, index: int, body: dict = Body(...)):
    from .. import render
    from ..quality import scene_image

    job, script, source, folder = _scene_visuals(job_id, index)
    settings = _motion_settings(body)
    scene = script["scenes"][index]
    media = scene.get("media") or {}
    if media.get("kind") == "video":
        raise HTTPException(409, "O vídeo importado já ocupa a cena. Remova-o para usar Motion Canvas.")
    imported = render.scene_media_path(folder, media.get("file"))
    frame = (640, 360) if job["kind"] == "long" else (360, 640)
    previews = folder / "motion-previews"
    previews.mkdir(exist_ok=True)
    dest = previews / f"{index:02d}.mp4"
    try:
        with TemporaryDirectory(dir=previews) as directory:
            temp = Path(directory) / dest.name
            await render.motion_clip(imported or scene_image(source, folder, scene), 2, temp, frame, settings)
            temp.replace(dest)
    except (ProviderError, TimeoutError) as exc:
        raise HTTPException(422, str(exc) or "A prévia excedeu o tempo disponível") from exc
    return {"url": f"/api/jobs/{job_id}/file/motion-previews/{dest.name}?v={dest.stat().st_mtime_ns}"}


@router.post("/api/jobs/{job_id}/scenes/{index}/upscale-preview")
async def preview_upscale(job_id: str, index: int):
    from .. import quality

    _, _, source, folder = _scene_visuals(job_id, index)
    dest = quality.upscale_variant(source, folder)
    dest.parent.mkdir(exist_ok=True)
    if not dest.is_file():
        try:
            with TemporaryDirectory(dir=dest.parent) as directory:
                temp = Path(directory) / "upscaled.png"
                await quality.upscale(source, temp)
                temp.replace(dest)
        except (ProviderError, TimeoutError) as exc:
            raise HTTPException(422, str(exc) or "O upscale excedeu o tempo disponível") from exc
    return {"original": f"/api/jobs/{job_id}/file/images/{source.name}",
            "url": f"/api/jobs/{job_id}/file/upscales/{dest.name}"}


@router.put("/api/jobs/{job_id}/scenes/{index}/visuals")
def set_scene_visuals(job_id: str, index: int, body: dict = Body(...)):
    from ..quality import upscale_variant

    _, script, source, folder = _scene_visuals(job_id, index)
    scene = script["scenes"][index]
    if "motion" in body:
        if body["motion"] is None:
            scene.pop("motion", None)
        else:
            scene["motion"] = _motion_settings(body["motion"])
    if "upscale" in body:
        if body["upscale"] is True:
            variant = upscale_variant(source, folder)
            if not variant.is_file():
                raise HTTPException(409, "Gere a prévia de upscale primeiro")
            scene["upscale"] = variant.name
        else:
            scene.pop("upscale", None)
    db.update_job(job_id, data={"script": script})
    _edited(job_id)
    return {"ok": True}


@router.get("/api/jobs/{job_id}/timeline/audio/{track}/{index}")
async def timeline_audio(job_id: str, track: Literal["events", "beds"], index: int, pcm: bool = False,
                         k: str | None = None):
    job = _job_or_404(job_id)
    items = (job["data"].get("sound") or {}).get(track)
    if not isinstance(items, list):
        raise HTTPException(404)
    if k and not (0 <= index < len(items) and _sound_key(items[index]) == k):
        # a lista mudou depois que a página abriu (som removido ou refeito): procura o mesmo som
        index = next((i for i, it in enumerate(items) if _sound_key(it) == k), -1)
        if index < 0:
            raise HTTPException(410, "A timeline mudou: recarregue")
    if not 0 <= index < len(items):
        raise HTTPException(404)
    path = _timeline_sound_path(items[index], job_id)
    if path is None:
        raise HTTPException(404)
    if pcm and path.suffix != ".wav":
        from .. import render

        stat = path.stat()
        key = hashlib.sha256(f"{path}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
        folder = config.JOBS_DIR / job_id / "audio-previews"
        folder.mkdir(exist_ok=True)
        preview = folder / f"{key}.wav"
        if not preview.is_file():
            with TemporaryDirectory(dir=folder) as directory:
                temp = Path(directory) / preview.name
                try:
                    await render.ffmpeg(["-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "44100",
                                         "-c:a", "pcm_s16le", str(temp)], timeout=30)
                except ProviderError as exc:
                    raise HTTPException(422, "Não foi possível preparar a prévia do áudio") from exc
                temp.replace(preview)
        path = preview
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@router.post("/api/jobs/{job_id}/start-render")
async def start_render(job_id: str):
    """Aprova a timeline e inicia a renderização do vídeo."""
    job = _job_or_404(job_id)
    await worker.stop(job_id)
    if job["stages"].get("render", {}).get("status") == "done":
        # já renderizado: refaz o render com as mudanças da timeline
        published = bool(((job["data"].get("publish") or {}).get("video_id")))
        db.reset_from(job_id, "render")
        if published and "upload" in job["stages"]:
            db.update_job(job_id, stages={"upload": {"status": "done"}})
            db.log(job_id, "O vídeo já publicado não é substituído no YouTube: baixe o novo final.mp4", "warn",
                   stage="render")
    db.update_job(job_id, data={"approved_render": True}, status="queued")
    db.log(job_id, "Timeline aprovada; iniciando renderização", stage="render")
    worker.wake()
    return {"ok": True}


@router.post("/api/jobs/{job_id}/ai-correct")
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
    from ..providers import llm
    from ..pipeline import Ctx
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


def _get_sound_elements(job: dict) -> tuple[list[dict], list[dict]]:
    d = job.get("data") or {}
    snd = d.get("sound") or {}
    events = snd.get("events")
    beds = snd.get("beds")
    if isinstance(events, list) and isinstance(beds, list):
        return list(events), list(beds)
    tl = build_timeline(job)
    return list(tl.get("sound_events") or []), list(tl.get("sound_beds") or [])


async def _remix_sounds(job_id: str, d: dict, events: list[dict], beds: list[dict]) -> None:
    """Refaz o sfx.wav do job a partir dos efeitos e ambientes que sobraram na timeline."""
    from .. import sound

    mix = config.JOBS_DIR / job_id / "sfx.wav"
    total_dur = sum(d.get("durations") or []) or d.get("script", {}).get("total_duration") or 30.0
    providers = config.load()["providers"]
    style = d.get("sound", {}).get("style") or "neutro"

    rebuild_events = []
    for ev in events:
        file_path = ev.get("file")
        if file_path and Path(file_path).exists():
            rebuild_events.append({"file": Path(file_path), "at": ev["at"], "volume": ev.get("volume", 0.5)})
            continue
        try:
            f = await sound.library_sound(ev.get("type", "sfx"), style, providers)
        except Exception as exc:
            db.log(job_id, f"Efeito aos {float(ev.get('at', 0)):.1f}s ficou de fora do remix: {exc}", "warn")
            continue
        rebuild_events.append({"file": f, "at": ev["at"], "volume": ev.get("volume", 0.5)})

    rebuild_beds = []
    for b in beds:
        file_path = b.get("file")
        if file_path and Path(file_path).exists():
            rebuild_beds.append({"file": Path(file_path), "start": b["start"], "dur": b["dur"],
                                 "volume": b.get("volume", 0.15)})

    try:
        if rebuild_events or rebuild_beds:
            await sound.build_mix(rebuild_events, rebuild_beds, float(total_dur), mix)
        else:
            mix.unlink(missing_ok=True)
    except ProviderError as exc:
        raise HTTPException(500, "Não foi possível remixar a timeline") from exc
    d["sound"]["mix"] = str(mix) if mix.is_file() else None
    d["sound"]["mix_version"] = sound.MIX_VERSION


@router.post("/api/jobs/{job_id}/delete-sfx")
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
            name = ev.get("label") or ev.get("text") or ev.get("sound") or "Som"
            if abs(float(ev.get("at", 0)) - at_f) < 0.05 and (not label or name == label):
                removed_event = events.pop(i)
                break

    if not removed_event:
        raise HTTPException(404, "Efeito sonoro não encontrado")

    d.setdefault("sound", {})["events"] = events
    d["sound"]["beds"] = beds
    if removed_event.get("type") == "impact":  # o tranco visual do impacto sai junto com o som
        hit = float(removed_event.get("at", 0)) + 0.05
        d["sound"]["beats"] = [b for b in d["sound"].get("beats") or [] if abs(float(b) - hit) > 0.15]

    await _remix_sounds(job_id, d, events, beds)

    db.update_job(job_id, data=d)
    _edited(job_id)
    name = removed_event.get("label") or removed_event.get("type") or "som"
    db.log(job_id, f"Efeito sonoro '{name}' removido da timeline")
    return {"ok": True, "timeline": build_timeline(db.get_job(job_id))}


@router.post("/api/jobs/{job_id}/delete-ambience")
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

    await _remix_sounds(job_id, d, events, beds)

    db.update_job(job_id, data=d)
    _edited(job_id)
    name = removed_bed.get("sound") or "ambiente"
    db.log(job_id, f"Som ambiente '{name}' removido da timeline")
    return {"ok": True, "timeline": build_timeline(db.get_job(job_id))}


@router.post("/api/jobs/{job_id}/delete-scene")
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


@router.get("/api/sound-library")
def sound_library(style: str | None = None):
    """Sons pontuais da sua biblioteca (data/sound-packs) disponíveis para o estilo."""
    from .. import sound

    return {"sounds": sound.library(style), "folder": str(sound.USER_PACKS)}


@router.post("/api/jobs/{job_id}/add-sfx")
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
    text = body.get("text")
    vol = float(body.get("volume", 0.55))

    from .. import sound
    is_lib = sfx_type.startswith("lib:")
    sfx_type = sfx_type.removeprefix("lib:")
    try:
        if is_lib:  # som da sua biblioteca (data/sound-packs)
            sfile = sound.packed_sound(sfx_type, style, user_only=True)
            if sfile is None:
                raise HTTPException(404, f"Som '{sfx_type}' não está na biblioteca")
        elif not text and sfx_type in sound.LIBRARY_PRESETS:
            sfile = sound.packed_sound(sfx_type, style)
        else:
            sfile = None
        if sfile is None:
            if sfx_type in ("whoosh", "impact", "riser", "blip"):
                sfile = await sound.library_sound(sfx_type, style, cfg.get("providers", {}))
            else:
                sfile = await sound.generate(text or sfx_type, cfg.get("providers", {}), duration=1.2)
    except HTTPException:
        raise
    except Exception as exc:
        db.log(job_id, f"Não deu para gerar o efeito '{text or sfx_type}' ({exc}); usando um whoosh", "warn")
        sfile = await sound.library_sound("whoosh", style, cfg.get("providers", {}))

    new_event = {
        "file": str(sfile),
        "at": round(at, 2),
        "volume": vol,
        "type": "sfx" if is_lib else sfx_type,
        "label": sfx_type if is_lib else None,
        "text": text or sfx_type,
    }
    await _insert_timeline_sound(job_id, new_event, "events", total)
    db.log(job_id, f"Efeito '{sfx_type}' adicionado aos {at:.1f}s na timeline")
    return {"ok": True, "event": new_event}


_timeline_sound_lock = asyncio.Lock()
_AUDIO_IMPORT_FORMATS = {
    ".mp3": "mp3", ".wav": "wav", ".ogg": "ogg", ".opus": "ogg",
    ".flac": "flac", ".m4a": "mov", ".aac": "aac",
}
_AUDIO_IMPORT_LIMIT = 25 * 1024 * 1024


async def _insert_timeline_sound(job_id: str, item: dict, track: str, total: float) -> None:
    from .. import sound

    async with _timeline_sound_lock:
        job = _job_or_404(job_id)
        if job_id in worker.running:
            raise HTTPException(409, "Aguarde o processamento para editar a timeline")
        events, beds = _get_sound_elements(job)
        if track == "events":
            events.append(item)
            events.sort(key=lambda e: e["at"])
        else:
            beds.append(item)
            beds.sort(key=lambda b: b["start"])
        clean_events = [{**e, "volume": float(e.get("volume", 0.55))} for e in events if Path(e.get("file") or "").is_file()]
        clean_beds = [{**b, "volume": float(b.get("volume", 0.16))} for b in beds if Path(b.get("file") or "").is_file()]

        dest = config.JOBS_DIR / job_id / "sfx.wav"
        with TemporaryDirectory(dir=dest.parent) as directory:
            temp_mix = Path(directory) / dest.name
            await sound.build_mix(clean_events, clean_beds, total, temp_mix)
            temp_mix.replace(dest)
        snd = dict(job["data"].get("sound") or {})
        snd.update(events=events, beds=beds, mix=str(dest), mix_version=sound.MIX_VERSION)
        db.update_job(job_id, data={"sound": snd})
    _edited(job_id)


@router.post("/api/jobs/{job_id}/import-audio")
async def import_timeline_audio(job_id: str, file: UploadFile = File(...), at: float = Form(...),
                                track: Literal["events", "beds"] = Form("events")):
    """Adiciona áudio externo ao cursor da timeline."""
    from .. import render

    job = _job_or_404(job_id)
    total = sum(job["data"].get("durations") or [])
    if job.get("kind") not in ("short", "long") or total <= 0:
        raise HTTPException(400, "A importação está disponível em shorts e vídeos longos com narração gerada")
    if job_id in worker.running:
        raise HTTPException(409, "Aguarde o processamento para editar a timeline")
    if not math.isfinite(at) or not 0 <= at < total:
        raise HTTPException(400, "Posicione o cursor antes do fim do vídeo")
    filename = Path(file.filename or "").name
    demuxer = _AUDIO_IMPORT_FORMATS.get(Path(filename).suffix.lower())
    if demuxer is None:
        raise HTTPException(400, "Use MP3, WAV, OGG, Opus, FLAC, M4A ou AAC")
    if file.size is not None and file.size > _AUDIO_IMPORT_LIMIT:
        raise HTTPException(413, "O áudio deve ter até 25 MiB")

    folder = config.JOBS_DIR / job_id / "imported-audio"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid4().hex}.ogg"
    duration = total - at
    with TemporaryDirectory(dir=folder) as directory:
        source = Path(directory) / "source"
        normalized = Path(directory) / "audio.ogg"
        size = 0
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > _AUDIO_IMPORT_LIMIT:
                    raise HTTPException(413, "O áudio deve ter até 25 MiB")
                out.write(chunk)
        try:
            await render.ffmpeg(["-protocol_whitelist", "file", "-f", demuxer, "-i", str(source),
                                 "-map", "0:a:0", "-t", f"{min(duration, 300):.6f}", "-c:a", "libvorbis",
                                 "-ar", "44100", "-ac", "2", str(normalized)], timeout=60)
            if await render.ffprobe_duration(normalized) <= 0:
                raise ProviderError("Áudio vazio")
        except (ProviderError, ValueError):
            raise HTTPException(422, "Não foi possível ler o arquivo de áudio")
        normalized.replace(dest)

    label = Path(filename).stem[:120]
    item = {"file": str(dest), "imported": True}
    if track == "beds":
        item.update(sound=label, start=at, dur=duration, volume=0.16)
    else:
        item.update(type="sfx", label=label, at=at, volume=0.55)
    try:
        await _insert_timeline_sound(job_id, item, track, total)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    db.log(job_id, f"Áudio importado aos {at:.1f}s: {label}")
    return {"ok": True}


@router.post("/api/jobs/{job_id}/adjust-audio-levels")
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
    _edited(job_id)
    db.log(job_id, f"Níveis de áudio atualizados: Voz {voice:.1f}x, Música {bgm:.1f}x, SFX {sfx:.1f}x")
    return {"ok": True, "levels": levels}
