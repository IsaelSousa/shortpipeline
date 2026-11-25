"""Etapas de mídia: narração, imagens, capa e legendas."""

from __future__ import annotations


import asyncio
import json
import re
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from .. import render
from ..providers import ProviderError, image as image_p, tts
from .core import Ctx, SHORT_FRAME, THUMB_FRAME
from .writing import series_text

async def stage_narracao(c: Ctx) -> None:
    scenes = c.data["script"]["scenes"]
    base = c.ch["models"]["narracao"]
    attempts = [dict(base)]
    if base.get("fallback_provider"):
        attempts.append({**base, "provider": base["fallback_provider"], "model": base.get("fallback_model") or ""})
    adir = c.dir / "audio"
    adir.mkdir(exist_ok=True)
    target = c.data.get("narration_scene")
    if type(target) is int:
        current = c.data.get("narration") or {}
        opts = {**base, **(current.get("settings") or {}), "provider": current.get("provider") or base["provider"],
                "model": current.get("model") or base.get("model")}
        clips = [adir / f"{i:02d}.mp3" for i in range(len(scenes))]
        timings = scene_words(c)
        if not 0 <= target < len(scenes) or len(timings) != len(scenes) or not all(p.is_file() for p in clips):
            raise ProviderError("A locução original está incompleta. Refaça a narração inteira antes de editar uma cena.")
        with TemporaryDirectory(dir=c.dir) as directory:
            folder = Path(directory)
            clip = folder / "scene.mp3"
            c.detail(f"Refazendo só a voz da cena {target + 1}")
            timings[target] = await narrate_scene(c, scenes, target, clip, opts)
            mixed = folder / "narration.wav"
            durations = await render.build_narration([clip if i == target else p for i, p in enumerate(clips)], 0.25, mixed)
            clip.replace(clips[target])
            mixed.replace(c.dir / "narration.wav")
        save_narration(c, scenes, timings, durations, opts)
        return
    last: Exception | None = None
    for opts in attempts:
        # todas as cenas com a mesma voz: se o provedor falhar no meio, refaz tudo com o reserva
        clips, timings = [], []
        try:
            for i, sc in enumerate(scenes):
                c.detail(f"{opts['provider']}: cena {i + 1}/{len(scenes)}")
                dest = adir / f"{i:02d}.mp3"
                words = await narrate_scene(c, scenes, i, dest, opts)
                clips.append(dest)
                timings.append(words)
        except ProviderError as e:
            last = e
            c.log(f"Narração com {opts['provider']} falhou: {e}", "warn")
            continue
        durations = await render.build_narration(clips, 0.25, c.dir / "narration.wav")
        save_narration(c, scenes, timings, durations, opts)
        return
    raise ProviderError(f"Narração falhou em todos os provedores: {last}")


async def narrate_scene(c: Ctx, scenes: list[dict], index: int, dest: Path, opts: dict) -> list[dict]:
    call = {**opts, "previous_text": scenes[index - 1]["narration"] if index else "",
            "next_text": scenes[index + 1]["narration"] if index + 1 < len(scenes) else ""}
    narration = scenes[index]["narration"]
    words = await tts.synthesize(narration, dest, call, c.cfg["providers"])
    plain = tts.strip_tags(narration)
    if not words:
        words = tts.even_words(plain, await render.ffprobe_duration(dest))
    return tts.restore_punctuation(plain, words)


def save_narration(c: Ctx, scenes: list[dict], timings: list, durations: list[float], opts: dict) -> None:
    (c.dir / "timings.json").write_text(json.dumps(timings, ensure_ascii=False))
    chars = sum(len(tts.strip_tags(sc["narration"])) for sc in scenes)
    chapters, start = [], 0.0
    for sc, duration in zip(scenes, durations):
        if sc.get("chapter"):
            chapters.append({"start": round(start, 2), "title": sc["chapter"]})
        start += duration
    keys = ("voice_id", "voice_name", "stability", "similarity_boost", "style", "speed", "rate", "pitch")
    settings = {key: opts[key] for key in keys if key in opts}
    c.save(durations=durations, duration=round(start, 2), chapters=chapters if c.is_long else [],
           narration={"provider": opts["provider"], "model": opts.get("model"), "chars": chars, "settings": settings},
           narration_scene=None)
    c.log(f"Narração pronta: {start:.1f}s, {chars} caracteres ({opts['provider']})")


