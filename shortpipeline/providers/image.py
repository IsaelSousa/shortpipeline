"""Geração de imagem via CLIs logadas: agy (Gemini/Antigravity) e codex.

Mesma técnica dos servidores MCP agy-image/codex-image: roda a CLI em modo não
interativo pedindo para usar a ferramenta de imagem embutida e pega o arquivo
gerado na pasta de dados da CLI.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

from . import ProviderError, resolve_bin, run
from .. import config

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
AGY_BRAIN = Path.home() / ".gemini/antigravity-cli/brain"
CODEX_IMAGES = Path.home() / ".codex/generated_images"


ASPECT_TEXT = {"9:16": "vertical 9:16 portrait", "16:9": "horizontal 16:9 landscape"}
PLACEHOLDER_SIZE = {"9:16": (1080, 1920), "16:9": (1920, 1080)}


def _prompt(description: str, aspect: str = "9:16", refs: list[Path] | None = None, attached: bool = False) -> str:
    lines = [
        "You are acting purely as an image generation backend.",
        "Use your built-in image generation tool. Do not run shell commands, do not create or edit files, "
        "and do not ask questions.",
    ]
    if refs:
        if attached:
            lines.append(f"The attached images ({', '.join(r.name for r in refs)}) are character references: "
                         "pass them to the image generation tool.")
        else:
            lines.append("Pass these files to the image generation tool as character reference images:")
            lines += [f"- {r}" for r in refs]
        lines.append("Keep the same people (face, hair, body, clothing) and the same art style as the references, "
                     "but create a NEW scene and composition as described below. Do not copy the reference framing.")
    return "\n".join(lines + [
        f"Generate exactly one image in {ASPECT_TEXT.get(aspect, ASPECT_TEXT['9:16'])} aspect ratio.",
        "Image request:\n" + description.strip(),
        "Wait until the image generation has fully finished before replying. "
        "When done, reply only with the absolute path of the generated image file.",
    ])


def _paths_in(text: str, started: float) -> list[Path]:
    found = []
    for m in re.findall(r"(/[^\s'\"`)]+\.(?:png|jpe?g|webp))", text, re.I):
        p = Path(m)
        if p.is_file() and p.stat().st_mtime >= started - 1:
            found.append(p)
    return found


def _newest(paths: list[Path]) -> Path | None:
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


# ---------------------------------------------------------------- agy
def _agy_outputs(conv: str, started: float) -> list[Path]:
    d = AGY_BRAIN / conv
    if not d.is_dir():
        return []
    out = []
    for f in d.rglob("*"):
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
            rel = f.relative_to(d).parts
            if rel and (rel[0] in (".user_uploaded", "scratch") or rel[0].startswith(".")):
                continue
            if f.stat().st_mtime >= started - 1:
                out.append(f)
    return out


def _agy_quota(started: float) -> str | None:
    log_dir = AGY_BRAIN.parent / "log"
    if not log_dir.is_dir():
        return None
    for p in log_dir.glob("*.log"):
        if p.stat().st_mtime < started - 1:
            continue
        text = p.read_text(errors="replace")
        if "RESOURCE_EXHAUSTED" in text or "QUOTA_EXHAUSTED" in text:
            m = re.search(r'"quotaResetTimeStamp":\s*"([^"]+)"', text)
            return "Cota de imagem do Antigravity esgotada" + (f" (volta em {m.group(1)} UTC)" if m else "")
    return None


async def _agy_call(bin_: str, prompt: str, model: str, timeout: int, conv: str | None,
                    add_dirs: list[Path] | None = None) -> dict:
    args = [bin_, "-p", prompt, "--output-format", "json", "--print-timeout", f"{timeout}s",
            "--disable-slash-commands"]
    for d in dict.fromkeys(add_dirs or []):
        args += ["--add-dir", str(d)]
    if model:
        args += ["--model", model]
    if conv:
        args += ["--conversation", conv]
    with tempfile.TemporaryDirectory(prefix="sp-agyimg-") as wd:
        code, out, err = await run(args, cwd=wd, timeout=timeout + 30)
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        data = {}
    if code != 0 or data.get("status") not in (None, "SUCCESS") or not data.get("conversation_id"):
        raise ProviderError(f"agy falhou (código {code}, status {data.get('status')}): {(err or out)[-500:]}")
    return data


async def _agy(description: str, model: str, timeout: int, cfg: dict) -> Path:
    bin_ = resolve_bin(cfg.get("bin") or "agy")
    started = time.time()
    refs = cfg.get("_refs") or []
    data = await _agy_call(bin_, _prompt(description, cfg.get("_aspect", "9:16"), refs), model, timeout, None,
                           [r.parent for r in refs])
    conv = data["conversation_id"]
    for attempt in range(3):
        deadline = time.time() + 30
        outs = _agy_outputs(conv, started) or _paths_in(data.get("response", ""), started)
        while not outs and time.time() < deadline:
            await asyncio.sleep(3)
            outs = _agy_outputs(conv, started)
        if outs:
            await asyncio.sleep(1)
            return _newest(outs)
        quota = _agy_quota(started)
        if quota:
            raise ProviderError(quota)
        if attempt < 2:
            data = await _agy_call(bin_, "The image was not generated yet. Generate it now with your image "
                                         "generation tool, wait for it to finish, then reply only with the path.",
                                   model, timeout, conv)
    raise ProviderError("agy terminou sem gerar imagem: " + data.get("response", "")[-300:])


# ---------------------------------------------------------------- codex
async def _codex(description: str, model: str, timeout: int, cfg: dict) -> Path:
    bin_ = resolve_bin(cfg.get("bin") or "codex")
    last_error = ""
    for attempt in range(3):
        started = time.time()
        with tempfile.TemporaryDirectory(prefix="sp-codeximg-") as wd:
            args = [bin_, "exec", "--json", "-s", "read-only", "--skip-git-repo-check", "-C", wd]
            if model:
                args += ["-m", model]
            refs = cfg.get("_refs") or []
            for r in refs:
                args += ["-i", str(r)]
            args.append("-")  # prompt pelo stdin (o -i aceita vários arquivos e engoliria o prompt)
            prompt = _prompt(description, cfg.get("_aspect", "9:16"), refs, attached=True)
            code, out, err = await run(args, stdin=prompt.encode(),
                                       cwd=wd, timeout=timeout)
        thread, messages, errors = None, [], []
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = ev.get("type", "")
            if kind == "thread.started":
                thread = ev.get("thread_id")
            elif kind == "item.completed" and ev.get("item", {}).get("type") == "agent_message":
                messages.append(ev["item"].get("text", ""))
            elif kind in ("error", "turn.failed"):
                errors.append(json.dumps(ev.get("error") or ev, ensure_ascii=False))
        outs: list[Path] = []
        deadline = time.time() + 20
        while True:
            if thread and (CODEX_IMAGES / thread).is_dir():
                outs = [f for f in (CODEX_IMAGES / thread).rglob("*")
                        if f.is_file() and f.suffix.lower() in IMAGE_EXTS and f.stat().st_mtime >= started - 1]
            outs = outs or _paths_in("\n".join(messages), started)
            if outs or not thread or time.time() > deadline:
                break
            await asyncio.sleep(2)
        if outs:
            await asyncio.sleep(0.5)
            return _newest(outs)
        last_error = "; ".join(errors) or (messages[-1] if messages else err[-400:])
        if not re.search(r"capacity|rate limit|overloaded|try again", last_error, re.I):
            break
        await asyncio.sleep(20 * (attempt + 1))
    raise ProviderError(f"codex não gerou imagem: {last_error[-500:]}")


# ---------------------------------------------------------------- placeholder
async def _placeholder(description: str, model: str, timeout: int, cfg: dict) -> Path:
    """Imagem de teste (gradiente com o texto do prompt), para testar o pipeline sem gastar cota."""
    import hashlib
    import textwrap
    h = hashlib.md5(description.encode()).hexdigest()
    pw, ph = PLACEHOLDER_SIZE.get(cfg.get("_aspect", "9:16"), (1080, 1920))
    c1, c2 = "#" + h[:6], "#" + h[6:12]
    out = Path(tempfile.mkdtemp(prefix="sp-ph-")) / "placeholder.png"
    txt = Path(out.parent / "t.txt")
    txt.write_text("\n".join(textwrap.wrap(description[:220], 28)))
    font = config.FONTS_DIR / "Anton-Regular.ttf"
    code, _, err = await run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"gradients=s={pw}x{ph}:c0={c1}:c1={c2}:x0=0:y0=0:x1={pw}:y1={ph}:d=1",
        "-vf", f"drawtext=fontfile={font}:textfile={txt}:fontsize=54:fontcolor=white:"
               "x=(w-tw)/2:y=(h-th)/2:line_spacing=12:borderw=3:bordercolor=black@0.6",
        "-frames:v", "1", str(out)], timeout=60)
    if code != 0:
        raise ProviderError(f"ffmpeg placeholder falhou: {err[-300:]}")
    return out


PROVIDERS = {"agy": _agy, "codex": _codex, "placeholder": _placeholder}


async def generate(provider: str, model: str, description: str, dest: Path, *, timeout: int,
                   providers_cfg: dict, aspect: str = "9:16", refs: list[Path] | None = None) -> Path:
    """refs: imagens de referência (personagem/estilo), aceitas pelo codex e pelo agy."""
    fn = PROVIDERS.get(provider)
    if not fn:
        raise ProviderError(f"Provedor de imagem desconhecido: {provider}")
    try:
        src = await fn(description, model, timeout, {**providers_cfg.get(provider, {}), "_aspect": aspect,
                                                   "_refs": [Path(r).resolve() for r in refs or [] if Path(r).is_file()]})
    except asyncio.TimeoutError:
        raise ProviderError(f"{provider} passou do tempo limite de {timeout}s")
    dest = dest.with_suffix(src.suffix.lower())
    shutil.copy2(src, dest)
    return dest
