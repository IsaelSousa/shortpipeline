"""Montagem do vídeo com ffmpeg: Ken Burns por cena, transições, legendas ASS, música."""

from __future__ import annotations

import asyncio
import json
import random
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from . import config
from .providers import ProviderError, resolve_bin, run

W, H, FPS = 1080, 1920, 30
XFADE = 0.35  # duração da transição entre cenas, em segundos


async def ffprobe_duration(path: Path) -> float:
    code, out, err = await run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "json", str(path)], timeout=60)
    if code != 0:
        raise ProviderError(f"ffprobe falhou em {path.name}: {err[-300:]}")
    return float(json.loads(out)["format"]["duration"])


async def has_audio_stream(path: Path) -> bool:
    code, out, err = await run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                                "-show_entries", "stream=index", "-of", "csv=p=0", str(path)], timeout=30)
    if code:
        raise ProviderError(f"Não foi possível inspecionar o áudio: {err[-300:]}")
    return bool(out.strip())


async def ffmpeg(args: list[str], timeout: int = 900) -> None:
    code, _, err = await run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *args], timeout=timeout)
    if code != 0:
        raise ProviderError(f"ffmpeg falhou: {err[-800:]}")


async def clip_media_cues(source: Path) -> dict[str, list[float]]:
    base = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-i", str(source)]

    async def scan(args: list[str], pattern: str) -> list[float]:
        try:
            code, _, log = await run([*base, *args, "-f", "null", "-"], timeout=180)
        except TimeoutError:
            return []
        if code:
            return []
        points = [round(float(value), 1) for value in re.findall(pattern, log)]
        spaced = []
        for point in points:
            if not spaced or point - spaced[-1] >= 2:
                spaced.append(point)
        if len(spaced) > 80:
            spaced = [spaced[round(i * (len(spaced) - 1) / 79)] for i in range(80)]
        return spaced

    cuts, peaks = await asyncio.gather(
        scan(["-an", "-vf", "fps=4,scale=320:-2,select='gt(scene,0.35)',showinfo"], r"pts_time:\s*([\d.]+)"),
        scan(["-vn", "-af", "aresample=16000,asetnsamples=n=8000,astats=metadata=1:reset=1,"
              "ametadata=mode=select:key=lavfi.astats.Overall.Peak_level:value=-6:function=greater,"
              "ametadata=mode=print:key=lavfi.astats.Overall.Peak_level"], r"pts_time:\s*([\d.]+)"),
    )
    return {"mudancas_de_plano": cuts, "picos_de_audio": peaks}


# ------------------------------------------------------------------ áudio
async def build_narration(clips: list[Path], gap: float, dest: Path) -> list[float]:
    """Concatena as narrações das cenas com uma pausa entre elas. Devolve a duração de cada cena."""
    durations = []
    inputs, filters = [], []
    for i, clip in enumerate(clips):
        d = await ffprobe_duration(clip)
        pad = gap if i < len(clips) - 1 else 0.6
        durations.append(d + pad)
        inputs += ["-i", str(clip)]
        filters.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono,apad=pad_dur={pad}[a{i}]")
    filters.append("".join(f"[a{i}]" for i in range(len(clips))) + f"concat=n={len(clips)}:v=0:a=1[out]")
    await ffmpeg([*inputs, "-filter_complex", ";".join(filters), "-map", "[out]", "-c:a", "pcm_s16le", str(dest)])
    return durations


