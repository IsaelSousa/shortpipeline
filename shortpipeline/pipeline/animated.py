"""Etapas do Short animado (motion graphics 2D/2.5D): pesquisa, storyboard, assets, preview, qualidade e render.

A IA dirige (pesquisa, roteiro, storyboard em JSON, revisão); a engine desenha. Cada etapa grava o resultado no
job e no diretório dele, então uma produção interrompida retoma sem refazer o que já ficou pronto.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .. import config, render, sound
from ..motion import catalog, physics, prompts, schema
from ..motion import render as motion
from ..providers import ProviderError, llm
from .core import Ctx
from .media import default_cover_text

EXAMPLE = config.ROOT / "docs" / "motion" / "examples" / "ar-condicionado.json"


def _opts(c: Ctx) -> dict:
    return c.ch.get("animated") or {}


def _compact(data) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def storyboard_path(c: Ctx) -> Path:
    return c.dir / "storyboard.json"


def load_storyboard(c: Ctx) -> dict:
    return json.loads(storyboard_path(c).read_text(encoding="utf-8"))


def save_storyboard(c: Ctx, data: dict) -> None:
    storyboard_path(c).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    c.save(storyboard={"file": str(storyboard_path(c)), "scenes": len(data["scenes"]), "saved_at": time.time(),
                       "schema_version": schema.SCHEMA_VERSION})


def _timings(c: Ctx) -> list[list[dict]]:
    return json.loads((c.dir / "timings.json").read_text())


def prepared_spec(c: Ctx) -> tuple[dict, list[str]]:
    data = load_storyboard(c)
    spec, warnings = motion.prepare(data, _timings(c), c.data["durations"])
    cap = _opts(c)
    spec["captions"]["enabled"] = cap.get("captions", True)
    spec["captions"]["max_words"] = int(cap.get("caption_words") or 3)
    return spec, warnings


# ------------------------------------------------------------------ pesquisa
async def stage_pesquisa(c: Ctx) -> None:
    prompt = prompts.RESEARCH_PROMPT.format(channel=c.ch["name"], niche=c.ch.get("niche", ""),
                                            topic=c.job.get("topic") or "", language=c.ch.get("language"))
    out = llm.extract_json(await c.text("ideia", prompt))
    facts = [f for f in out.get("facts") or [] if isinstance(f, dict) and f.get("claim")][:12]
    kinds = {"verified", "calculation", "estimate", "illustrative"}
    for f in facts:
        if f.get("kind") not in kinds:
            f["kind"] = "estimate"
    research = {"question": str(out.get("question") or "")[:300], "facts": facts,
                "safety": str(out.get("safety") or "")[:300], "avoid": [str(x)[:200] for x in out.get("avoid") or []][:6]}
    c.save(research=research)
    by = {k: sum(1 for f in facts if f["kind"] == k) for k in kinds}
    c.log(f"Pesquisa: {len(facts)} fatos ({by['verified']} verificados, {by['calculation']} cálculos, "
          f"{by['estimate']} estimativas)")


def research_brief(c: Ctx) -> str:
    r = c.data.get("research") or {}
    if not r.get("facts"):
        return ""
    lines = [f"- [{f['kind']}] {f['claim']}" + (f" ({f['assumptions']})" if f.get("assumptions") else "")
             for f in r["facts"]]
    extra = []
    if r.get("safety"):
        extra.append(f"Orientação prática: {r['safety']}")
    if r.get("avoid"):
        extra.append("Não afirmar: " + "; ".join(r["avoid"]))
    return "\n\nFATOS DA PESQUISA (use só estes números):\n" + "\n".join(lines + extra)


# ------------------------------------------------------------------ storyboard
def _scenes_brief(c: Ctx) -> str:
    timings = _timings(c)
    out = []
    for i, (sc, dur, words) in enumerate(zip(c.data["script"]["scenes"], c.data["durations"], timings)):
        said = " ".join(f"{w['text']}({w['start']:.2f})" for w in words)
        out.append(f"Cena {i + 1} — {dur:.2f} s\nNarração: {sc['narration']}\nVisual pedido: {sc.get('visual', '')}\n"
                   f"Palavras: {said}")
    return "\n\n".join(out)


def _fit_timing(data: dict, durations: list[float]) -> None:
    """Início e fim das cenas vêm da narração, não do que a IA escreveu."""
    offset = 0.0
    for i, (sc, d) in enumerate(zip(data.get("scenes") or [], durations)):
        sc["start"], sc["end"] = round(offset, 3), round(offset + d, 3)
        sc["id"] = re.sub(r"[^a-z0-9_]", "_", str(sc.get("id") or f"s{i + 1}").lower())[:40] or f"s{i + 1}"
        offset += d


async def stage_storyboard(c: Ctx) -> None:
    durations = c.data["durations"]
    example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    accent = _opts(c).get("accent") or c.ch["video"].get("highlight_color") or "#F97316"
    facts = (c.data.get("research") or {}).get("facts") or []
    prompt = prompts.STORYBOARD_PROMPT.format(
        catalog=catalog.prompt_catalog(), fields=schema.field_guide(), scenes=_scenes_brief(c), facts=_compact(facts) if facts else "(sem fatos)",
        example=_compact(example["scenes"][2]), accent=accent, n=len(durations))
    c.detail("dirigindo as cenas")
    data = llm.extract_json(await c.text("roteiro", prompt))
    if len(data.get("scenes") or []) != len(durations):
        raise ProviderError(f"O storyboard veio com {len(data.get('scenes') or [])} cenas; o roteiro tem {len(durations)}")
    _fit_timing(data, durations)
    for attempt in range(3):
        try:
            video = schema.validate(data)
            break
        except schema.ValidationError as exc:
            if attempt == 2:
                raise ProviderError("Storyboard inválido depois de 2 correções:\n" + schema.errors_text(exc))
            c.log(f"Storyboard inválido, pedindo correção ({len(exc.errors())} erros):\n"
                  + schema.errors_text(exc, limit=6), "warn")
            c.detail(f"corrigindo o storyboard ({attempt + 1})")
            data = llm.extract_json(await c.text("critica", prompts.FIX_PROMPT.format(
                errors=schema.errors_text(exc), json=_compact(data))))
            _fit_timing(data, durations)
    data = video.model_dump(by_alias=True, exclude_none=True)
    data["facts"] = facts + physics.fall_facts(video)
    data["title"] = c.data["script"].get("title") or data.get("title") or ""
    save_storyboard(c, data)
    _, warnings = prepared_spec(c)
    for w in warnings:
        c.log(w, "warn")
    n_actions = sum(len(el.actions) for s in video.scenes for el in [*s.characters, *s.objects])
    c.log(f"Storyboard: {len(video.scenes)} cenas, {len(video.characters)} personagens, {n_actions} ações, "
          f"{sum(len(s.overlays) for s in video.scenes)} informativos")


# ------------------------------------------------------------------ assets
async def stage_assets(c: Ctx) -> None:
    video = schema.validate(load_storyboard(c))
    usage = catalog.usage_report(video)
    looks = {ch.id: ch.look.model_dump() for ch in video.characters}
    c.save(assets={"catalog": usage, "characters": looks, "new": []})
    used = ", ".join(f"{k} ×{v}" for k, v in sorted(usage.items())) or "nenhum objeto"
    c.log(f"Assets do catálogo: {used}; {len(looks)} personagem(ns) com aparência fixa; nenhum asset novo")


# ------------------------------------------------------------------ preview
async def _render_preview(c: Ctx, only: set[str] | None = None) -> Path:
    spec, _ = prepared_spec(c)
    p = motion.PREVIEW
    t0 = time.time()
    parts = await motion.render_scenes(spec, c.dir / "motion" / "preview", width=p["width"], height=p["height"],
                                       fps=p["fps"], quality=p["quality"], only=only, log=c.detail)
    silent = c.dir / "motion" / "preview-silent.mp4"
    await motion.concat(parts, silent)
    out = c.dir / "preview.mp4"
    await render.ffmpeg(["-i", str(silent), "-i", str(c.dir / "narration.wav"), "-map", "0:v", "-map", "1:a",
                         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(out)])
    c.save(preview=str(out))
    c.log(f"Preview pronto em {time.time() - t0:.0f} s ({p['width']}×{p['height']}, {p['fps']} fps)")
    return out


async def stage_preview(c: Ctx) -> None:
    if not motion.available():
        raise ProviderError("Engine de animação indisponível. Execute npm ci e npm run build em motion-canvas.")
    await _render_preview(c)


# ------------------------------------------------------------------ qualidade
async def _freezes(video: Path) -> list[tuple[float, float]]:
    from ..providers import run
    code, _, err = await run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(video), "-vf",
                              "freezedetect=n=0.002:d=1.6", "-map", "0:v", "-f", "null", "-"], timeout=300)
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err or "")]
    durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", err or "")]
    return list(zip(starts, durs))


def auto_checks(video: schema.Video, freezes: list[tuple[float, float]]) -> list[dict]:
    issues = []
    for sc in video.scenes:
        moving = any(el.actions for el in [*sc.characters, *sc.objects]) or sc.camera.moves
        if not moving:
            issues.append({"scene": sc.id, "problem": "cena sem nenhum movimento (personagem, objeto ou câmera)"})
        for o in sc.overlays:
            if o.type == "callout" and o.text and len(o.text) > 60:
                issues.append({"scene": sc.id, "problem": f"balão longo demais ({len(o.text)} caracteres)"})
        if re.search(r"\d", sc.narration) and not sc.overlays:
            issues.append({"scene": sc.id, "problem": "a narração diz um número que não aparece na tela"})
    for start, dur in freezes:
        sc = next((s for s in video.scenes if s.start <= start + 0.05 < s.end), video.scenes[-1])
        issues.append({"scene": sc.id, "problem": f"{dur:.1f} s sem mudança na imagem (a partir de {start:.1f} s)"})
    return issues


def _summary(video: schema.Video) -> str:
    lines = []
    for sc in video.scenes:
        acts = lambda els, key: ", ".join(f"{getattr(e, key)}({'/'.join(a.type for a in e.actions) or 'parado'})" for e in els)
        lines.append(
            f"{sc.id} [{sc.end - sc.start:.1f}s, entra {sc.enter.type}] \"{sc.narration[:160]}\" | cenário {sc.environment.type}"
            f" | pessoas {acts(sc.characters, 'ref') or '-'} | objetos {acts(sc.objects, 'id') or '-'}"
            f" | câmera {', '.join(m.type + (f'({m.target})' if m.target else '') for m in sc.camera.moves) or 'fixa'}"
            f" | informativos {', '.join(o.type + (f':{o.text}' if o.text else '') for o in sc.overlays) or '-'}"
            f" | efeitos {', '.join(e.type for e in sc.effects) or '-'}")
    return "\n".join(lines)


async def stage_qualidade(c: Ctx) -> None:
    opts = _opts(c)
    video = schema.validate(load_storyboard(c))
    preview = Path(c.data.get("preview") or c.dir / "preview.mp4")
    freezes = await _freezes(preview) if preview.is_file() else []
    issues = auto_checks(video, freezes)
    for i in issues:
        c.log(f"Checagem: cena {i['scene']}: {i['problem']}", "warn")
    report = {"auto": issues, "score": None, "ai": [], "fixed": []}
    if opts.get("ai_review", True):
        try:
            out = llm.extract_json(await c.text("critica", prompts.QA_PROMPT.format(
                checks="\n".join(f"- {i['scene']}: {i['problem']}" for i in issues) or "(nada encontrado)",
                summary=_summary(video))))
            report["score"] = int(out.get("score") or 0)
            report["ai"] = [i for i in out.get("issues") or [] if isinstance(i, dict) and i.get("scene")][:3]
            c.log(f"Qualidade: nota {report['score']}/10" + (
                f" — {'; '.join(i.get('problem', '') for i in report['ai'])}" if report["ai"] else ""))
        except ProviderError as e:
            c.log(f"Revisão de qualidade pela IA falhou, seguindo: {e}", "warn")
    min_score = int(opts.get("min_score") or 7)
    if report["score"] is not None and report["score"] < min_score and report["ai"]:
        data = load_storyboard(c)
        changed = set()
        for issue in report["ai"][:2]:
            idx = next((k for k, s in enumerate(data["scenes"]) if s["id"] == issue["scene"]), None)
            if idx is None:
                continue
            c.detail(f"refazendo a cena {issue['scene']}")
            try:
                scene = llm.extract_json(await c.text("roteiro", prompts.SCENE_FIX_PROMPT.format(
                    catalog=catalog.prompt_catalog(), problem=issue.get("problem", ""), fix=issue.get("fix", ""),
                    scene=_compact(data["scenes"][idx]))))
                old = data["scenes"][idx]
                trial = None
                for attempt in range(2):
                    scene.update(id=old["id"], start=old["start"], end=old["end"], narration=old.get("narration", ""))
                    trial = {**data, "scenes": [*data["scenes"][:idx], scene, *data["scenes"][idx + 1:]]}
                    try:
                        trial = schema.validate(trial).model_dump(by_alias=True, exclude_none=True)
                        break
                    except schema.ValidationError as exc:
                        if attempt:
                            raise
                        scene = llm.extract_json(await c.text("critica", prompts.FIX_PROMPT.format(
                            errors=schema.errors_text(exc), json=_compact(scene))))
                trial["facts"] = data.get("facts") or []
            except (ProviderError, schema.ValidationError) as e:
                c.log(f"Correção da cena {issue['scene']} descartada: {str(e)[:200]}", "warn")
                continue
            data = trial
            changed.add(old["id"])
        if changed:
            save_storyboard(c, data)
            report["fixed"] = sorted(changed)
            c.log(f"Cenas refeitas pela qualidade: {', '.join(sorted(changed))}")
            await _render_preview(c, only=changed | {s["id"] for s in data["scenes"]})
    c.save(qa=report)


# ------------------------------------------------------------------ render final
async def render_final(c: Ctx, log) -> None:
    spec, _ = prepared_spec(c)
    t0 = time.time()
    parts = await motion.render_scenes(spec, c.dir / "motion" / "final", width=1080, height=1920, fps=render.FPS,
                                       quality=0.92, concurrency=2, log=log)
    silent = c.dir / "motion" / "final-silent.mp4"
    await motion.concat(parts, silent)
    log(f"Animação renderizada em {time.time() - t0:.0f} s")
    total = sum(c.data["durations"])
    snd = c.data.get("sound") or {}
    if (snd.get("events") or snd.get("beds")) and snd.get("mix_version") != sound.MIX_VERSION:
        snd = await sound.remix_saved(snd, total, c.dir / "sfx.wav", c.creative().get("ambience_volume"))
        c.save(sound=snd)
    sfx = Path(snd["mix"]) if snd.get("mix") and Path(snd["mix"]).exists() else None
    music = render.pick_music(c.channel_id, c.data["script"].get("music"))
    log(f"Música: {music.name}" if music else "Sem música de fundo")
    out = c.dir / "final.mp4"
    await render.mux_animation(silent, c.dir / "narration.wav", c.ch["video"], c.channel_id, out, total=total,
                               sfx=sfx, beats=snd.get("beats") or [], music=music)
    # capa: um quadro da própria animação com o texto de capa por cima
    cov = c.ch.get("cover") or {}
    if cov.get("enabled", True):
        cdir = c.dir / "cover"
        cdir.mkdir(exist_ok=True)
        bg = cdir / "frame.jpg"
        t = spec.get("cover_time")
        if t is None or not 0 <= float(t) < total:
            t = min(total - 0.1, spec["scenes"][0]["end"] * 0.6)
        await motion.still({**spec, "captions": {**spec["captions"], "enabled": False}}, float(t), bg)
        script = c.data["script"]
        text = (c.data.get("cover_text_override") or script.get("cover_text") or default_cover_text(script)).strip() \
            if cov.get("text_enabled", True) else ""
        png, jpg = cdir / "cover.png", cdir / "cover.jpg"
        await render.build_cover(bg, text, dict(cov), png, jpg, c.frame)
        c.save(cover={"image": str(png), "jpg": str(jpg), "bg": str(bg), "text": text})
