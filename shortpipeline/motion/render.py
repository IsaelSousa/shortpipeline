"""Ponte Python → engine de animação: prepara o JSON (tempos da narração, legendas, fontes), renderiza cada cena
com cache e junta as cenas. Uma cena que não mudou não é renderizada de novo."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .. import config
from ..providers import ProviderError, resolve_bin, run
from ..render import ffmpeg

PROJECT = config.ROOT / "motion-canvas"
ENGINE = PROJECT / "dist" / "engine.js"
BRIDGE = PROJECT / "animate.mjs"
FONTS = {"SPDisplay": config.FONTS_DIR / "Anton-Regular.ttf", "SPBody": config.FONTS_DIR / "Montserrat-Variable.ttf"}
PREVIEW = {"width": 540, "height": 960, "fps": 15, "quality": 0.82}


def available() -> bool:
    return ENGINE.is_file() and BRIDGE.is_file()


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


def find_word(words: list[dict], word: str) -> float | None:
    """Início (s, relativo à cena) da primeira palavra da narração que bate com `word`."""
    key = _norm(word.split()[0]) if word.strip() else ""
    if not key:
        return None
    for w in words:
        if _norm(w["text"]) == key:
            return float(w["start"])
    for w in words:
        if _norm(w["text"]).startswith(key) or key.startswith(_norm(w["text"]) or "#"):
            return float(w["start"])
    return None


def prepare(data: dict, scene_words: list[list[dict]], durations: list[float]) -> tuple[dict, list[str]]:
    """Encaixa o storyboard na narração real: início/fim de cada cena vêm das durações da voz, `at_word` vira
    tempo e as palavras viram as legendas. Devolve o JSON pronto e os avisos (palavras não encontradas)."""
    spec = json.loads(json.dumps(data))
    warnings: list[str] = []
    scenes = spec["scenes"]
    if len(scenes) != len(durations):
        raise ProviderError(f"O storyboard tem {len(scenes)} cenas e a narração tem {len(durations)}")
    offset = 0.0
    words_all = []
    for sc, dur, words in zip(scenes, durations, scene_words):
        sc["start"], sc["end"] = round(offset, 3), round(offset + dur, 3)
        for group in ("characters", "objects"):
            for el in sc.get(group) or []:
                for a in el.get("actions") or []:
                    _resolve(a, words, sc["id"], warnings, dur)
        for m in (sc.get("camera") or {}).get("moves") or []:
            _resolve(m, words, sc["id"], warnings, dur)
        for o in sc.get("overlays") or []:
            _resolve(o, words, sc["id"], warnings, dur)
        for e in sc.get("effects") or []:
            _resolve(e, words, sc["id"], warnings, dur, key="at")
        words_all += [{"text": w["text"], "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)}
                      for w in words]
        offset += dur
    spec.setdefault("captions", {})["words"] = words_all
    spec["fonts"] = {k: str(v) for k, v in FONTS.items() if v.is_file()}
    return spec, warnings


def _resolve(item: dict, words: list[dict], scene_id: str, warnings: list[str], dur: float, key: str = "start") -> None:
    word = item.pop("at_word", None)
    if word:
        t = find_word(words, word)
        if t is None:
            warnings.append(f"cena {scene_id}: a palavra \"{word}\" não está na narração; mantido o tempo {item.get(key, 0)}")
        else:
            shift = t - float(item.get(key) or 0)
            item[key] = round(t, 3)
            if item.get("end") is not None:
                item["end"] = round(float(item["end"]) + max(0.0, shift), 3)
    # nada começa depois do fim da cena
    if item.get(key) is not None and float(item[key]) > dur:
        item[key] = round(max(0.0, dur - 0.3), 3)


def _scene_key(spec: dict, i: int, width: int, height: int, fps: int, quality: float) -> str:
    sc = spec["scenes"][i]
    words = [w for w in spec["captions"]["words"] if sc["start"] - 0.5 <= w["start"] < sc["end"] + 0.5]
    shared = {k: spec.get(k) for k in ("upm", "theme", "characters", "fonts")}
    shared["captions"] = {k: v for k, v in spec["captions"].items() if k != "words"}
    engine = hashlib.sha256(ENGINE.read_bytes()).hexdigest()[:12] if ENGINE.is_file() else "-"
    raw = json.dumps([sc, words, shared, engine, width, height, fps, quality], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


async def _node(args: list[str], timeout: int) -> None:
    if not available():
        raise ProviderError("Engine de animação indisponível. Execute npm ci e npm run build em motion-canvas.")
    code, _, err = await run([resolve_bin("node"), str(BRIDGE), *args], timeout=timeout)
    if code:
        raise ProviderError(f"Engine de animação falhou: {(err or '')[-800:]}")


async def render_scenes(spec: dict, folder: Path, *, width: int, height: int, fps: int, quality: float = 0.9,
                        only: set[str] | None = None, concurrency: int = 2, log=None) -> list[Path]:
    """Renderiza cada cena num MP4 (com cache pelo conteúdo da cena). Devolve os arquivos na ordem."""
    folder.mkdir(parents=True, exist_ok=True)
    spec_file = folder / "spec.json"
    spec_file.write_text(json.dumps({**spec, "fps": fps}, ensure_ascii=False), encoding="utf-8")
    sem = asyncio.Semaphore(concurrency)
    outs: list[Path] = []
    jobs = []
    for i, sc in enumerate(spec["scenes"]):
        key = _scene_key(spec, i, width, height, fps, quality)
        dest = folder / f"{sc['id']}-{key}.mp4"
        outs.append(dest)
        if dest.is_file() or (only is not None and sc["id"] not in only):
            continue
        f0, f1 = round(sc["start"] * fps), round(sc["end"] * fps)

        async def one(sc=sc, dest=dest, f0=f0, f1=f1):
            async with sem:
                tmp = dest.with_suffix(".tmp.mp4")
                await _node([str(spec_file), str(tmp), "--f0", str(f0), "--f1", str(f1), "--width", str(width),
                             "--height", str(height), "--fps", str(fps), "--quality", str(quality)],
                            timeout=max(120, int((f1 - f0) / fps * 60)))
                tmp.replace(dest)
                if log:
                    log(f"Cena {sc['id']} animada")
        jobs.append(one())
    await asyncio.gather(*jobs)
    # limpa versões antigas das cenas (o cache guarda só a atual de cada uma)
    keep = {p.name for p in outs}
    for old in folder.glob("*.mp4"):
        if old.name not in keep and re.match(r".+-[0-9a-f]{16}\.mp4$", old.name):
            old.unlink(missing_ok=True)
    return outs


async def concat(parts: list[Path], dest: Path) -> None:
    lst = dest.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    await ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(dest)])
    lst.unlink(missing_ok=True)


async def still(spec: dict, t: float, dest: Path, width: int = 1080, height: int = 1920) -> None:
    spec_file = dest.with_suffix(".spec.json")
    spec_file.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    try:
        await _node([str(spec_file), str(dest), "--still", f"{t:.3f}", "--width", str(width), "--height", str(height)],
                    timeout=120)
    finally:
        spec_file.unlink(missing_ok=True)
