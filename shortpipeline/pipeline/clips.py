"""Cortes de vídeos longos: download, transcrição, seleção e recorte."""

from __future__ import annotations


import asyncio
import bisect
import json
import shutil
import time
from pathlib import Path

from .. import config, db, reframe, render
from ..providers import ProviderError, llm, transcribe
from .core import Ctx, WaitingApproval

# ------------------------------------------------------------------ cortes
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}


async def stage_download(c: Ctx) -> None:
    inp = c.data.get("input") or {}
    src = next((p for p in c.dir.glob("source.*") if p.suffix.lower() in VIDEO_EXTS), None)
    info: dict = {}
    if src:
        c.log("Vídeo de origem já baixado")
    elif inp.get("file"):
        up = Path(inp["file"])
        if not up.exists():
            raise ProviderError("Arquivo enviado não encontrado")
        src = c.dir / f"source{up.suffix.lower()}"
        shutil.move(str(up), src)
        info = {"title": Path(inp.get("name") or up.name).stem}
        c.log(f"Arquivo recebido: {inp.get('name') or up.name}")
    elif inp.get("url"):
        info = await asyncio.to_thread(_ytdlp, inp["url"], c)
        src = next((p for p in c.dir.glob("source.*") if p.suffix.lower() in VIDEO_EXTS), None)
        if not src:
            raise ProviderError("yt-dlp terminou sem gerar o vídeo")
        c.log(f"Baixado: {info.get('title')}")
    else:
        raise ProviderError("Fonte sem link nem arquivo")
    duration = await render.ffprobe_duration(src)
    prev = c.data.get("source") or {}
    source = {**prev, **{k: v for k, v in info.items() if v}, "path": str(src), "duration": round(duration, 1)}
    c.save(source=source)
    if source.get("title"):
        c.job = db.update_job(c.job["id"], topic=source["title"])
    c.log(f"Duração: {duration / 60:.1f} min")


def _ytdlp(url: str, c: Ctx) -> dict:
    import yt_dlp

    last = {"t": 0.0}

    def hook(d):
        if d.get("status") == "downloading" and time.time() - last["t"] > 1.5:
            last["t"] = time.time()
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            pct = f"{d.get('downloaded_bytes', 0) / total * 100:.0f}%" if total else ""
            c.detail(f"baixando {pct}".strip())

    opts = {
        "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "outtmpl": str(c.dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
        "progress_hooks": [hook],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as e:
        raise ProviderError(f"Download falhou: {e}")
    return {"title": info.get("title"), "uploader": info.get("uploader"), "url": info.get("webpage_url") or url,
            "thumbnail": info.get("thumbnail")}


async def stage_transcricao(c: Ctx) -> None:
    opts = c.cfg.get("transcription") or {}
    src = Path(c.data["source"]["path"])
    t0 = time.time()
    c.log(f"Transcrevendo com {opts.get('provider')}{' / ' + opts['model'] if opts.get('model') else ''}")
    media_cues = {**(c.ch.get("clips") or {}), **(c.data.get("clip_opts") or {})}.get("media_cues")
    if media_cues and not await render.has_audio_stream(src):
        tr = {"words": [], "provider": "sem áudio"}
    else:
        tr = await transcribe.transcribe(src, opts, c.cfg["providers"], progress=c.detail)
    if not tr["words"] and not media_cues:
        raise ProviderError("A transcrição voltou vazia (o vídeo tem fala?)")
    (c.dir / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False))
    c.save(transcript={"words": len(tr["words"]), "provider": tr["provider"], "language": tr.get("language")})
    c.log(f"Transcrição: {len(tr['words'])} palavras em {time.time() - t0:.0f}s ({tr['provider']})")