# ------------------------------------------------------------------ legendas
def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ts(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


EMOJI_KEYWORDS: dict[str, str] = {
    "morte": "💀", "morreu": "💀", "matou": "💀", "cadáver": "💀", "fantasma": "👻",
    "medo": "😨", "terror": "😱", "pânico": "😱", "grito": "😱", "sangue": "🩸",
    "olho": "👁️", "olhos": "👀", "olhando": "👀", "olhou": "👀", "vi": "👀", "olhe": "👀",
    "dinheiro": "💰", "milhões": "💸", "rico": "💰", "dólar": "💵", "lucro": "📈",
    "fogo": "🔥", "queimou": "🔥", "chama": "🔥", "incêndio": "🔥",
    "tempo": "⏱️", "segundo": "⏱️", "segundos": "⏱️", "minuto": "⏳", "hora": "⏰",
    "coração": "❤️", "amor": "❤️", "vida": "✨", "alma": "✨",
    "bomba": "💣", "explosão": "💥", "explodiu": "💥",
    "rápido": "⚡", "velocidade": "⚡", "choque": "⚡", "raio": "⚡",
    "segredo": "🤫", "mistério": "🔍", "porta": "🚪", "casa": "🏚️",
    "carro": "🚗", "nave": "🚀", "espaço": "🪐", "planeta": "🪐", "alien": "👽",
}

TRANSITION_PRESETS: dict[str, list[str]] = {
    "cut": ["fade"],
    "whip_pan": ["smoothleft", "smoothright", "slideleft", "slideright", "wipeleft", "wiperight"],
    "zoom_punch": ["zoomin", "circleopen", "rectcrop", "radial", "fadeblack"],
    "cinematic": ["fade", "fadeblack", "dissolve", "fadewhite"],
    "glitch": ["pixelize", "horzopen", "vertopen", "dissolve"],
    "dynamic": ["smoothleft", "zoomin", "circleopen", "fadeblack", "slideright", "dissolve"],
}


def _clean(word: str) -> str:
    return word.replace("{", "").replace("}", "").replace("\\", "")


def build_ass(words: list[dict], video: dict, dest: Path, frame: tuple[int, int] = (W, H),
              size: int | None = None) -> None:
    """Legenda estilo karaokê: blocos de N palavras, a palavra falada fica colorida e maior."""
    import re
    fw, fh = frame
    landscape = fw > fh
    font = video.get("caption_font") or "Anton"
    size = int(size or video.get("caption_size") or 92)
    margin_v = 90 if landscape else 600
    base = _ass_color(video.get("caption_color") or "#FFFFFF")
    hi = _ass_color(video.get("highlight_color") or "#FFD400")
    upper = video.get("caption_uppercase", True)
    per = max(1, int(video.get("words_per_caption") or 3))
    emojis_on = bool(video.get("dynamic_emojis", True))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {fw}
PlayResY: {fh}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{base},{base},&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,{max(4, size // 14)},4,2,70,70,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Agrupa em blocos, quebrando também em pausas longas e pontuação.
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        long_pause = nxt is not None and nxt["start"] - w["end"] > 0.45
        punct = w["text"].rstrip()[-1:] in ".!?,;:"
        if len(cur) >= per or long_pause or punct or nxt is None:
            groups.append(cur)
            cur = []

    lines = []
    for gi, g in enumerate(groups):
        # o bloco fica na tela até o próximo começar (sem piscar em pausas curtas)
        next_start = groups[gi + 1][0]["start"] if gi + 1 < len(groups) else None
        g_end = g[-1]["end"] + 0.7
        if next_start is not None:
            g_end = next_start if next_start - g[-1]["end"] < 1.2 else g[-1]["end"] + 0.5
        for j, w in enumerate(g):
            start = w["start"]
            end = g[j + 1]["start"] if j + 1 < len(g) else g_end
            parts = []
            for k, x in enumerate(g):
                t = _clean(x["text"].upper() if upper else x["text"])
                if k == j:
                    t_lookup = re.sub(r"[^\w]", "", x["text"].lower())
                    emoji = EMOJI_KEYWORDS.get(t_lookup, "") if emojis_on else ""
                    highlight_word = f"{t} {emoji}".strip() if emoji else t
                    parts.append(f"{{\\c{hi}\\fscx118\\fscy118}}{highlight_word}{{\\c{base}\\fscx100\\fscy100}}")
                else:
                    parts.append(t)
            pop = "{\\fad(40,0)}" if j == 0 else ""
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{pop}{' '.join(parts)}")
    dest.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ vídeo
def _motion(i: int, frames: int) -> tuple[str, str, str]:
    """Movimentos de câmera alternados: zoom in, zoom out, pan lateral."""
    step = 0.18 / max(frames, 1)
    kind = i % 4
    if kind == 0:   # zoom in central
        return f"1+{step}*on", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == 1:   # zoom out
        return f"1.18-{step}*on", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == 2:   # pan esquerda -> direita com zoom leve
        return "1.12", f"(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"
    return "1.12", f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-(ih/zoom/2)"


SHOT_KINDS = ["push", "punch", "pan", "detail", "pullback"]


def _camera_preset(preset: str, frames: int, index: int) -> tuple[str, str, str] | None:
    progress = f"on/{max(frames - 1, 1)}"
    eased = f"(1-cos(PI*{progress}))/2"
    x_center = "(iw-iw/zoom)/2"
    y_center = "(ih-ih/zoom)/2"
    if preset == "smooth_zoom":
        return f"1+0.22*{eased}", x_center, y_center
    if preset in ("smooth_pan", "smooth_tilt"):
        travel = eased if index % 2 == 0 else f"(1-{eased})"
        if preset == "smooth_pan":
            return "1.18", f"(iw-iw/zoom)*{travel}", y_center
        return "1.18", x_center, f"(ih-ih/zoom)*{travel}"
    return None


def _shot(kind: str, frames: int, seed: int) -> tuple[str, str, str]:
    """Enquadramentos tirados da mesma imagem: dão sensação de vários planos sem gastar outra geração."""
    t = f"on/{max(frames, 1)}"
    side = 0.33 if seed % 2 else 0.66
    if kind == "punch":     # close no terço superior (rosto/objeto principal costuma estar lá)
        return f"1.34+0.05*{t}", "iw/2-(iw/zoom/2)", "ih*0.38-(ih/zoom/2)"
    if kind == "pan":       # plano médio atravessando
        x = f"(iw-iw/zoom)*{t}" if seed % 2 else f"(iw-iw/zoom)*(1-{t})"
        return "1.18", x, "ih/2-(ih/zoom/2)"
    if kind == "detail":    # detalhe num dos terços
        return f"1.55+0.04*{t}", f"iw*{side}-(iw/zoom/2)", "ih*0.5-(ih/zoom/2)"
    if kind == "pullback":  # abre o plano
        return f"1.25-0.12*{t}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return f"1+0.08*{t}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"  # push


async def scene_clip(image: Path, duration: float, index: int, dest: Path, frame: tuple[int, int] = (W, H),
                     shots: list[float] | None = None, shake: list[tuple[float, float]] | None = None,
                     *, camera_motion: str = "") -> None:
    """Uma cena. Com `shots` (durações), a imagem vira vários planos com corte seco entre eles;
    `shake` são janelas (início, fim) em segundos relativos à cena com tremor de câmera."""
    fw, fh = frame
    total_frames = int(round(duration * FPS))
    pre = f"scale={fw * 2}:{fh * 2}:force_original_aspect_ratio=increase,crop={fw * 2}:{fh * 2}"
    if not shots or len(shots) < 2:
        frames = total_frames
        z, x, y = _camera_preset(camera_motion, frames, index) or _motion(index, frames)
        segs = [(z, x, y, frames, 0)]
    else:
        frames_list = [max(1, int(round(d * FPS))) for d in shots]
        frames_list[-1] = max(1, total_frames - sum(frames_list[:-1]))
        segs, start = [], 0
        for j, fr in enumerate(frames_list):
            kind = "push" if j == 0 else SHOT_KINDS[1 + (index + j) % (len(SHOT_KINDS) - 1)]
            z, x, y = _camera_preset(camera_motion, fr, index + j) or _shot(kind, fr, index + j)
            segs.append((z, x, y, fr, start))
            start += fr
    parts, labels = [], []
    for k, (z, x, y, fr, start) in enumerate(segs):
        jx = jy = ""
        for a, b in shake or []:
            fa, fb = int(a * FPS) - start, int(b * FPS) - start
            if fb > 0 and fa < fr:
                jx += f"+if(between(on,{fa},{fb}),34*sin(on*2.9),0)"
                jy += f"+if(between(on,{fa},{fb}),26*cos(on*3.7),0)"
        parts.append(f"[s{k}]zoompan=z='{z}':x='{x}{jx}':y='{y}{jy}':d={fr}:s={fw}x{fh}:fps={FPS},setsar=1[v{k}]")
        labels.append(f"[v{k}]")
    n = len(segs)
    graph = f"[0:v]{pre},split={n}" + "".join(f"[s{k}]" for k in range(n)) + ";" + ";".join(parts) + ";" + \
        "".join(labels) + f"concat=n={n}:v=1:a=0,format=yuv420p[v]" if n > 1 else \
        f"[0:v]{pre}[s0];{parts[0].replace('[v0]', ',format=yuv420p[v]')}"
    await ffmpeg(["-i", str(image), "-filter_complex", graph, "-map", "[v]", "-frames:v", str(total_frames),
                  "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", str(dest)])


EFFECTS = {
    "none": "",
    # granulado, vinheta, leve aberração cromática (VHS) e luz tremulando
    "terror": "eq=saturation=0.72:contrast=1.14:brightness='-0.035+0.018*sin(13*t)*sin(7.3*t)':eval=frame,"
              "rgbashift=rh=3:bh=-3,vignette=PI/4,noise=alls=5:allf=t",
    "vibrante": "eq=saturation=1.22:contrast=1.06,unsharp=5:5:0.6",
}


MUSIC_EXTS = (".mp3", ".wav", ".m4a", ".ogg")


def music_tracks(channel_id: str) -> tuple[list[Path], dict[str, str]]:
    """Músicas do canal: (comuns, especiais). Especiais são as descritas no music.json da pasta,
    {"arquivo.mp3": "quando usar"}, e só tocam quando o roteiro pede por elas."""
    folder = config.MUSIC_DIR / channel_id
    if not folder.is_dir():
        return [], {}
    tracks = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MUSIC_EXTS)
    special: dict[str, str] = {}
    meta = folder / "music.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text())
        except ValueError:
            data = {}
        names = {p.name for p in tracks}
        special = {k: str(v) for k, v in (data if isinstance(data, dict) else {}).items() if k in names and v}
    return [p for p in tracks if p.name not in special], special


def pick_music(channel_id: str, wanted: str | None = None) -> Path | None:
    """A música especial pedida pelo roteiro, se existir; senão uma comum sorteada (ou nenhuma)."""
    common, special = music_tracks(channel_id)
    if wanted and wanted in special:
        return config.MUSIC_DIR / channel_id / wanted
    return random.choice(common) if common else None


MOTION_PROJECT = config.ROOT / "motion-canvas"


def scene_media_path(job_dir: Path, name: str | None) -> Path | None:
    if not name or Path(name).name != name:
        return None
    root = (job_dir / "scene-media").resolve()
    path = (root / name).resolve()
    return path if path.parent == root and path.is_file() else None


async def scene_video_clip(source: Path, duration: float, dest: Path, frame: tuple[int, int]) -> None:
    width, height = frame
    await ffmpeg(["-stream_loop", "-1", "-i", str(source), "-map", "0:v:0", "-an",
                  "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                         f"crop={width}:{height},setsar=1,fps={FPS},format=yuv420p",
                  "-frames:v", str(max(1, round(duration * FPS))), "-c:v", "libx264",
                  "-preset", "veryfast", "-crf", "18", str(dest)])


async def motion_clip(image: Path, duration: float, dest: Path, frame: tuple[int, int], settings: dict) -> None:
    if not (MOTION_PROJECT / "dist" / "scene.js").is_file():
        raise ProviderError("Motion Canvas indisponível. Execute npm ci e npm run build em motion-canvas.")
    width, height = frame
    frames = max(1, round(duration * FPS))
    with TemporaryDirectory(dir=dest.parent) as directory:
        folder = Path(directory)
        spec = {**settings, "duration": frames / FPS, "width": width, "height": height, "fps": FPS}
        if settings["template"] != "comparison":
            background = folder / "background.jpg"
            await ffmpeg(["-i", str(image), "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                          f"crop={width}:{height}", "-frames:v", "1", str(background)])
            spec["image"] = str(background)
        spec_file = folder / "scene.json"
        spec_file.write_text(json.dumps(spec), encoding="utf-8")
        code, _, err = await run([resolve_bin("node"), str(MOTION_PROJECT / "render.mjs"), str(spec_file), str(folder)],
                                  timeout=max(90, int(duration * 35)))
        if code:
            raise ProviderError(f"Motion Canvas falhou: {err[-600:]}")
        if len(list(folder.glob("[0-9]*.jpg"))) != frames:
            raise ProviderError(f"Motion Canvas não exportou os {frames} quadros esperados")
        await ffmpeg(["-framerate", str(FPS), "-i", str(folder / "%06d.jpg"), "-c:v", "libx264",
                      "-preset", "veryfast", "-crf", "18", "-vf", "setsar=1,format=yuv420p", "-an", str(dest)])


def audio_filters(f: list[str], na: int, mi: int | None, si: int | None, video: dict, beats: list[float],
                  total: float) -> None:
    """Acrescenta ao filtro a mixagem final em [a]: voz + música (abaixa quando a voz fala e some antes dos sustos)
    + efeitos, com o mixer de volume individual (audio_levels)."""
    levels = video.get("audio_levels") or {}
    voice_mul = float(levels.get("voice", 1.0))
    bgm_mul = float(levels.get("bgm", 1.0))
    sfx_mul = float(levels.get("sfx", 1.0))

    mix = []
    if mi is not None:
        f.append(f"[{na}:a]aresample=44100,aformat=channel_layouts=stereo,volume={voice_mul:.2f},asplit=2[nv][nk]")
        vol = float(video.get("music_volume") or 0.1) * 1.8 * bgm_mul
        dips = "".join(f",volume=0:enable='between(t,{b - 0.7:.2f},{b + 0.2:.2f})'" for b in beats)
        f.append(f"[{mi}:a]aresample=44100,aformat=channel_layouts=stereo,volume={vol:.3f}{dips},"
                 f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5[mraw]")
        f.append("[mraw][nk]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[m]")
        mix += ["[nv]", "[m]"]
    else:
        f.append(f"[{na}:a]aresample=44100,aformat=channel_layouts=stereo,volume={voice_mul:.2f}[nv]")
        mix.append("[nv]")
    if si is not None:
        f.append(f"[{si}:a]aresample=44100,aformat=channel_layouts=stereo,volume={sfx_mul:.2f}[sx]")
        mix.append("[sx]")
    if len(mix) > 1:
        f.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:dropout_transition=0:normalize=0,"
                 "alimiter=limit=0.95[a]")
    else:
        f.append("[nv]anull[a]")


async def render_video(job_dir: Path, images: list[Path], durations: list[float], narration: Path,
                       ass: Path | None, video: dict, channel_id: str, dest: Path, log=None,
                       cover: Path | None = None, cover_seconds: float = 0.3,
                       frame: tuple[int, int] = (W, H), shots: list[list[float]] | None = None,
                       beats: list[float] | None = None, sfx: Path | None = None, flash: bool = False,
                       meter: dict | None = None, motions: list[dict | None] | None = None,
                       scene_videos: list[Path | None] | None = None, music: Path | None | str = "auto") -> None:
    """`shots`: durações dos planos de cada cena; `beats`: instantes (s) de susto/revelação, que ganham
    tremor, flash (se `flash`) e um respiro na música; `sfx`: trilha de efeitos já mixada;
    `meter`: selo de nota no fim do vídeo ({"score", "label", "start", "end", "color"})."""
    fw, fh = frame
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(exist_ok=True)
    n = len(images)
    beats = beats or []
    # cada clipe ganha XFADE extra para sobrepor na transição (menos o último)
    lens = [d + (XFADE if i < n - 1 else 0) for i, d in enumerate(durations)]
    starts = [sum(durations[:i]) for i in range(n)]
    sem = asyncio.Semaphore(4)

    async def one(i):
        sh = None
        if shots and i < len(shots) and shots[i]:
            sh = list(shots[i])
            sh[-1] += lens[i] - sum(sh)  # o último plano absorve a sobra da transição
        shake = [(b - starts[i] - 0.05, b - starts[i] + 0.45) for b in beats if starts[i] <= b < starts[i] + lens[i]]
        async with sem:
            clip = clips_dir / f"{i:02d}.mp4"
            motion = motions[i] if motions and i < len(motions) else None
            custom_video = scene_videos[i] if scene_videos else None
            if custom_video:
                await scene_video_clip(custom_video, lens[i], clip, frame)
            elif motion:
                await motion_clip(images[i], lens[i], clip, frame, motion)
            else:
                await scene_clip(images[i], lens[i], i, clip, frame, sh, shake,
                                 camera_motion=video.get("camera_motion", ""))
            if log:
                log(f"Cena {i + 1}/{n} renderizada")

    await asyncio.gather(*(one(i) for i in range(n)))

    inputs = []
    for i in range(n):
        inputs += ["-i", str(clips_dir / f"{i:02d}.mp4")]
    na = n
    inputs += ["-i", str(narration)]
    nxt = n + 1
    if music == "auto":
        music = pick_music(channel_id)
    mi = si = cover_idx = None
    if music:
        mi = nxt; nxt += 1
        inputs += ["-stream_loop", "-1", "-i", str(music)]
    if sfx and sfx.exists():
        si = nxt; nxt += 1
        inputs += ["-i", str(sfx)]
    if cover and cover.exists():
        cover_idx = nxt; nxt += 1
        inputs += ["-i", str(cover)]
    meter_idx = None
    if meter:
        meter_idx = nxt; nxt += 1
        mc = (meter.get("color") or "#22D3EE").lstrip("#")
        tw, th, d = METER["track_w"], METER["track_h"], float(meter["end"]) + 0.5
        inputs += ["-f", "lavfi", "-i",
                   f"color=c=0x{mc}:s={tw}x{th}:r={FPS}:d={d:.2f}[l];color=c={METER['track_bg']}:s={tw}x{th}:r={FPS}:d={d:.2f}[r];"
                   "[l][r]hstack"]

    f = []
    last = "[0:v]"
    offset = 0.0
    t_style = video.get("transition_style") or "dynamic"
    transitions = TRANSITION_PRESETS.get(t_style, TRANSITION_PRESETS["dynamic"])
    for i in range(1, n):
        offset += durations[i - 1]
        out = f"[x{i}]"
        f.append(f"{last}[{i}:v]xfade=transition={transitions[i % len(transitions)]}:"
                 f"duration={XFADE}:offset={offset:.3f}{out}")
        last = out
    total = sum(durations)
    fx = EFFECTS.get(video.get("effects") or "none", "")
    flashes = ",".join(f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.6:t=fill:enable='between(t,{b:.3f},{b + 0.07:.3f})'"
                       for b in beats) if flash else ""
    chain = ",".join(x for x in (fx, flashes, f"ass='{ass}':fontsdir='{config.FONTS_DIR}'" if ass else "") if x) or "null"
    if meter_idx is not None:
        f.append(f"{last}{chain}[vpre]")
        f += _meter_filters("[vpre]", meter_idx, meter, job_dir, "[vm]")
        last, chain = "[vm]", "null"
    if cover_idx is not None:
        # capa nos primeiros frames: é o frame que o YouTube costuma usar no feed de Shorts
        f.append(f"{last}{chain}[vs]")
        f.append(f"[{cover_idx}:v]scale={fw}:{fh},setsar=1[cov]")
        f.append(f"[vs][cov]overlay=0:0:enable='lt(t,{cover_seconds:.2f})',format=yuv420p[v]")
    else:
        f.append(f"{last}{chain},format=yuv420p[v]")

    audio_filters(f, na, mi, si, video, beats, total)
    await ffmpeg([*inputs, "-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]",
                  "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                  "-maxrate", "8M", "-bufsize", "16M", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ac", "2",
                  "-movflags", "+faststart", str(dest)],
                 timeout=max(1800, int(total * 8)))



async def mux_animation(silent: Path, narration: Path, video: dict, channel_id: str, dest: Path, *, total: float,
                        sfx: Path | None = None, beats: list[float] | None = None,
                        music: Path | None | str = "auto") -> Path | None:
    """Vídeo animado (sem som) + a mesma mixagem do short: voz, música com ducking e trilha de efeitos.
    Devolve a música usada."""
    inputs = ["-i", str(silent), "-i", str(narration)]
    nxt, mi, si = 2, None, None
    if music == "auto":
        music = pick_music(channel_id)
    if music:
        mi, nxt = nxt, nxt + 1
        inputs += ["-stream_loop", "-1", "-i", str(music)]
    if sfx and sfx.exists():
        si, nxt = nxt, nxt + 1
        inputs += ["-i", str(sfx)]
    f: list[str] = []
    audio_filters(f, 1, mi, si, video, beats or [], total)
    await ffmpeg([*inputs, "-filter_complex", ";".join(f), "-map", "0:v", "-map", "[a]", "-t", f"{total:.3f}",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-movflags", "+faststart", str(dest)])
    return music if isinstance(music, Path) else None

METER = {"x": 110, "y": 300, "w": 860, "h": 230, "track_x": 160, "track_y": 450, "track_w": 760, "track_h": 44,
         "panel": "0x0B0F19", "track_bg": "0x32363E"}  # trilha = branco 16% sobre o painel, já misturado


def _meter_filters(src: str, idx: int, m: dict, job_dir: Path, out: str) -> list[str]:
    """Selo de nota (ex.: "NOTA 8/10"): painel escuro, barra que enche animada e a nota. O drawbox não anima, então a
    barra vem de uma faixa [cor | fundo] com o dobro da largura, recortada por uma janela (crop) que anda."""
    g = METER
    t0, t1 = float(m["start"]), float(m["end"])
    score = max(0.0, min(10.0, float(m.get("score") or 0)))
    en = f"between(t,{t0:.3f},{t1:.3f})"
    tdir = job_dir / "_meter"
    tdir.mkdir(exist_ok=True)
    (tdir / "label.txt").write_text((m.get("label") or "NOTA").upper(), encoding="utf-8")
    (tdir / "score.txt").write_text(f"{score:g}/10", encoding="utf-8")
    font = font_file("Anton")
    fill_w = g["track_w"] * score / 10
    prog = f"min(1,max(0,(t-{t0 + 0.15:.3f})/0.7))"
    color = "0x" + (m.get("color") or "#22D3EE").lstrip("#")
    alpha = f"min(1,max(0,(t-{t0:.3f})/0.25))"
    return [
        f"{src}drawbox=x={g['x']}:y={g['y']}:w={g['w']}:h={g['h']}:color={g['panel']}:t=fill:enable='{en}',"
        f"drawbox=x={g['x']}:y={g['y']}:w={g['w']}:h={g['h']}:color={color}@0.9:t=5:enable='{en}'[mt]",
        f"[{idx}:v]setsar=1,crop=w={g['track_w']}:h={g['track_h']}:x='{g['track_w']}-{fill_w:.1f}*{prog}':y=0[mf]",
        f"[mt][mf]overlay=x={g['track_x']}:y={g['track_y']}:enable='{en}':eof_action=pass,"
        f"drawtext=fontfile='{font}':textfile='{tdir / 'label.txt'}':fontsize=64:fontcolor=white:alpha='{alpha}':"
        f"x={g['track_x']}:y={g['y'] + 40}:enable='{en}',"
        f"drawtext=fontfile='{font}':textfile='{tdir / 'score.txt'}':fontsize=104:fontcolor={color}:alpha='{alpha}':"
        f"x={g['track_x'] + g['track_w']}-text_w:y={g['y'] + 18}:enable='{en}'{out}",
    ]


async def render_clip(src: Path, ass: Path | None, dest: Path, cover: Path | None = None,
                      cover_seconds: float = 0.3) -> None:
    """Corte: vídeo já reenquadrado em 9:16 + legenda + capa nos primeiros frames + áudio normalizado."""
    inputs = ["-i", str(src)]
    chain = f"ass='{ass}':fontsdir='{config.FONTS_DIR}'" if ass else "null"
    f = []
    if cover and cover.exists():
        inputs += ["-i", str(cover)]
        f.append(f"[0:v]{chain}[vs]")
        f.append(f"[1:v]scale={W}:{H},setsar=1[cov]")
        f.append(f"[vs][cov]overlay=0:0:enable='lt(t,{cover_seconds:.2f})',format=yuv420p[v]")
    else:
        f.append(f"[0:v]{chain},format=yuv420p[v]")
    f.append("[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    await ffmpeg([*inputs, "-filter_complex", ";".join(f), "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-maxrate", "12M", "-bufsize", "24M",
                  "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", str(dest)])


# ------------------------------------------------------------------ capa
def font_file(name: str) -> Path:
    for p in sorted(config.FONTS_DIR.glob("*.ttf")):
        if p.stem.split("-")[0].lower() == (name or "").lower():
            return p
    return config.FONTS_DIR / "Anton-Regular.ttf"


def wrap_cover_text(text: str, max_chars: int = 12) -> list[tuple[str, bool]]:
    """Quebra o texto em linhas curtas. Palavras entre [colchetes] destacam a linha inteira.
    Devolve [(linha, destacada)]."""
    import re

    words = text.split()
    lines: list[list[str]] = [[]]
    for w in words:
        cur = lines[-1]
        plain_len = len(" ".join(re.sub(r"[\[\]]", "", x) for x in cur + [w]))
        if cur and plain_len > max_chars:
            lines.append([w])
        else:
            cur.append(w)
    out = []
    for ln in lines:
        raw = " ".join(ln)
        out.append((re.sub(r"[\[\]]", "", raw), "[" in raw))
    if out and not any(h for _, h in out) and len(out) > 1:
        out[-1] = (out[-1][0], True)  # sem marcação: destaca a última linha
    return out


async def build_cover(bg: Path, text: str, opts: dict, dest_png: Path, dest_jpg: Path,
                      frame: tuple[int, int] = (W, H)) -> None:
    """Capa (1080x1920 nos shorts, 1280x720 nos longos): fundo recortado, escurecido, com o título por cima."""
    fw, fh = frame
    landscape = fw > fh
    tmp = dest_png.parent / "_cover_txt"
    tmp.mkdir(exist_ok=True)
    darken = float(opts.get("darken") if opts.get("darken") is not None else 0.25)
    vf = [f"scale={fw}:{fh}:force_original_aspect_ratio=increase", f"crop={fw}:{fh}", "setsar=1",
          f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{darken:.2f}:t=fill", "vignette=PI/5"]
    text = (text or "").strip()
    if text:
        lines = wrap_cover_text(text.upper(), 16 if landscape else 12)
        longest = max(len(t) for t, _ in lines)
        if landscape:
            size = max(70, min(150, int(1180 / (0.5 * max(longest, 4)))))
        else:
            size = int(opts.get("font_size") or 0) or max(96, min(190, int(1000 / (0.5 * max(longest, 4)))))
        line_h = int(size * 1.16)
        total = line_h * len(lines)
        pos = opts.get("position") or "top"
        has_badge = bool((opts.get("badge") or "").strip())
        if landscape:
            y0 = {"top": 120 if has_badge else 60, "center": (fh - total) // 2, "bottom": fh - total - 60}.get(pos, 60)
        else:
            y0 = {"top": 290 if has_badge else 230, "center": (fh - total) // 2, "bottom": fh - total - 360}.get(pos, 230)
        font = font_file(opts.get("font") or "Anton")
        base_c = (opts.get("text_color") or "#FFFFFF").lstrip("#")
        hi_c = (opts.get("highlight_color") or "#FFD400").lstrip("#")
        for i, (line, hi) in enumerate(lines):
            tf = tmp / f"{i}.txt"
            tf.write_text(line, encoding="utf-8")
            vf.append(
                f"drawtext=fontfile='{font}':textfile='{tf}':fontsize={size}:fontcolor=0x{hi_c if hi else base_c}:"
                f"borderw={max(6, size // 14)}:bordercolor=black:shadowx=0:shadowy={size // 16}:shadowcolor=black@0.55:"
                f"x=(w-text_w)/2:y={y0 + i * line_h}")
    badge = (opts.get("badge") or "").strip()
    if badge:  # selo da série (ex.: CASO #047) no topo
        bf = tmp / "badge.txt"
        bf.write_text(badge.upper(), encoding="utf-8")
        bsize = 54 if landscape else 64
        hi = (opts.get("highlight_color") or "#FFD400").lstrip("#")
        by = 24 if landscape else 130
        vf.append(f"drawtext=fontfile='{font_file(opts.get('badge_font') or opts.get('font') or 'Anton')}':textfile='{bf}':"
                  f"fontsize={bsize}:fontcolor=white:box=1:boxcolor=0x{hi}@0.92:boxborderw=18|30:"
                  f"x=(w-text_w)/2:y={by}")
    await ffmpeg(["-i", str(bg), "-vf", ",".join(vf), "-frames:v", "1", str(dest_png)])
    # JPG para thumbnail do YouTube (limite de 2 MB)
    await ffmpeg(["-i", str(dest_png), "-q:v", "3", str(dest_jpg)])
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
