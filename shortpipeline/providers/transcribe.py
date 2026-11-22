"""Transcrição com tempo por palavra: Whisper local (faster-whisper, CPU) ou ElevenLabs Scribe."""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import httpx

from . import ProviderError
from .tts import elevenlabs_key

_models: dict = {}


def _whisper_sync(audio_path: Path, model_name: str, language: str | None, progress) -> dict:
    import numpy as np
    from faster_whisper import WhisperModel

    # decodifica com o ffmpeg (o decodificador embutido do faster-whisper quebra com algumas versões do PyAV)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio_path), "-f", "s16le", "-ac", "1",
                          "-ar", "16000", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    duration = len(audio) / 16000
    key = model_name or "small"
    if key not in _models:
        if progress:
            progress(f"carregando modelo {key}")
        _models[key] = WhisperModel(key, device="cpu", compute_type="int8",
                                    cpu_threads=max(2, (os.cpu_count() or 4) - 2))
    segments, info = _models[key].transcribe(audio, language=language or None, word_timestamps=True,
                                             vad_filter=True, beam_size=5)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"text": text, "start": round(w.start, 3), "end": round(w.end, 3)})
        if progress and duration:
            progress(f"{min(99, int(seg.end / duration * 100))}%")
    return {"words": words, "language": info.language, "duration": duration, "provider": f"whisper/{key}"}


async def _whisper(audio_path: Path, opts: dict, providers_cfg: dict, progress) -> dict:
    try:
        return await asyncio.to_thread(_whisper_sync, audio_path, opts.get("model") or "small",
                                       opts.get("language") or None, progress)
    except Exception as e:
        raise ProviderError(f"Whisper falhou: {e}")


async def _scribe(audio_path: Path, opts: dict, providers_cfg: dict, progress) -> dict:
    key = elevenlabs_key(providers_cfg)
    if not key:
        raise ProviderError("ElevenLabs Scribe precisa da API key (aba Provedores)")
    mp3 = audio_path.with_suffix(".scribe.mp3")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(audio_path), "-ac", "1", "-b:a", "64k", str(mp3)],
                   check=True)
    if progress:
        progress("enviando áudio ao ElevenLabs")
    data = {"model_id": "scribe_v1", "timestamps_granularity": "word"}
    if opts.get("language"):
        data["language_code"] = opts["language"]
    async with httpx.AsyncClient(timeout=1800) as client:
        with open(mp3, "rb") as f:
            r = await client.post("https://api.elevenlabs.io/v1/speech-to-text", headers={"xi-api-key": key},
                                  data=data, files={"file": (mp3.name, f, "audio/mpeg")})
    mp3.unlink(missing_ok=True)
    if r.status_code != 200:
        raise ProviderError(f"ElevenLabs Scribe {r.status_code}: {r.text[:300]}")
    body = r.json()
    words = [{"text": w["text"].strip(), "start": w["start"], "end": w["end"]}
             for w in body.get("words", []) if w.get("type", "word") == "word" and w.get("text", "").strip()]
    duration = words[-1]["end"] if words else 0
    return {"words": words, "language": body.get("language_code"), "duration": duration, "provider": "elevenlabs/scribe"}


PROVIDERS = {"whisper": _whisper, "elevenlabs": _scribe}


async def transcribe(audio_path: Path, opts: dict, providers_cfg: dict, progress=None) -> dict:
    attempts = [opts.get("provider") or "whisper"]
    if opts.get("fallback_provider") and opts["fallback_provider"] not in attempts:
        attempts.append(opts["fallback_provider"])
    last = None
    for prov in attempts:
        fn = PROVIDERS.get(prov)
        if not fn:
            continue
        try:
            return await fn(audio_path, opts if prov == attempts[0] else {**opts, "model": ""}, providers_cfg, progress)
        except ProviderError as e:
            last = e
            if progress:
                progress(f"{prov} falhou, tentando reserva")
    raise ProviderError(f"Transcrição falhou: {last}")


def transcript_lines(words: list[dict], max_gap: float = 0.8, max_len: float = 12.0) -> list[dict]:
    """Agrupa palavras em trechos curtos ([início] texto) para mandar à IA."""
    lines, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or w["end"] - cur[0]["start"] > max_len
                    or cur[-1]["text"][-1:] in ".?!"):
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [{"start": ln[0]["start"], "end": ln[-1]["end"], "text": " ".join(w["text"] for w in ln)} for ln in lines]