async def gen_image(c: Ctx, prompt: str, dest: Path, label: str, aspect: str | None = None,
                    refs: list[Path] | None = None) -> Path:
    """Gera uma imagem com o provedor da etapa Imagens, caindo para a reserva se falhar."""
    m = c.ch["models"]["imagens"]
    timeout = int(c.cfg["general"].get("image_timeout") or 420)
    attempts = [(m["provider"], m.get("model") or "")]
    if m.get("fallback_provider"):
        attempts.append((m["fallback_provider"], m.get("fallback_model") or ""))
    last = None
    for prov, model in attempts:
        try:
            t0 = time.time()
            p = await image_p.generate(prov, model, prompt, dest, timeout=timeout, providers_cfg=c.cfg["providers"],
                                       aspect=aspect or c.aspect, refs=refs if prov != "placeholder" else None)
            c.log(f"{label} gerada por {prov} em {time.time() - t0:.0f}s" +
                  (" (com referência)" if refs and prov != "placeholder" else ""))
            return p
        except ProviderError as e:
            last = e
            c.log(f"{label}: {prov} falhou: {e}", "warn")
    raise ProviderError(f"{label} falhou em todos os provedores: {last}")


def image_style(c: Ctx, aspect: str | None = None) -> str:
    style = c.ch["prompts"].get("image_style", "")
    if (aspect or c.aspect) == "16:9":
        style = re.sub(r"vertical\s*9:16", "horizontal 16:9", style, flags=re.I)
    return style


def _cast(script: dict) -> dict[str, str]:
    """{nome normalizado: aparência} dos personagens do roteiro."""
    out = {}
    for ch in script.get("characters") or []:
        if isinstance(ch, dict) and ch.get("name") and ch.get("look"):
            out[_norm(ch["name"])] = f"{ch['name']}: {ch['look']}"
    return out


def _scene_cast(sc: dict, cast: dict) -> list[str]:
    return [k for k in (_norm(n) for n in sc.get("characters") or [] if isinstance(n, str)) if k in cast]


async def stage_imagens(c: Ctx) -> None:
    scenes = c.data["script"]["scenes"]
    style = image_style(c)
    idir = c.dir / "images"
    idir.mkdir(exist_ok=True)
    sem = asyncio.Semaphore(max(1, int(c.cfg["general"].get("image_concurrency") or 2)))
    done = 0
    images: list[str | None] = [None] * len(scenes)
    cr = c.creative()
    cast = _cast(c.data["script"]) if cr.get("characters", True) else {}
    use_refs = bool(cast) and cr.get("character_refs", True)
    # a primeira imagem de cada personagem vira a referência das outras cenas em que ele aparece
    anchor: dict[str, int] = {}
    for i, sc in enumerate(scenes):
        for k in _scene_cast(sc, cast):
            anchor.setdefault(k, i)

    async def one(i: int, sc: dict):
        nonlocal done
        existing = [p for p in idir.glob(f"{i:02d}.*") if p.suffix.lower() in image_p.IMAGE_EXTS]
        if existing:  # retomada: não refaz imagem já gerada
            images[i] = str(existing[0])
        else:
            who = _scene_cast(sc, cast)
            prompt = sc.get("image_prompt") or sc["narration"]
            if who:
                prompt += ". Characters (keep exactly this look): " + "; ".join(cast[k] for k in who)
            prompt += f". Style: {style}"
            refs = list(dict.fromkeys(Path(images[anchor[k]]) for k in who
                                      if anchor[k] != i and images[anchor[k]])) if use_refs else []
            async with sem:
                images[i] = str(await gen_image(c, prompt, idir / f"{i:02d}", f"Imagem {i + 1}", refs=refs[:2]))
        done += 1
        c.detail(f"{done}/{len(scenes)} imagens")

    # 1º as cenas onde cada personagem aparece pela primeira vez (e as sem personagem), depois o resto com referência
    first = [i for i, sc in enumerate(scenes) if not use_refs or all(anchor[k] == i for k in _scene_cast(sc, cast))]
    rest = [i for i in range(len(scenes)) if i not in first]
    await asyncio.gather(*(one(i, scenes[i]) for i in first))
    if rest:
        c.log(f"Personagens fixos: {', '.join(v.split(':')[0] for v in cast.values())} — "
              f"{len(rest)} imagens com referência")
    await asyncio.gather(*(one(i, scenes[i]) for i in rest))
    c.save(images=images)


def default_cover_text(script: dict) -> str:
    import re
    title = re.sub(r"#\S+", "", script.get("title") or "").strip(" -|:")
    words = title.split()
    return " ".join(words[:5])


