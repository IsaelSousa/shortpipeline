"""Desenho de som: efeitos sonoros, ambiente, transições e batidas.

Ordem de busca de um som:
1. a sua biblioteca em data/sound-packs/ (fora do git, para sons que não podem ser redistribuídos);
2. o ElevenLabs (sound generation), com cache em data/sfx_cache para não pagar duas vezes;
3. os pacotes CC0 incluídos em assets/sound-packs/;
4. sons sintetizados com o FFmpeg.

Cada pacote é uma pasta. Os arquivos se chamam pelo tipo de som (impact.mp3, whoosh.ogg, scream.mp3,
ambience.mp3, ambience-rain.wav…); variações do mesmo som levam um número (scream-1.mp3, scream-2.mp3) e uma
delas é sorteada a cada uso. Um pack.json opcional limita o pacote a estilos de som e acrescenta palavras-chave:
    {"styles": ["terror"], "tags": {"scream": ["grito", "gritando"]}}
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx

from . import config
from .providers import ProviderError, run
from .providers.tts import elevenlabs_key

CACHE = config.DATA_DIR / "sfx_cache"
PACKS = config.ASSETS_DIR / "sound-packs"
AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav"}


USER_PACKS = config.DATA_DIR / "sound-packs"
LIBRARY_PRESETS = ("whoosh", "impact", "riser", "blip", "sfx")
# palavras que levam a um tipo de som quando aparecem na descrição de um efeito ou ambiente
SYNONYMS = {
    "scream": ["scream", "screams", "screaming", "shriek", "shrieks", "yell", "grito", "gritos", "grita", "gritando",
               "berro", "berra"],
    "impact": ["impact", "hit", "boom", "slam", "bang", "thud", "impacto", "batida", "pancada", "estrondo"],
    "whoosh": ["whoosh", "swoosh", "swish"],
    "riser": ["riser", "rising", "build", "crescendo"],
    "rain": ["rain", "rainfall", "chuva", "chovendo"],
    "cave": ["cave", "cavern", "dungeon", "caverna", "calabouco", "masmorra"],
    "tense": ["tense", "tension", "suspense", "paranormal", "eerie", "creepy", "dread", "tenso", "tensao",
              "sinistro", "sombrio", "arrepiante"],
}


def _norm_text(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.findall(r"[a-z0-9]+", text)


def _pack_meta(pack: Path) -> dict:
    meta = pack / "pack.json"
    if not meta.is_file():
        return {}
    try:
        data = json.loads(meta.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _packs(style: str | None, user_only: bool = False) -> list[tuple[Path, dict]]:
    """Pacotes válidos para o estilo: os seus primeiro, depois os incluídos; cada grupo em ordem alfabética."""
    roots = [USER_PACKS] if user_only else [USER_PACKS, PACKS]
    out = []
    for root in roots:
        for pack in sorted(root.iterdir()) if root.is_dir() else ():
            if not pack.is_dir():
                continue
            meta = _pack_meta(pack)
            styles = meta.get("styles")
            if styles and style and style not in styles:
                continue
            out.append((pack, meta))
    return out


def _base(path: Path) -> str:
    return re.sub(r"-\d+$", "", path.stem.lower())


def _files(pack: Path) -> list[Path]:
    return [f for f in sorted(pack.iterdir()) if f.is_file() and f.suffix.lower() in AUDIO_SUFFIXES]


def packed_sound(name: str, style: str | None = None, user_only: bool = False) -> Path | None:
    """Um som da biblioteca pelo tipo (ex.: "impact"); sorteia entre as variações do primeiro pacote que tiver."""
    for pack, _ in _packs(style, user_only):
        found = [f for f in _files(pack) if _base(f) == name]
        if found:
            return random.choice(found)
    return None


def match_sound(description: str, style: str | None, prefix: str = "") -> Path | None:
    """Procura na sua biblioteca um som cuja palavra-chave aparece na descrição (ex.: "a woman screaming" → scream).
    Com prefix="ambience", só olha ambientes."""
    words = set(_norm_text(description))
    if not words:
        return None
    for pack, meta in _packs(style, user_only=True):
        extra = {k: [w.lower() for w in v] for k, v in (meta.get("tags") or {}).items() if isinstance(v, list)}
        by_base: dict[str, list[Path]] = {}
        for f in _files(pack):
            by_base.setdefault(_base(f), []).append(f)
        for base, files in by_base.items():
            if prefix and not base.startswith(prefix):
                continue
            if not prefix and base.startswith("ambience"):
                continue
            keys = {t for t in _norm_text(base) if t != "ambience"}
            tags = set(extra.get(base, []))
            for k in keys:
                tags |= set(SYNONYMS.get(k, [k]))
            if words & {_norm_text(t)[0] for t in tags if _norm_text(t)}:
                return random.choice(files)
    return None


def library(style: str | None) -> list[dict]:
    """Sons pontuais da sua biblioteca para o estilo, para inserir pela timeline."""
    seen: dict[str, int] = {}
    for pack, _ in _packs(style, user_only=True):
        for f in _files(pack):
            base = _base(f)
            if not base.startswith("ambience"):
                seen[base] = seen.get(base, 0) + 1
    return [{"name": k, "variants": v} for k, v in sorted(seen.items())]


def in_library(path: Path) -> bool:
    path = path.resolve()
    return any(root.resolve() in path.parents for root in (USER_PACKS, PACKS))


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


AMBIENCE_SYNTH = {
    "neutro": "anoisesrc=d=10:c=pink:a=0.42:r=44100,highpass=f=100,lowpass=f=1400",
    "terror": "anoisesrc=d=10:c=brown:a=0.55:r=44100,highpass=f=38,lowpass=f=380",
    "tech": "anoisesrc=d=10:c=pink:a=0.38:r=44100,highpass=f=180,lowpass=f=800",
}


async def fallback_ambience(style: str, description: str = "") -> Path:
    """Ambiente sem o ElevenLabs: palavra-chave na biblioteca, ambiente padrão do estilo ou ruído sintetizado."""
    asset = match_sound(description, style, prefix="ambience")
    for name, pattern in (("rain", r"\b(rain|rainfall|chuva)\b"),
                          ("cave", r"\b(cave|cavern|dungeon|caverna|calabouço)\b")):
        if not asset and re.search(pattern, description, flags=re.IGNORECASE):
            asset = packed_sound(f"ambience-{name}", style)
    asset = asset or packed_sound("ambience", style)
    if asset:
        return asset
    style = style if style in AMBIENCE_SYNTH else "neutro"
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"synth_ambience_{style}.wav"
    if dest.is_file():
        return dest
    with TemporaryDirectory(dir=CACHE) as directory:
        temp = Path(directory) / dest.name
        code, _, err = await run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", AMBIENCE_SYNTH[style],
                                  "-ac", "1", "-ar", "44100", str(temp)], timeout=60)
        if code != 0:
            raise ProviderError(f"ffmpeg (ambiente sintetizado) falhou: {err[-500:]}")
        temp.replace(dest)
    return dest


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
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post("https://api.elevenlabs.io/v1/sound-generation", headers={"xi-api-key": key},
                                  params={"output_format": "mp3_44100_128"}, json=body)
            if r.status_code == 422 and loop:  # modelo sem suporte a loop: gera normal
                body.pop("loop"); body.pop("model_id")
                r = await client.post("https://api.elevenlabs.io/v1/sound-generation", headers={"xi-api-key": key},
                                      params={"output_format": "mp3_44100_128"}, json=body)
    except httpx.RequestError as exc:
        raise ProviderError(f"Não foi possível acessar o ElevenLabs para gerar som: {exc}") from exc
    if r.status_code != 200:
        raise ProviderError(f"ElevenLabs SFX {r.status_code}: {r.text[:200]}")
    dest.write_bytes(r.content)
    return dest


async def library_sound(name: str, style: str, providers_cfg: dict) -> Path:
    """Som fixo do estilo: sua biblioteca, ElevenLabs, pacote incluído ou sintetizado, nessa ordem."""
    mine = packed_sound(name, style, user_only=True)
    if mine:
        return mine
    text, dur = LIBRARY.get(style, LIBRARY["neutro"])[name]
    try:
        return await generate(text, providers_cfg, dur)
    except ProviderError:
        asset = packed_sound(name, style)
        if asset:
            return asset
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
