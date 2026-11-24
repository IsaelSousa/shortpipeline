"""As etapas do pipeline. Cada etapa lê/grava na pasta do job e no campo `data`."""

from __future__ import annotations

import asyncio
import bisect
import json
import math
import re
import shutil
import time
from pathlib import Path

from . import config, db, learn, reframe, render, sound, upload
from .providers import ProviderError, image as image_p, llm, transcribe, tts

SHORT_FRAME = (1080, 1920)
LONG_FRAME = (1920, 1080)
THUMB_FRAME = (1280, 720)


class WaitingApproval(Exception):
    """A etapa de revisão para o job até alguém aprovar no painel."""


class Ctx:
    def __init__(self, job: dict, cfg: dict):
        self.job = job
        self.cfg = cfg
        self.channel_id = job["channel"]
        self.ch = config.channel(cfg, self.channel_id)
        self.dir = config.JOBS_DIR / job["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stage = None
        self.kind = job.get("kind") or "short"

    @property
    def is_long(self) -> bool:
        return self.kind == "long"

    @property
    def frame(self) -> tuple[int, int]:
        return LONG_FRAME if self.is_long else SHORT_FRAME

    @property
    def aspect(self) -> str:
        return "16:9" if self.is_long else "9:16"

    def creative(self) -> dict:
        return self.ch.get("creative") or {}

    def insights(self) -> str:
        """Aprendizados escritos à mão + os aprendidos do Analytics."""
        parts = [(self.creative().get("insights") or "").strip()]
        if self.creative().get("auto_learn", True):
            parts.append((learn.load(self.channel_id).get("insights") or "").strip())
        return "\n".join(p for p in parts if p)

    def long_opts(self) -> dict:
        lo = dict(self.ch.get("long") or {})
        if self.data.get("long_minutes"):
            lo["target_minutes"] = self.data["long_minutes"]
        return lo

    @property
    def data(self) -> dict:
        return self.job["data"]

    def save(self, **data) -> None:
        self.job = db.update_job(self.job["id"], data=data)

    def log(self, msg: str, level: str = "info") -> None:
        db.log(self.job["id"], msg, level, self.stage)

    def detail(self, text: str) -> None:
        self.job = db.set_stage(self.job["id"], self.stage, detail=text)

    def fmt(self, template: str, **extra) -> str:
        v = self.ch["video"]
        if self.is_long:
            lo = self.long_opts()
            minutes = float(lo.get("target_minutes") or 8)
            seconds = int(minutes * 60)
            scenes = max(6, math.ceil(seconds / float(lo.get("seconds_per_image") or 15)))
        else:
            minutes = round((v.get("target_seconds") or 45) / 60, 1)
            seconds = int(v.get("target_seconds") or 45)
            scenes = v.get("scenes") or 6
        values = {"channel": self.ch["name"], "niche": self.ch.get("niche", ""), "language": self.ch.get("language"),
                  "scenes": scenes, "seconds": seconds, "minutes": f"{minutes:g}", "words": int(seconds * 2.5),
                  "topic": self.job.get("topic") or ""}
        values.update(extra)
        return template.format(**values)

    async def text(self, stage_key: str, prompt: str) -> str:
        """Chama o modelo da etapa; se falhar, tenta o fallback configurado."""
        m = self.ch["models"][stage_key]
        attempts = [(m["provider"], m.get("model") or "")]
        if m.get("fallback_provider"):
            attempts.append((m["fallback_provider"], m.get("fallback_model") or ""))
        timeout = int(self.cfg["general"].get("llm_timeout") or 300)
        last: Exception | None = None
        for prov, model in attempts:
            self.log(f"Chamando {prov}{' / ' + model if model else ''}")
            try:
                t0 = time.time()
                out = await llm.generate(prov, model, prompt, timeout=timeout, providers_cfg=self.cfg["providers"])
                self.log(f"{prov} respondeu em {time.time() - t0:.0f}s")
                return out
            except ProviderError as e:
                last = e
                self.log(f"{prov} falhou: {e}", "warn")
        raise ProviderError(str(last))


# ------------------------------------------------------------------ etapas
async def stage_ideia(c: Ctx) -> None:
    if c.job.get("topic"):
        c.log("Pauta definida manualmente")
        return
    src = c.ch.get("idea") or {}
    if src.get("source") == "rss" and src.get("rss_urls"):
        item = await _rss_pick(c, src["rss_urls"])
        if item:
            topic = f"{item['title']}. {item['summary']}".strip()[:900]
            c.job = db.update_job(c.job["id"], topic=topic, data={"source": item})
            db.mark_source_used(c.channel_id, item["link"])
            c.log(f"Pauta do RSS: {item['title']}")
            return
        c.log("Nenhuma notícia nova no RSS; pedindo pauta para a IA", "warn")
    history = "\n".join(f"- {t}" for t in db.recent_titles(c.channel_id)) or "(nenhum ainda)"
    prompt = c.fmt(c.ch["prompts"]["idea"], history=history)
    if c.insights():
        prompt += "\n\nO que já funcionou no canal (use como guia, sem copiar temas):\n" + c.insights()
    if c.is_long:
        prompt += (f"\n\nA pauta é para um VÍDEO LONGO de uns {c.long_opts().get('target_minutes')} minutos: "
                   "escolha um tema com profundidade para sustentar esse tempo.")
    out = await c.text("ideia", prompt)
    topic = llm.extract_json(out).get("topic", "").strip()
    if not topic:
        raise ProviderError("A IA não devolveu uma pauta")
    c.job = db.update_job(c.job["id"], topic=topic)
    c.log(f"Pauta: {topic}")


async def _rss_pick(c: Ctx, urls: list[str]) -> dict | None:
    import feedparser
    import httpx

    items = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 shortpipeline"}) as client:
        for url in urls:
            try:
                r = await client.get(url)
                feed = feedparser.parse(r.content)
            except Exception as e:
                c.log(f"RSS falhou ({url}): {e}", "warn")
                continue
            for e in feed.entries[:15]:
                link = e.get("link") or e.get("id")
                if not link or db.source_used(c.channel_id, link):
                    continue
                import re
                summary = re.sub(r"<[^>]+>", " ", e.get("summary", ""))
                summary = re.sub(r"\s+", " ", summary).strip()[:600]
                ts = time.mktime(e.published_parsed) if e.get("published_parsed") else 0
                items.append({"title": e.get("title", ""), "summary": summary, "link": link, "ts": ts,
                              "feed": url})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[0] if items else None


COVER_FIELDS_HINT = (
    "\n\nInclua também no JSON os campos \"cover_text\" (texto da capa do short: 2 a 5 palavras de impacto, "
    "com a palavra mais forte entre [colchetes]) e \"cover_prompt\" (prompt EM INGLÊS para uma imagem de capa "
    "chamativa, com um elemento central forte e sem texto)."
)


def pick_format(c: Ctx) -> str:
    """Alterna os formatos do canal: escolhe o menos usado nos últimos vídeos."""
    formats = [f for f in c.creative().get("formats") or [] if f.strip()]
    if not formats:
        return ""
    recent = [j["data"].get("format") for j in db.list_jobs(c.channel_id, limit=30) if j["id"] != c.job["id"]]
    scores = learn.load(c.channel_id).get("format_scores") or {} if c.creative().get("auto_learn", True) else {}
    # o que rende mais volta mais vezes, mas sem repetir sempre o mesmo (cada uso recente pesa 1)
    return min(formats, key=lambda f: (recent.count(f) - 3 * float(scores.get(f, 0.5)), formats.index(f)))


def rating_on(c: Ctx) -> bool:
    """Selo de nota no fim do short (ex.: "HYPE REAL 8/10", "DIFICULDADE 3/10")."""
    return bool(c.creative().get("rating_meter")) and c.kind == "short"


def series_text(template: str, n: int) -> str:
    return (template or "").replace("{nnn}", f"{n:03d}").replace("{n}", str(n))


def assign_series(c: Ctx) -> int | None:
    """Número da série (Caso #N) do short: o próximo depois do maior já usado no canal."""
    cr = c.creative()
    if c.kind != "short" or not (cr.get("series_name") or cr.get("series_badge")):
        return None
    if c.data.get("series_no"):
        return int(c.data["series_no"])
    used = [int(j["data"]["series_no"]) for j in db.list_jobs(c.channel_id, limit=2000)
            if j["id"] != c.job["id"] and j["data"].get("series_no") and j["status"] != "canceled"]
    n = max(used) + 1 if used else max(1, int(cr.get("series_start") or 1))
    c.save(series_no=n)
    return n


def brand_rules(c: Ctx) -> str:
    """Regras fixas da marca, para o revisor não apagar."""
    cr = c.creative()
    rules = []
    if cr.get("persona"):
        rules.append(f"narrador fixo: {cr['persona']}")
    if cr.get("signoff"):
        rules.append(f'a narração termina com o bordão "{cr["signoff"]}"')
    if rating_on(c):
        rules.append('o JSON tem "rating" (0 a 10)')
    return ("\nRegras fixas do canal (mantenha no roteiro, não são problema): " + "; ".join(rules) + "\n") if rules else ""


def creative_hint(c: Ctx, fmt: str) -> str:
    cr = c.creative()
    n = c.ch["models"]["narracao"]
    lines = ["\n\nDIREÇÃO CRIATIVA (siga e inclua os campos extras no JSON):"]
    if fmt:
        others = [f for f in cr.get("formats") or [] if f.strip() and f != fmt]
        lines.append(f"- Formato sugerido: {fmt}. Adapte a estrutura ao formato."
                     + (f" Se ele não combinar com a pauta, troque pelo que combinar melhor desta lista: {others}. "
                        'Diga no JSON o formato usado em "format" (texto exato da lista).' if others else ""))
    if cr.get("sound", True):
        lines.append(
            '- Em cada cena, além de narration e image_prompt, inclua: "sfx": até 2 efeitos sonoros '
            '[{"word": "palavra EXATA da narração onde o som acontece", "sound": "descrição curta do som EM INGLÊS"}]; '
            '"ambience": som ambiente da cena EM INGLÊS (ex.: "heavy rain on a window, distant thunder") ou ""; '
            '"beat": "scare" (susto), "reveal" (revelação) ou "" — no máximo 2 beats no vídeo inteiro, no momento mais forte.')
    if cr.get("emotion_tags", True) and n.get("provider") == "elevenlabs" and (n.get("model") or "").startswith("eleven_v3"):
        lines.append(
            "- Na narração, use tags de emoção do ElevenLabs entre colchetes, em inglês, antes das frases que pedem "
            "(com moderação, 3 a 6 no vídeo): [whispers], [scared], [nervous], [sighs], [gasps], [laughs], [excited], "
            "[sarcastic], [shouting]. Nunca coloque tags no título, descrição ou cover_text.")
    if cr.get("loop_ending", True) and not c.is_long:
        lines.append("- A última frase deve emendar naturalmente na primeira, para o vídeo funcionar em loop "
                     "(sem pedir like, inscrição ou comentário no final).")
    if cr.get("persona"):
        lines.append(f"- Narrador fixo do canal (mantenha a voz e o jeito dele, sem atrasar o gancho): {cr['persona']}")
    if cr.get("signoff"):
        lines.append(f'- Termine a narração com o bordão do canal, exatamente assim: "{cr["signoff"]}". '
                     "Ele é a última frase da última cena.")
    if rating_on(c):
        lines.append('- Inclua no JSON "rating": inteiro de 0 a 10, uma nota honesta para '
                     f"{cr.get('rating_criteria') or 'o tema do vídeo'} (ela aparece num selo no fim do vídeo).")
    if cr.get("characters", True):
        lines.append(
            '- Inclua no JSON "characters": [{"name": "nome curto", "look": "aparência FIXA EM INGLÊS: idade, gênero, '
            'rosto, cabelo, roupa"}] com os personagens que aparecem nas imagens (no máximo 3; [] se não houver), '
            'e em cada cena "characters": ["nomes que aparecem NA IMAGEM dessa cena"].')
    if c.insights():
        lines.append("- O que já funcionou no canal (aplique):\n" + c.insights())
    return "\n".join(lines) if len(lines) > 1 else ""


async def stage_roteiro(c: Ctx) -> None:
    template = c.ch["prompts"].get("long_script") if c.is_long else None
    prompt = c.fmt(template or c.ch["prompts"]["script"])
    if "cover_text" not in prompt:
        prompt += COVER_FIELDS_HINT
    fmt = c.data.get("format") or pick_format(c)
    prompt += creative_hint(c, fmt)
    if fmt:
        c.save(format=fmt)
        c.log(f"Formato: {fmt}")
    out = await c.text("roteiro", prompt)
    script = llm.extract_json(out)
    scenes = [s for s in script.get("scenes", []) if s.get("narration")]
    if not scenes:
        raise ProviderError("Roteiro sem cenas")
    script["scenes"] = scenes
    chosen = script.pop("format", None)
    if chosen and chosen != fmt and chosen in (c.creative().get("formats") or []):
        c.save(format=chosen)
        c.log(f"Formato trocado pela IA para combinar com a pauta: {chosen}")
    if c.creative().get("review_script", True):
        script = await critique(c, script)
    if script.get("rating") is not None:
        try:
            script["rating"] = max(0, min(10, round(float(str(script["rating"]).split("/")[0].replace(",", ".")))))
        except ValueError:
            script.pop("rating")
    n = assign_series(c)
    if n and c.creative().get("series_name"):
        head = series_text(c.creative()["series_name"], n)
        script["description"] = f"{head}\n\n{script.get('description') or ''}".strip()
        c.log(f"Série: {head}")
    (c.dir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
    c.save(script=script)
    words = sum(len(s["narration"].split()) for s in scenes)
    c.log(f"Roteiro: \"{script.get('title')}\" — {len(scenes)} cenas, {words} palavras")


async def critique(c: Ctx, script: dict) -> dict:
    """Uma segunda IA dá nota ao roteiro (gancho, entrega, ritmo, final, título) e reescreve se ficar abaixo do corte."""
    cr = c.creative()
    min_score = int(cr.get("review_min_score") or 8)
    rounds = max(1, int(cr.get("review_rounds") or 1))
    history = []
    for r in range(rounds + 1):
        c.detail(f"Revisor: rodada {r + 1}")
        prompt = config.CRITIC_PROMPT.format(
            channel=c.ch["name"], niche=c.ch.get("niche", ""), min_score=min_score,
            kind="vídeos longos" if c.is_long else "Shorts",
            insights=(("\nO que já funcionou no canal:\n" + c.insights() + "\n") if c.insights() else "") + brand_rules(c),
            script=json.dumps(script, ensure_ascii=False))
        try:
            out = llm.extract_json(await c.text("critica", prompt))
        except ProviderError as e:
            c.log(f"Revisor falhou, seguindo com o roteiro atual: {e}", "warn")
            break
        score = int(out.get("score") or 0)
        entry = {"score": score, "scores": out.get("scores") or {}, "issues": out.get("issues") or [],
                 "rewritten": False}
        history.append(entry)
        c.log(f"Revisor: nota {score}/10" + (f" — {'; '.join(entry['issues'][:3])}" if entry["issues"] else ""))
        new = out.get("script")
        if score >= min_score or r == rounds:
            break
        new_scenes = [s for s in (new or {}).get("scenes", []) if s.get("narration")] if isinstance(new, dict) else []
        if not new_scenes:
            c.log("Revisor não devolveu um roteiro reescrito; mantendo o original", "warn")
            break
        script = {**script, **new, "scenes": new_scenes}
        entry["rewritten"] = True
        c.log(f"Roteiro reescrito pelo revisor: \"{script.get('title')}\"")
    c.save(critique={"min_score": min_score, "rounds": history,
                     "final": history[-1]["score"] if history else None})
    return script


async def stage_narracao(c: Ctx) -> None:
    scenes = c.data["script"]["scenes"]
    base = c.ch["models"]["narracao"]
    attempts = [dict(base)]
    if base.get("fallback_provider"):
        attempts.append({**base, "provider": base["fallback_provider"], "model": base.get("fallback_model") or ""})
    adir = c.dir / "audio"
    adir.mkdir(exist_ok=True)
    last: Exception | None = None
    for opts in attempts:
        # todas as cenas com a mesma voz: se o provedor falhar no meio, refaz tudo com o reserva
        clips, timings = [], []
        try:
            for i, sc in enumerate(scenes):
                c.detail(f"{opts['provider']}: cena {i + 1}/{len(scenes)}")
                dest = adir / f"{i:02d}.mp3"
                call = {**opts,
                        "previous_text": scenes[i - 1]["narration"] if i > 0 else "",
                        "next_text": scenes[i + 1]["narration"] if i + 1 < len(scenes) else ""}
                words = await tts.synthesize(sc["narration"], dest, call, c.cfg["providers"])
                plain = tts.strip_tags(sc["narration"])
                if not words:
                    words = tts.even_words(plain, await render.ffprobe_duration(dest))
                words = tts.restore_punctuation(plain, words)
                clips.append(dest)
                timings.append(words)
        except ProviderError as e:
            last = e
            c.log(f"Narração com {opts['provider']} falhou: {e}", "warn")
            continue
        durations = await render.build_narration(clips, 0.25, c.dir / "narration.wav")
        (c.dir / "timings.json").write_text(json.dumps(timings, ensure_ascii=False))
        chars = sum(len(tts.strip_tags(s["narration"])) for s in scenes)
        chapters, t = [], 0.0
        for sc, d in zip(scenes, durations):
            if sc.get("chapter"):
                chapters.append({"start": round(t, 2), "title": sc["chapter"]})
            t += d
        c.save(durations=durations, duration=round(sum(durations), 2), chapters=chapters if c.is_long else [],
               narration={"provider": opts["provider"], "model": opts.get("model"), "chars": chars})
        c.log(f"Narração pronta: {sum(durations):.1f}s, {chars} caracteres ({opts['provider']} / "
              f"{opts.get('voice_name') if opts['provider'] == 'elevenlabs' else opts.get('model')})")
        return
    raise ProviderError(f"Narração falhou em todos os provedores: {last}")


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


async def stage_som(c: Ctx) -> None:
    cr = c.creative()
    if c.kind == "corte" or not cr.get("sound", True):
        c.save(sound=None)
        c.log("Desenho de som desligado")
        return
    style = cr.get("sound_style") or ("terror" if c.ch["video"].get("effects") == "terror" else "neutro")
    scenes = c.data["script"]["scenes"]
    durations = c.data["durations"]
    timings = scene_words(c)
    total = sum(durations)
    events, beds, beats = [], [], []
    sfx_vol = float(cr.get("sfx_volume") or 0.55)
    amb_vol = float(cr.get("ambience_volume") or 0.15)
    have_key = bool(tts.elevenlabs_key(c.cfg["providers"]))
    if not have_key:
        c.log("Sem API key do ElevenLabs: só transições e batidas sintetizadas", "warn")
    offset = 0.0
    budget = int(cr.get("max_sfx") or 8)
    failed = 0
    for i, (sc, d) in enumerate(zip(scenes, durations)):
        words = timings[i] if i < len(timings) else []
        c.detail(f"cena {i + 1}/{len(scenes)}")
        if i > 0 and cr.get("whoosh", True):
            events.append({"file": await sound.library_sound("whoosh", style, c.cfg["providers"]),
                           "at": offset - 0.3, "volume": sfx_vol * 0.8,
                           "type": "whoosh", "label": "Whoosh (transição)", "scene": i + 1})
        beat = (sc.get("beat") or "").lower()
        if beat in ("scare", "reveal") and cr.get("beat_fx", True):
            first_sfx = next((x for x in sc.get("sfx") or [] if x.get("word")), None)
            rel = find_word_time(words, first_sfx["word"]) if first_sfx else None
            if rel is None:
                rel = words[len(words) // 2]["start"] if words else d / 2
            at = offset + rel
            beats.append(round(at, 3))
            events.append({"file": await sound.library_sound("impact", style, c.cfg["providers"]),
                           "at": at - 0.05, "volume": sfx_vol * 1.2,
                           "type": "impact", "label": f"Impacto ({'susto' if beat == 'scare' else 'revelação'})",
                           "scene": i + 1})
            if at > 2.5:
                events.append({"file": await sound.library_sound("riser", style, c.cfg["providers"]),
                               "at": at - 2.3, "volume": sfx_vol * 0.6,
                               "type": "riser", "label": "Tensão / Riser", "scene": i + 1})
        if have_key:
            for x in (sc.get("sfx") or [])[:2]:
                if budget <= 0 or not x.get("sound"):
                    continue
                rel = find_word_time(words, x.get("word") or "")
                if rel is None:
                    continue
                try:
                    f = await sound.generate(x["sound"], c.cfg["providers"], duration=2.0)
                    events.append({"file": f, "at": offset + rel - 0.1, "volume": sfx_vol,
                                   "type": "sfx", "label": x["sound"], "word": x.get("word"), "scene": i + 1})
                    budget -= 1
                except ProviderError as e:
                    failed += 1
                    c.log(f"Efeito \"{x['sound']}\" falhou: {e}", "warn")
            if sc.get("ambience") and amb_vol > 0:
                try:
                    f = await sound.generate(sc["ambience"], c.cfg["providers"], duration=10.0, loop=True)
                    beds.append({"file": f, "start": offset, "dur": d + (render.XFADE if i < len(scenes) - 1 else 0),
                                 "volume": amb_vol, "sound": sc["ambience"], "scene": i + 1})
                except ProviderError as e:
                    failed += 1
                    c.log(f"Ambiente \"{sc['ambience']}\" falhou: {e}", "warn")
        offset += d
    script = c.data["script"]
    if rating_on(c) and script.get("rating") is not None:
        at = max(0.0, total - float(cr.get("rating_seconds") or 2.4))
        events.append({"file": await sound.library_sound("blip", style, c.cfg["providers"]), "at": at,
                       "volume": sfx_vol, "type": "blip", "label": "Selo de nota"})
    if cr.get("sonic_logo") and cr.get("sonic_logo_prompt") and have_key:
        try:  # assinatura sonora no ponto do loop (fim → começo)
            f = await sound.generate(cr["sonic_logo_prompt"], c.cfg["providers"], duration=0.8)
            events.append({"file": f, "at": max(0.0, total - 0.75), "volume": sfx_vol * 1.1,
                           "type": "sonic_logo", "label": "Assinatura sonora"})
        except ProviderError as e:
            c.log(f"Assinatura sonora falhou: {e}", "warn")
    mix = c.dir / "sfx.wav"
    c.detail("mixando")
    await sound.build_mix(events, beds, total, mix)
    clean_events = [
        {"type": e.get("type", "sfx"), "label": e.get("label", "Efeito"), "at": round(e["at"], 2),
         "volume": round(e.get("volume", 0.5), 2), "word": e.get("word"), "scene": e.get("scene"),
         "file": str(e["file"]) if e.get("file") else None}
        for e in events
    ]
    clean_beds = [
        {"sound": b.get("sound", "Ambiente"), "start": round(b["start"], 2), "dur": round(b["dur"], 2),
         "volume": round(b.get("volume", 0.15), 2), "scene": b.get("scene"),
         "file": str(b["file"]) if b.get("file") else None}
        for b in beds
    ]
    c.save(sound={"mix": str(mix) if mix.exists() else None, "beats": beats, "events": clean_events,
                  "beds": clean_beds, "style": style})
    c.log(f"Som: {len(events)} efeitos, {len(beds)} ambientes, {len(beats)} momentos de impacto"
          + (f" ({failed} falharam)" if failed else ""))


async def stage_render(c: Ctx) -> None:
    if c.ch.get("review", {}).get("approve_before_render", True):
        if not c.data.get("approved_render"):
            c.log("Pausado antes do render para conferência da timeline")
            raise WaitingApproval()
    out = c.dir / "final.mp4"
    cover = c.data.get("cover")
    cov = c.ch.get("cover") or {}
    caps = c.data.get("captions", str(c.dir / "captions.ass"))
    ass = Path(caps) if caps and Path(caps).exists() else None
    cover_png = Path(cover["image"]) if cover and cov.get("in_video") and not c.is_long else None
    log = lambda m: (c.log(m), c.detail(m))
    if c.kind == "corte":
        c.detail("renderizando")
        await render.render_clip(Path(c.data["reframed"]), ass, out, cover_png,
                                 float(cov.get("in_video_seconds") or 0.3))
    else:
        cr = c.creative()
        every = float(cr.get("cut_every_long" if c.is_long else "cut_every") or 0)
        timings = scene_words(c)
        shots = [plan_shots(timings[i] if i < len(timings) else [], d, every)
                 for i, d in enumerate(c.data["durations"])] if every > 0 else None
        snd = c.data.get("sound") or {}
        sfx = Path(snd["mix"]) if snd.get("mix") and Path(snd["mix"]).exists() else None
        style = snd.get("style") or cr.get("sound_style")
        meter = None
        rating = c.data["script"].get("rating")
        if rating_on(c) and rating is not None:
            total = sum(c.data["durations"])
            meter = {"score": rating, "label": cr.get("rating_label") or "NOTA",
                     "start": max(0.0, total - float(cr.get("rating_seconds") or 2.4)), "end": total,
                     "color": c.ch["video"].get("highlight_color")}
        await render.render_video(c.dir, [Path(p) for p in c.data["images"]], c.data["durations"],
                                  c.dir / "narration.wav", ass, c.ch["video"], c.channel_id, out, log=log,
                                  cover=cover_png, cover_seconds=float(cov.get("in_video_seconds") or 0.3),
                                  frame=c.frame, shots=shots, beats=snd.get("beats") or [], sfx=sfx,
                                  flash=style == "terror" and cr.get("beat_fx", True), meter=meter)
    size = out.stat().st_size / 1e6
    c.save(video=str(out))
    c.log(f"Vídeo pronto: {size:.1f} MB")


async def stage_revisao(c: Ctx) -> None:
    if not c.ch["review"].get("require_approval"):
        c.log("Aprovação desligada para este canal; seguindo direto")
        return
    if c.data.get("approved"):
        c.log("Aprovado no painel")
        return
    if not c.data.get("review_notified"):
        from . import notify
        c.save(review_notified=True)
        try:
            await notify.notify_event(c.cfg, "review_ready", c.job)
        except Exception:
            pass
    raise WaitingApproval()


def chapters_text(chapters: list[dict]) -> str:
    """Capítulos no formato do YouTube (precisa começar em 0:00 e ter pelo menos 3)."""
    if len(chapters) < 3:
        return ""
    lines = []
    for i, ch in enumerate(chapters):
        t = 0 if i == 0 else int(ch["start"])
        lines.append(f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d} {ch['title']}" if t >= 3600
                     else f"{t // 60}:{t % 60:02d} {ch['title']}")
    return "\n".join(lines)


async def stage_upload(c: Ctx) -> None:
    up = c.ch["upload"]
    mode = c.data.get("upload_mode_override") or up.get("mode") or "manual"
    if mode not in ("auto", "draft"):
        c.save(publish={"mode": "manual", "ready_at": time.time()})
        c.log("Modo manual: vídeo pronto para você baixar e postar")
        return
    opts = dict(up)
    if mode == "draft":
        # a API do YouTube não cria rascunho de verdade: sobe como privado, sem avisar inscritos,
        # e você termina no Studio (o vídeo fica lá como privado até você publicar)
        opts.update(privacy="private", draft=True)
    elif c.data.get("publish_at"):
        opts["publish_at"] = c.data["publish_at"]
    c.log("Enviando para o YouTube como rascunho (privado)" if mode == "draft"
          else f"Enviando para o YouTube ({opts.get('privacy')})")
    cover = c.data.get("cover") or {}
    cov_path = cover.get("jpg") or cover.get("image")
    thumb = Path(cov_path) if cov_path and Path(cov_path).exists() and (c.ch.get("cover") or {}).get("upload_thumbnail", True) else None
    meta = dict(c.data["script"])
    if c.is_long and c.data.get("chapters") and c.long_opts().get("chapters", True):
        meta["description"] = (meta.get("description") or "") + "\n\n" + chapters_text(c.data["chapters"])
    opts["is_short"] = not c.is_long
    result = await upload.upload(c.channel_id, Path(c.data["video"]), meta, opts,
                                 progress=lambda p: c.detail(f"{p}%"), thumbnail=thumb)
    c.save(publish={"mode": mode, **result})
    c.log(f"Rascunho no YouTube: {result['studio_url']}" if mode == "draft" else f"Publicado: {result['url']}")
    if result.get("thumbnail_error"):
        c.log(f"Thumbnail não enviada: {result['thumbnail_error']}", "warn")
    elif thumb:
        c.log("Capa enviada como thumbnail")

    # Upload para o TikTok (Shorts / Vídeos verticais)
    from . import tiktok
    tt_status = tiktok.status(c.cfg, c.channel_id)
    send_tt = bool(tt_status.get("connected") and (opts.get("publish_to_tiktok", True) or c.data.get("publish_to_tiktok")))
    if send_tt and not c.is_long:
        try:
            cov_cfg = c.ch.get("cover") or {}
            opts["cover_in_video"] = bool(cov_cfg.get("in_video", True))
            if opts["cover_in_video"]:
                opts["cover_timestamp_ms"] = int(float(cov_cfg.get("in_video_seconds") or 0.3) * 1000 / 2)
            c.log("Enviando para o TikTok...")
            tt_res = await tiktok.upload(
                c.channel_id,
                Path(c.data["video"]),
                meta,
                opts,
                progress=lambda p: c.detail(f"TikTok: {p}%"),
            )
            result["tiktok"] = tt_res
            c.save(publish={"mode": mode, **result})
            c.log(f"Enviado para o TikTok ({tt_res.get('privacy')}): {tt_res.get('status')}")
        except Exception as e:
            c.log(f"Falha ao enviar para o TikTok: {e}", "warn")
            result["tiktok_error"] = str(e)[:300]
            c.save(publish={"mode": mode, **result})

    # Upload para o Instagram Reels
    from . import instagram
    ig_status = instagram.status(c.cfg, c.channel_id)
    send_ig = bool(ig_status.get("configured") and (opts.get("publish_to_instagram") or c.data.get("publish_to_instagram")))
    if send_ig and not c.is_long:
        try:
            c.log("Enviando para o Instagram Reels...")
            ig_res = await instagram.upload(
                c.channel_id,
                Path(c.data["video"]),
                meta,
                opts,
                progress=lambda p: c.detail(f"Instagram: {p}%"),
            )
            result["instagram"] = ig_res
            c.save(publish={"mode": mode, **result})
            c.log(f"Enviado para o Instagram Reels: {ig_res.get('permalink')}")
        except Exception as e:
            c.log(f"Falha ao enviar para o Instagram Reels: {e}", "warn")
            result["instagram_error"] = str(e)[:300]
            c.save(publish={"mode": mode, **result})

    # Disparar notificação de publicação concluída
    from . import notify
    try:
        await notify.notify_event(c.cfg, "published", c.job)
    except Exception:
        pass


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
    tr = await transcribe.transcribe(src, opts, c.cfg["providers"], progress=c.detail)
    if not tr["words"]:
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
    lines = transcribe.transcript_lines(words)
    text = "\n".join(f"[{ln['start']:.1f}] {ln['text']}" for ln in lines)
    instr = (c.data.get("instructions") or "").strip()
    prompt = c.fmt(c.ch["prompts"].get("clip_select") or config.CLIP_SELECT_PROMPT, transcript=text, count=count,
                   min_seconds=int(min_s), max_seconds=int(max_s),
                   source_title=(c.data.get("source") or {}).get("title") or "",
                   instructions=f"- Instruções extras: {instr}" if instr else "")
    out = await c.text("selecao", prompt)
    raw = llm.extract_json(out).get("clips") or []
    if not raw:
        raise ProviderError("A IA não escolheu nenhum corte")
    # refazer a seleção descarta cortes que ainda não começaram
    for old in db.list_children(c.job["id"]):
        if old["status"] in ("queued", "failed", "canceled"):
            db.delete_job(old["id"])
            shutil.rmtree(config.JOBS_DIR / old["id"], ignore_errors=True)
    picked, used = [], []
    for cl in sorted(raw, key=lambda x: -float(x.get("score") or 0)):
        try:
            snapped = snap_clip(words, float(cl["start"]), float(cl["end"]), min_s, max_s)
        except (KeyError, TypeError, ValueError):
            continue
        if not snapped:
            continue
        s, e = snapped
        if any(s < ue and e > us for us, ue in used):
            continue
        used.append((s, e))
        picked.append((s, e, cl))
        if len(picked) >= count:
            break
    if not picked:
        raise ProviderError("Nenhum corte válido (durações fora do limite ou sobrepostos)")
    source = c.data["source"]
    created = []
    for s, e, cl in sorted(picked, key=lambda x: x[0]):
        script = {"title": cl.get("title") or "Corte", "description": cl.get("description") or "",
                  "tags": cl.get("tags") or [], "cover_text": cl.get("cover_text") or ""}
        clip = {"start": round(s, 2), "end": round(e, 2), "score": cl.get("score"), "reason": cl.get("reason")}
        child = db.create_job(c.channel_id, script["title"], kind="corte", parent_id=c.job["id"], data={
            "source_job": c.job["id"], "source_video": source["path"], "source_title": source.get("title"),
            "clip": clip, "script": script, "words": clip_words(words, s, e)})
        db.log(child["id"], f"Corte de {s:.1f}s a {e:.1f}s de \"{source.get('title')}\" (nota {cl.get('score')})")
        created.append({"id": child["id"], **clip, "title": script["title"]})
        c.log(f"Corte {e - s:.0f}s (nota {cl.get('score')}): {script['title']}")
    c.save(clips=created)
    c.log(f"{len(created)} cortes criados e enviados para a fila")


async def stage_recorte(c: Ctx) -> None:
    clip = c.data["clip"]
    src = Path(c.data["source_video"])
    if not src.exists():
        raise ProviderError("Vídeo de origem não existe mais (a fonte foi excluída?)")
    dur = clip["end"] - clip["start"]
    raw = c.dir / "clip_raw.mp4"
    c.detail("recortando")
    await render.ffmpeg(["-ss", f"{clip['start']:.3f}", "-i", str(src), "-t", f"{dur:.3f}",
                         "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", "30",
                         "-c:a", "aac", "-b:a", "192k", str(raw)])
    mode = (c.ch.get("clips") or {}).get("reframe") or "face"
    c.detail("reenquadrando")
    dst = c.dir / "reframed.mp4"
    used = await asyncio.to_thread(reframe.reframe, raw, dst, mode, c.log)
    raw.unlink(missing_ok=True)
    c.save(reframed=str(dst), reframe_mode=used, duration=round(dur, 2))
    c.log(f"Corte de {dur:.1f}s reenquadrado ({used})")


STAGE_FUNCS = {
    "ideia": stage_ideia,
    "roteiro": stage_roteiro,
    "narracao": stage_narracao,
    "imagens": stage_imagens,
    "capa": stage_capa,
    "legendas": stage_legendas,
    "render": stage_render,
    "revisao": stage_revisao,
    "upload": stage_upload,
    "som": stage_som,
    "download": stage_download,
    "transcricao": stage_transcricao,
    "selecao": stage_selecao,
    "recorte": stage_recorte,
}


async def run_job(job_id: str) -> None:
    cfg = config.load()
    job = db.get_job(job_id)
    c = Ctx(job, cfg)
    c.job = db.update_job(job_id, status="running", error=None)
    for stage in config.stages_for(c.kind):
        if c.job["stages"][stage].get("status") == "done":
            continue
        c.stage = stage
        c.job = db.update_job(job_id, stage=stage,
                              stages={stage: {"status": "running", "started": time.time(), "error": None,
                                              "detail": None}})
        try:
            await STAGE_FUNCS[stage](c)
        except WaitingApproval:
            db.update_job(job_id, status="waiting_approval", stages={stage: {"status": "waiting"}})
            c.log("Aguardando sua aprovação no painel")
            return
        except asyncio.CancelledError:
            db.update_job(job_id, status="canceled", stages={stage: {"status": "canceled", "ended": time.time()}})
            c.log("Cancelado", "warn")
            raise
        except Exception as e:
            msg = f"{type(e).__name__}: {e}" if not isinstance(e, ProviderError) else str(e)
            db.update_job(job_id, status="failed", error=msg,
                          stages={stage: {"status": "failed", "ended": time.time(), "error": msg}})
            c.log(msg, "error")
            return
        c.job = db.update_job(job_id, stages={stage: {"status": "done", "ended": time.time()}})
    db.update_job(job_id, status="done", stage=None)
    c.log("Pipeline concluído")

