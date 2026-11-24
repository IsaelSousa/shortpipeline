"""Narração. Devolve o áudio e o tempo de cada palavra (para as legendas)."""

from __future__ import annotations

import base64
import re
from pathlib import Path

import httpx

from . import ProviderError

Word = dict  # {"text": str, "start": float, "end": float}


async def _edge(text: str, dest: Path, opts: dict, providers_cfg: dict) -> list[Word]:
    # o serviço do Edge às vezes devolve "No audio was received" do nada: tenta de novo
    import asyncio
    for attempt in range(4):
        try:
            return await _edge_once(text, dest, opts)
        except ProviderError:
            if attempt == 3:
                raise
            await asyncio.sleep(2 * (attempt + 1))


async def _edge_once(text: str, dest: Path, opts: dict) -> list[Word]:
    import edge_tts

    comm = edge_tts.Communicate(
        text, opts.get("model") or "pt-BR-AntonioNeural",
        rate=opts.get("rate") or "+0%", pitch=opts.get("pitch") or "+0Hz", boundary="WordBoundary")
    words: list[Word] = []
    try:
        with open(dest, "wb") as f:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    f.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append({"text": chunk["text"], "start": start, "end": start + chunk["duration"] / 1e7})
    except Exception as e:  # erros de rede do edge-tts
        raise ProviderError(f"edge-tts falhou: {e}")
    return words


def elevenlabs_key(providers_cfg: dict) -> str:
    import os
    return ((providers_cfg.get("elevenlabs") or {}).get("api_key") or os.environ.get("ELEVENLABS_API_KEY") or "").strip()


async def elevenlabs_voices(providers_cfg: dict) -> list[dict]:
    key = elevenlabs_key(providers_cfg)
    if not key:
        raise ProviderError("Configure a API key do ElevenLabs na aba Provedores")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get("https://api.elevenlabs.io/v2/voices", headers={"xi-api-key": key},
                             params={"page_size": 100})
    if r.status_code != 200:
        raise ProviderError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append({"voice_id": v["voice_id"], "name": v.get("name"), "category": v.get("category"),
                    "description": ", ".join(x for x in (labels.get("gender"), labels.get("age"),
                                                         labels.get("accent"), labels.get("description")) if x),
                    "preview_url": v.get("preview_url")})
    return out


async def elevenlabs_usage(providers_cfg: dict) -> dict:
    key = elevenlabs_key(providers_cfg)
    if not key:
        raise ProviderError("Sem API key do ElevenLabs")
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key})
    if r.status_code != 200:
        raise ProviderError(f"ElevenLabs {r.status_code}: {r.text[:200]}")
    d = r.json()
    return {"tier": d.get("tier"), "used": d.get("character_count"), "limit": d.get("character_limit"),
            "reset_unix": d.get("next_character_count_reset_unix")}


async def check_connection(providers_cfg: dict) -> dict:
    """Verifica a integridade da conexão com a API do ElevenLabs."""
    key = elevenlabs_key(providers_cfg)
    if not key:
        return {
            "status": "unconfigured",
            "api": "ElevenLabs API",
            "version": "v1",
            "error": "API Key não configurada",
        }
    try:
        import time
        t0 = time.time()
        info = await elevenlabs_usage(providers_cfg)
        latency_ms = round((time.time() - t0) * 1000)
        return {
            "status": "ok",
            "api": "ElevenLabs API",
            "version": "v1",
            "tier": info.get("tier"),
            "used": info.get("used"),
            "limit": info.get("limit"),
            "latency_ms": latency_ms,
        }
    except Exception as e:
        return {
            "status": "error",
            "api": "ElevenLabs API",
            "version": "v1",
            "error": str(e)[:300],
        }


