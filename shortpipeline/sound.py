"""Desenho de som: efeitos sonoros, ambiente, transições e batidas.

Os efeitos vêm do ElevenLabs (sound generation) e ficam em cache em data/sfx_cache, então o
mesmo som não é pago duas vezes. Sem API key (ou sem créditos), transições e batidas são
sintetizadas com o ffmpeg, de graça; efeitos por palavra e ambiente são pulados.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from . import config
from .providers import ProviderError, run
from .providers.tts import elevenlabs_key

CACHE = config.DATA_DIR / "sfx_cache"

# Sons fixos por estilo: gerados uma vez e reaproveitados em todos os vídeos.
LIBRARY = {
    "terror": {
        "whoosh": ("dark cinematic whoosh transition, low and airy", 1.0),
        "impact": ("deep cinematic horror impact boom with sub bass and metallic hit", 2.0),
        "riser": ("horror tension riser, dissonant strings building up, ending abruptly", 2.5),
        "blip": ("short eerie low bell ding with a dark reverb tail", 1.0),
    },
    "neutro": {
        "whoosh": ("soft subtle air whoosh transition", 0.8),
        "impact": ("soft deep cinematic boom, warm and clean", 1.5),
        "riser": ("gentle airy riser building up", 2.0),
        "blip": ("soft pleasant two-note chime", 0.7),
    },
    "tech": {
        "whoosh": ("clean fast digital swoosh transition", 0.7),
        "impact": ("punchy modern tech hit with short glitch", 1.0),
        "riser": ("short synth riser building energy", 1.5),
        "blip": ("short bright futuristic synth blip, clean UI confirmation sound", 0.6),
    },
}

# Reserva sintetizada (filtros do ffmpeg), sem custo.
SYNTH = {
    "whoosh": "anoisesrc=d=0.7:c=pink:a=0.6,highpass=f=300,lowpass=f=5000,"
              "afade=t=in:d=0.35:curve=exp,afade=t=out:st=0.35:d=0.35",
    "impact": "sine=f=48:d=1.6,volume=2.5,afade=t=out:st=0.05:d=1.55:curve=exp",
    "riser": "anoisesrc=d=2.2:c=white:a=0.35,highpass=f=900,afade=t=in:d=2.1:curve=qsin,afade=t=out:st=2.1:d=0.1",
    "blip": "sine=f=1320:d=0.18,volume=0.7,afade=t=out:st=0.04:d=0.14:curve=exp",
}


def _key(text: str, duration: float | None, loop: bool) -> str:
    return hashlib.sha1(f"{text}|{duration}|{loop}".encode()).hexdigest()[:16]


async def generate(text: str, providers_cfg: dict, duration: float | None = None, loop: bool = False) -> Path:
    """Gera (ou pega do cache) um efeito sonoro do ElevenLabs."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"{_key(text, duration, loop)}.mp3"
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    key = elevenlabs_key(providers_cfg)
    if not key:
        raise ProviderError("sem API key do ElevenLabs")
    body = {"text": text, "prompt_influence": 0.45}
    if duration:
        body["duration_seconds"] = round(max(0.5, min(duration, 22.0)), 1)
    if loop:
        body["loop"] = True
        body["model_id"] = "eleven_text_to_sound_v2"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post("https://api.elevenlabs.io/v1/sound-generation", headers={"xi-api-key": key},
                              params={"output_format": "mp3_44100_128"}, json=body)
        if r.status_code == 422 and loop:  # modelo sem suporte a loop: gera normal
            body.pop("loop"); body.pop("model_id")
            r = await client.post("https://api.elevenlabs.io/v1/sound-generation", headers={"xi-api-key": key},
                                  params={"output_format": "mp3_44100_128"}, json=body)
    if r.status_code != 200:
        raise ProviderError(f"ElevenLabs SFX {r.status_code}: {r.text[:200]}")
    dest.write_bytes(r.content)
    return dest


async def library_sound(name: str, style: str, providers_cfg: dict) -> Path:
    """Som fixo do estilo (whoosh/impact/riser); cai para a versão sintetizada se não der."""
    text, dur = LIBRARY.get(style, LIBRARY["neutro"])[name]
    try:
        return await generate(text, providers_cfg, dur)
    except ProviderError:
        CACHE.mkdir(parents=True, exist_ok=True)
        dest = CACHE / f"synth_{name}.wav"
        if not dest.exists():
            code, _, err = await run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", SYNTH[name],
                                      "-ac", "1", "-ar", "44100", str(dest)], timeout=60)
            if code != 0:
                raise ProviderError(f"ffmpeg (som sintetizado) falhou: {err[-200:]}")
        return dest


async def build_mix(events: list[dict], beds: list[dict], total: float, dest: Path) -> None:
    """Monta a trilha de efeitos (mesma duração do vídeo).
    events: [{"file", "at", "volume"}] sons pontuais; beds: [{"file", "start", "dur", "volume"}] ambientes em loop."""
    inputs, filters, labels = [], [], []
    idx = 0
    for ev in events:
        inputs += ["-i", str(ev["file"])]
        ms = max(0, int(ev["at"] * 1000))
        filters.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,volume={ev['volume']:.3f},"
                       f"adelay={ms}|{ms}[e{idx}]")
        labels.append(f"[e{idx}]")
        idx += 1
    for bed in beds:
        # o loop fica no filtro (aloop): com -stream_loop -1 na entrada o ffmpeg nunca termina de ler
        inputs += ["-i", str(bed["file"])]
        ms = max(0, int(bed["start"] * 1000))
        fade = min(0.8, bed["dur"] / 3)
        filters.append(f"[{idx}:a]aresample=44100,aformat=channel_layouts=stereo,"
                       f"aloop=loop=-1:size=2147483647,atrim=0:{bed['dur']:.3f},"
                       f"asetpts=N/SR/TB,afade=t=in:d={fade:.2f},afade=t=out:st={bed['dur'] - fade:.3f}:d={fade:.2f},"
                       f"volume={bed['volume']:.3f},adelay={ms}|{ms}[e{idx}]")
        labels.append(f"[e{idx}]")
        idx += 1
    if not labels:
        return
    # base de silêncio com a duração exata do vídeo: o amix termina junto com ela
    # (apad + aloop deixava o ffmpeg girando para sempre no fim)
    inputs += ["-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    filters.append(f"[{idx}:a]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:"
                   f"normalize=0[out]")
    code, _, err = await run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *inputs, "-filter_complex",
                              ";".join(filters), "-map", "[out]", "-t", f"{total:.3f}", "-ac", "2", "-ar", "44100", str(dest)], timeout=600)
    if code != 0:
        raise ProviderError(f"ffmpeg (mix de efeitos) falhou: {err[-500:]}")
