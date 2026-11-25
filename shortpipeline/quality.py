"""Inspeção do render e upscale opcional de imagens."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .providers import ProviderError, resolve_bin, run


def upscale_variant(source: Path, job_dir: Path) -> Path:
    stat = source.stat()
    return job_dir / "upscales" / f"{stat.st_mtime_ns}-{stat.st_size}.png"


def scene_image(source: Path, job_dir: Path, scene: dict) -> Path:
    if scene.get("upscale") and source.is_file():
        variant = upscale_variant(source, job_dir)
        if variant.name == scene["upscale"] and variant.is_file():
            return variant
    return source


async def inspect_render(path: Path, expected: tuple[int, int], duration: float | None) -> dict:
    code, out, err = await run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ], timeout=45)
    if code:
        raise ProviderError(f"Não foi possível inspecionar o render: {err[-300:]}")
    info = json.loads(out)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    audio = any(s["codec_type"] == "audio" for s in info["streams"])
    actual = float(info.get("format", {}).get("duration") or 0)
    width, height = video.get("width"), video.get("height")
    warnings = []
    filters = ["-map", "0:v:0", "-vf", "blackdetect=d=0.45:pix_th=0.10,freezedetect=n=-55dB:d=3"] if video else []
    if audio:
        filters += ["-map", "0:a:0", "-af", "silencedetect=n=-48dB:d=1.2,ebur128=framelog=verbose:peak=true"]
    else:
        warnings.append({"message": "O arquivo final não tem faixa de áudio."})
    if (width, height) != expected:
        warnings.append({"message": f"Resolução encontrada: {width}×{height}. Esperada: {expected[0]}×{expected[1]}."})
    if duration and abs(actual - duration) > max(0.6, duration * 0.01):
        warnings.append({"message": f"Duração de {actual:.1f}s difere dos {duration:.1f}s da timeline."})

    code, _, log = await run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "info", "-i", str(path),
                              *filters, "-f", "null", "-"], timeout=max(90, int(actual * 3)))
    if code:
        raise ProviderError(f"Falha ao analisar o render: {log[-400:]}")
    for pattern, message in (
        (r"black_start:([\d.]+)", "Trecho quase preto"),
        (r"freeze_start:\s*([\d.]+)", "Imagem quase estática por pelo menos 3s"),
        (r"silence_start:\s*([\d.]+)", "Áudio abaixo de −48 dB por pelo menos 1,2s"),
    ):
        for match in re.finditer(pattern, log):
            warnings.append({"at": float(match[1]), "message": message})
    volume = re.findall(r"^\s*I:\s*(-?[\d.]+) LUFS", log, re.M)
    peak = re.findall(r"^\s*Peak:\s*(-?[\d.]+) dBFS", log, re.M)
    true_peak = float(peak[-1]) if peak else None
    if true_peak is not None and true_peak >= -0.1:
        warnings.append({"message": "Pico verdadeiro próximo ou acima de 0 dBFS."})
    return {"width": width, "height": height, "duration": actual, "audio": audio,
            "lufs": float(volume[-1]) if volume else None, "peak": true_peak, "warnings": warnings}


def upscale_command() -> tuple[str, Path]:
    local = config.DATA_DIR / "tools" / "realesrgan" / "realesrgan-ncnn-vulkan"
    binary = str(local) if local.is_file() else resolve_bin("realesrgan-ncnn-vulkan")
    models = Path(binary).resolve().parent / "models"
    if not all((models / f"realesrgan-x4plus.{ext}").is_file() for ext in ("param", "bin")):
        raise ProviderError("Instale os modelos Real-ESRGAN x4plus ao lado do executável.")
    return binary, models


async def upscale(source: Path, dest: Path) -> None:
    binary, models = upscale_command()
    code, _, err = await run([binary, "-i", str(source), "-o", str(dest), "-m", str(models), "-n",
                              "realesrgan-x4plus", "-s", "4", "-f", "png"], timeout=240)
    if code or not dest.is_file() or any(error in err.lower() for error in ("failed", "invalid gpu")):
        raise ProviderError(f"Falha no Real-ESRGAN: {err[-500:]}")