async def _elevenlabs(text: str, dest: Path, opts: dict, providers_cfg: dict) -> list[Word]:
    key = elevenlabs_key(providers_cfg)
    voice = opts.get("voice_id")
    if not key:
        raise ProviderError("ElevenLabs sem API key (aba Provedores ou ELEVENLABS_API_KEY)")
    if not voice:
        raise ProviderError("Escolha uma voz do ElevenLabs no canal")
    model = opts.get("model") or "eleven_multilingual_v2"
    body = {
        "text": text, "model_id": model,
        "voice_settings": {
            "stability": float(opts.get("stability", 0.5)),
            "similarity_boost": float(opts.get("similarity_boost", 0.8)),
            "style": float(opts.get("style", 0.0)),
            "speed": float(opts.get("speed", 1.0)),
            "use_speaker_boost": True,
        },
    }
    if model != "eleven_v3":  # contexto entre cenas deixa a entonação contínua (v3 não aceita)
        if opts.get("previous_text"):
            body["previous_text"] = opts["previous_text"]
        if opts.get("next_text"):
            body["next_text"] = opts["next_text"]
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/with-timestamps",
            headers={"xi-api-key": key}, params={"output_format": "mp3_44100_128"}, json=body)
    if r.status_code != 200:
        detail = r.text[:300]
        if r.status_code == 401 or "quota" in detail.lower():
            detail = "sem créditos ou chave inválida: " + detail
        raise ProviderError(f"ElevenLabs {r.status_code}: {detail}")
    data = r.json()
    dest.write_bytes(base64.b64decode(data["audio_base64"]))
    al = data.get("normalized_alignment") or data.get("alignment") or {}
    chars = al.get("characters", [])
    starts = al.get("character_start_times_seconds", [])
    ends = al.get("character_end_times_seconds", [])
    words: list[Word] = []
    cur, cs, ce = "", None, 0.0
    for ch, st, en in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"text": cur, "start": cs, "end": ce})
            cur, cs = "", None
        else:
            if cs is None:
                cs = st
            cur += ch
            ce = en
    if cur:
        words.append({"text": cur, "start": cs, "end": ce})
    return words


PROVIDERS = {"edge": _edge, "elevenlabs": _elevenlabs}


TAG_RE = re.compile(r"\[[^\]\n]{1,40}\]")


def strip_tags(text: str) -> str:
    """Remove marcações de emoção ([whispers], [scared]...) do texto."""
    return re.sub(r"\s{2,}", " ", TAG_RE.sub(" ", text or "")).strip()


def supports_tags(opts: dict) -> bool:
    return opts.get("provider") == "elevenlabs" and (opts.get("model") or "").startswith("eleven_v3")


def _drop_tag_words(words: list[Word]) -> list[Word]:
    out, inside = [], False
    for w in words:
        t = w["text"]
        if t.startswith("["):
            inside = True
        if not inside:
            out.append(w)
        if t.endswith("]"):
            inside = False
    return out


async def synthesize(text: str, dest: Path, opts: dict, providers_cfg: dict) -> list[Word]:
    """As marcações de emoção só vão para o modelo que as entende (eleven_v3); nos outros, saem do texto.
    As palavras devolvidas nunca incluem as marcações (servem para a legenda)."""
    fn = PROVIDERS.get(opts.get("provider"))
    if not fn:
        raise ProviderError(f"Provedor de voz desconhecido: {opts.get('provider')}")
    spoken = text if supports_tags(opts) else strip_tags(text)
    call = dict(opts)
    for k in ("previous_text", "next_text"):
        if call.get(k):
            call[k] = strip_tags(call[k])
    return _drop_tag_words(await fn(spoken, dest, call, providers_cfg))


def even_words(text: str, duration: float) -> list[Word]:
    """Reserva quando o provedor não dá tempos: distribui pelo tamanho de cada palavra."""
    tokens = re.findall(r"\S+", text)
    total = sum(len(t) for t in tokens) or 1
    t, out = 0.0, []
    for tok in tokens:
        d = duration * len(tok) / total
        out.append({"text": tok, "start": t, "end": t + d})
        t += d
    return out


def restore_punctuation(text: str, words: list[Word]) -> list[Word]:
    """O edge-tts devolve palavras sem pontuação; recoloca usando o texto original
    (a legenda quebra melhor nas vírgulas e pontos)."""
    tokens = [t for t in re.findall(r"\S+", text) if re.search(r"\w", t)]
    if len(tokens) != len(words):
        return words
    return [{**w, "text": tok} for w, tok in zip(words, tokens)]