async def stage_capa(c: Ctx) -> None:
    cov = c.ch.get("cover") or {}
    if not cov.get("enabled"):
        c.save(cover=None)
        c.log("Capa desligada para este canal")
        return
    script = c.data["script"]
    cdir = c.dir / "cover"
    cdir.mkdir(exist_ok=True)
    bg = next((p for p in cdir.glob("bg.*") if p.suffix.lower() in image_p.IMAGE_EXTS), None)
    frame = THUMB_FRAME if c.is_long else SHORT_FRAME
    if bg is None and c.kind == "corte" and (c.ch.get("clips") or {}).get("cover_from_frame", True):
        bg = cdir / "bg.png"
        t = float(c.data.get("duration") or 10) * 0.35
        await render.ffmpeg(["-ss", f"{t:.2f}", "-i", c.data["reframed"], "-frames:v", "1", str(bg)])
        c.log(f"Fundo da capa: frame do corte em {t:.1f}s")
    if bg is None:  # retomada: só gera o fundo se ainda não existir
        if cov.get("source") == "scene" and c.data.get("images"):
            idx = max(1, min(int(cov.get("scene") or 1), len(c.data["images"]))) - 1
            src = Path(c.data["images"][idx])
            bg = cdir / f"bg{src.suffix}"
            import shutil
            shutil.copy2(src, bg)
            c.log(f"Fundo da capa: imagem da cena {idx + 1}")
        else:
            c.detail("gerando imagem da capa")
            base = script.get("cover_prompt") or script["scenes"][0].get("image_prompt") or script.get("title")
            aspect = "16:9" if c.is_long else "9:16"
            kind_txt = "YouTube video thumbnail" if c.is_long else "YouTube Shorts cover"
            prompt = (f"{base}. Style: {image_style(c, aspect)}. Composition: striking {kind_txt}, one strong "
                      "central subject, dramatic lighting, high contrast, keep the upper area simple for a big title, "
                      "no text.")
            bg = await gen_image(c, prompt, cdir / "bg", "Imagem da capa", aspect)
    text = ""
    if cov.get("text_enabled", True):
        text = (c.data.get("cover_text_override") or script.get("cover_text") or default_cover_text(script)).strip()
    c.detail("montando capa")
    png, jpg = cdir / "cover.png", cdir / "cover.jpg"
    opts = dict(cov)
    if c.data.get("series_no") and c.creative().get("series_badge"):
        opts["badge"] = series_text(c.creative()["series_badge"], int(c.data["series_no"]))
        opts.setdefault("highlight_color", c.ch["video"].get("highlight_color"))
    await render.build_cover(Path(bg), text, opts, png, jpg, frame)
    c.save(cover={"image": str(png), "jpg": str(jpg), "bg": str(bg), "text": text})
    c.log(f"Capa pronta{': ' + text if text else ' (sem texto)'}")


async def stage_legendas(c: Ctx) -> None:
    ass = c.dir / "captions.ass"
    if c.kind == "corte":
        if not (c.ch.get("clips") or {}).get("captions", True):
            c.save(captions=None)
            c.log("Legendas desligadas para cortes neste canal")
            return
        render.build_ass(c.data.get("words") or [], c.ch["video"], ass)
        c.save(captions=str(ass))
        c.log(f"Legendas: {len(c.data.get('words') or [])} palavras")
        return
    if c.is_long and not c.long_opts().get("captions"):
        c.save(captions=None)
        c.log("Legendas desligadas para vídeos longos neste canal")
        return
    timings = json.loads((c.dir / "timings.json").read_text())
    durations = c.data["durations"]
    words, offset = [], 0.0
    for scene_words, d in zip(timings, durations):
        for w in scene_words:
            words.append({"text": w["text"], "start": w["start"] + offset, "end": w["end"] + offset})
        offset += d
    render.build_ass(words, c.ch["video"], ass, c.frame,
                     size=c.long_opts().get("caption_size") if c.is_long else None)
    c.save(captions=str(ass))
    c.log(f"Legendas: {len(words)} palavras")

def scene_words(c: Ctx) -> list[list[dict]]:
    path = c.dir / "timings.json"
    return json.loads(path.read_text()) if path.exists() else []


def _norm(w: str) -> str:
    import unicodedata
    w = unicodedata.normalize("NFKD", w.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(ch for ch in w if not unicodedata.combining(ch)))


def find_word_time(words: list[dict], target: str) -> float | None:
    """Tempo (relativo à cena) da palavra pedida pela IA; aceita prefixo ("abriu" casa com "abriu-se")."""
    t = _norm((target or "").split()[0] if target else "")
    if not t:
        return None
    for w in words:
        if _norm(w["text"]) == t:
            return w["start"]
    for w in words:
        nw = _norm(w["text"])
        if nw.startswith(t) or (len(nw) > 3 and t.startswith(nw)):
            return w["start"]
    return None


def plan_shots(words: list[dict], duration: float, every: float) -> list[float]:
    """Divide a cena em planos de ~`every` segundos, cortando sempre no início de uma palavra."""
    if every <= 0 or duration < every * 1.6:
        return []
    cuts, t = [], every
    starts = [w["start"] for w in words]
    while t < duration - every * 0.6:
        near = min(starts, key=lambda s: abs(s - t)) if starts else t
        cut = near if abs(near - t) < 0.7 and near - (cuts[-1] if cuts else 0) > 1.2 else t
        if duration - cut > 1.0:
            cuts.append(round(cut, 3))
        t = cut + every
    bounds = [0.0] + cuts + [duration]
    return [round(bounds[i + 1] - bounds[i], 3) for i in range(len(bounds) - 1)]