def clip_words(words: list[dict], start: float, end: float) -> list[dict]:
    """Palavras dentro do corte, com o tempo relativo ao início do corte."""
    return [{"text": w["text"], "start": round(w["start"] - start, 3), "end": round(w["end"] - start, 3)}
            for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


def snap_clip(words: list[dict], start: float, end: float, min_s: float, max_s: float) -> tuple[float, float] | None:
    """Ajusta o corte para começar no início de uma palavra e terminar no fim de outra."""
    if not words:
        return None
    starts = [w["start"] for w in words]
    i = bisect.bisect_left(starts, start)
    cand = range(max(0, i - 3), min(len(words), i + 3))
    a = min(cand, key=lambda k: abs(words[k]["start"] - start))
    ends = [w["end"] for w in words]
    j = bisect.bisect_left(ends, end)
    cand = range(max(a, j - 3), min(len(words), j + 3))
    b = min(cand, key=lambda k: abs(words[k]["end"] - end)) if cand else a
    s, e = words[a]["start"], words[b]["end"]
    if e - s > max_s:  # longo demais: termina na última palavra que cabe
        k = b
        while k > a and words[k]["end"] - s > max_s:
            k -= 1
        e = words[k]["end"]
    if e - s < min_s * 0.6:
        return None
    return max(0.0, s - 0.15), e + 0.4


async def stage_selecao(c: Ctx) -> None:
    tr = json.loads((c.dir / "transcript.json").read_text())
    words = tr["words"]
    opts = {**(c.ch.get("clips") or {}), **(c.data.get("clip_opts") or {})}
    count = int(opts.get("count") or 5)
    min_s, max_s = float(opts.get("min_seconds") or 25), float(opts.get("max_seconds") or 60)
    picked = c.data.get("approved_clip_candidates")
    if picked is None:
        if c.data.get("clip_candidates") and opts.get("review_selection"):
            raise WaitingApproval()
        lines = transcribe.transcript_lines(words)
        text = "\n".join(f"[{ln['start']:.1f}] {ln['text']}" for ln in lines)
        instr = (c.data.get("instructions") or "").strip()
        prompt = c.fmt(c.ch["prompts"].get("clip_select") or config.CLIP_SELECT_PROMPT, transcript=text, count=count,
                       min_seconds=int(min_s), max_seconds=int(max_s),
                       source_title=(c.data.get("source") or {}).get("title") or "",
                       instructions=f"- Instruções extras: {instr}" if instr else "")
        if opts.get("media_cues"):
            c.detail("Analisando mudanças visuais e picos de áudio")
            cues = await render.clip_media_cues(Path(c.data["source"]["path"]))
            if any(cues.values()):
                prompt += "\n\nMarcas aproximadas em segundos para investigar junto com a transcrição. " \
                          "Uma mudança de plano ou pico de áudio, por si só, não prova que o trecho é bom.\n" + json.dumps(cues)
            elif not words:
                raise ProviderError("A fonte não tem fala nem mudanças de plano ou picos de áudio detectáveis")
        out = await c.text("selecao", prompt)
        raw = llm.extract_json(out).get("clips") or []
        if not raw:
            raise ProviderError("A IA não escolheu nenhum corte")
        picked, used = [], []
        for cl in sorted(raw, key=lambda x: -float(x.get("score") or 0)):
            try:
                start, end = float(cl["start"]), float(cl["end"])
                source_duration = c.data["source"].get("duration") or end
                if not (0 <= start < end <= float(source_duration) + 0.05):
                    continue
                if opts.get("media_cues") and not clip_words(words, start, end):
                    snapped = (start, end) if min_s <= end - start <= max_s else None
                else:
                    snapped = snap_clip(words, start, end, min_s, max_s)
            except (KeyError, TypeError, ValueError):
                continue
            if not snapped:
                continue
            s, e = snapped[0], min(snapped[1], float(source_duration))
            if any(s < ue and e > us for us, ue in used):
                continue
            used.append((s, e))
            picked.append({**cl, "start": s, "end": e})
            if len(picked) >= count:
                break
        if not picked:
            raise ProviderError("Nenhum corte válido (durações fora do limite ou sobrepostos)")
        if opts.get("review_selection"):
            c.save(clip_candidates=picked)
            raise WaitingApproval()
    # refazer a seleção descarta cortes que ainda não começaram
    for old in db.list_children(c.job["id"]):
        if old["status"] in ("queued", "failed", "canceled"):
            db.delete_job(old["id"])
            shutil.rmtree(config.JOBS_DIR / old["id"], ignore_errors=True)
    source = c.data["source"]
    created = []
    for cl in sorted(picked, key=lambda item: item["start"]):
        s, e = cl["start"], cl["end"]
        script = {"title": cl.get("title") or "Corte", "description": cl.get("description") or "",
                  "tags": cl.get("tags") or [], "cover_text": cl.get("cover_text") or ""}
        clip = {"start": round(s, 2), "end": round(e, 2), "score": cl.get("score"), "reason": cl.get("reason")}
        child = db.create_job(c.channel_id, script["title"], kind="corte", parent_id=c.job["id"], data={
            "source_job": c.job["id"], "source_video": source["path"], "source_title": source.get("title"),
            "clip": clip, "script": script, "words": clip_words(words, s, e)})
        db.log(child["id"], f"Corte de {s:.1f}s a {e:.1f}s de \"{source.get('title')}\" (nota {cl.get('score')})")
        created.append({"id": child["id"], **clip, "title": script["title"]})
        c.log(f"Corte {e - s:.0f}s (nota {cl.get('score')}): {script['title']}")
    c.save(clips=created, clip_candidates=[], approved_clip_candidates=None)
    c.log(f"{len(created)} cortes criados e enviados para a fila")


async def stage_recorte(c: Ctx) -> None:
    clip = c.data["clip"]
    src = Path(c.data["source_video"])
    if not src.exists():
        raise ProviderError("Vídeo de origem não existe mais (a fonte foi excluída?)")
    dur = clip["end"] - clip["start"]
    raw = c.dir / "clip_raw.mp4"
    c.detail("recortando")
    inputs = ["-ss", f"{clip['start']:.3f}", "-i", str(src)]
    if not await render.has_audio_stream(src):
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-map", "0:v:0", "-map", "1:a:0"]
    await render.ffmpeg([*inputs, "-t", f"{dur:.3f}",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", "30",
                         "-c:a", "aac", "-b:a", "192k", str(raw)])
    mode = (c.ch.get("clips") or {}).get("reframe") or "face"
    c.detail("reenquadrando")
    dst = c.dir / "reframed.mp4"
    framing = clip.get("framing") or {}
    if framing.get("mode") == "manual":
        await asyncio.to_thread(reframe.reframe_manual, raw, dst, framing["x"], framing["y"])
        used = "manual"
    else:
        used = await asyncio.to_thread(reframe.reframe, raw, dst, framing.get("mode") or mode, c.log)
    raw.unlink(missing_ok=True)
    c.save(reframed=str(dst), reframe_mode=used, duration=round(dur, 2))
    c.log(f"Corte de {dur:.1f}s reenquadrado ({used})")
