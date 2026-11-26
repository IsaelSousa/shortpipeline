"""Geração de texto via CLIs: claude, codex e agy (Gemini/Antigravity)."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path

from . import ProviderError, resolve_bin, run

SYSTEM = ("Você é um gerador de texto usado por um pipeline automático. Não use ferramentas, não leia nem "
          "crie arquivos e não faça perguntas. Responda exatamente no formato pedido.")


async def _claude(prompt: str, model: str, timeout: int, cfg: dict) -> str:
    args = [resolve_bin(cfg.get("bin") or "claude"), "-p", "--output-format", "json", "--tools", "",
            "--no-session-persistence", "--strict-mcp-config", "--system-prompt", SYSTEM]
    if model:
        args += ["--model", model]
    with tempfile.TemporaryDirectory(prefix="sp-claude-") as wd:
        code, out, err = await run(args, stdin=prompt.encode(), cwd=wd, timeout=timeout)
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        raise ProviderError(f"claude devolveu saída inesperada (código {code}): {(err or out)[-600:]}")
    if data.get("is_error") or code != 0:
        raise ProviderError(f"claude falhou: {str(data.get('result') or err)[-600:]}")
    return data.get("result", "")


async def _codex(prompt: str, model: str, timeout: int, cfg: dict, *, image: Path | None = None) -> str:
    with tempfile.TemporaryDirectory(prefix="sp-codex-") as wd:
        last = Path(wd) / "last.txt"
        args = [resolve_bin(cfg.get("bin") or "codex"), "exec", "--json", "-s", "read-only",
                "--skip-git-repo-check", "--ephemeral", "-C", wd, "-o", str(last)]
        if model:
            args += ["-m", model]
        if image is not None:
            args += ["--image", str(image.resolve()), "--"]
        args.append("-")
        code, out, err = await run(args, stdin=(SYSTEM + "\n\n" + prompt).encode(), cwd=wd, timeout=timeout)
        text = last.read_text() if last.exists() else ""
    if not text.strip():
        errors = [ln for ln in out.splitlines() if '"error"' in ln or "turn.failed" in ln]
        raise ProviderError(f"codex falhou (código {code}): {(' '.join(errors) or err)[-600:]}")
    return text


async def _agy(prompt: str, model: str, timeout: int, cfg: dict) -> str:
    args = [resolve_bin(cfg.get("bin") or "agy"), "-p", SYSTEM + "\n\n" + prompt, "--output-format", "json",
            "--print-timeout", f"{timeout}s", "--disable-slash-commands"]
    if model:
        args += ["--model", model]
    with tempfile.TemporaryDirectory(prefix="sp-agy-") as wd:
        code, out, err = await run(args, cwd=wd, timeout=timeout + 30)
    try:
        data = json.loads(out[out.index("{"):])
    except (ValueError, json.JSONDecodeError):
        raise ProviderError(f"agy devolveu saída inesperada (código {code}): {(err or out)[-600:]}")
    if code != 0 or data.get("status") not in (None, "SUCCESS"):
        raise ProviderError(f"agy falhou (status {data.get('status')}): {(err or out)[-600:]}")
    return data.get("response", "")


PROVIDERS = {"claude": _claude, "codex": _codex, "agy": _agy}


async def generate(provider: str, model: str, prompt: str, *, timeout: int, providers_cfg: dict,
                   image: Path | None = None) -> str:
    fn = PROVIDERS.get(provider)
    if not fn:
        raise ProviderError(f"Provedor de texto desconhecido: {provider}")
    try:
        options = {"image": image} if provider == "codex" and image is not None else {}
        return await fn(prompt, model, timeout, providers_cfg.get(provider, {}), **options)
    except asyncio.TimeoutError:
        raise ProviderError(f"{provider} passou do tempo limite de {timeout}s")


def extract_json(text: str):
    """Pega o primeiro objeto JSON da resposta (tolera ```json ... ``` e texto em volta)."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    start = text.find("{")
    if start < 0:
        raise ProviderError(f"Resposta sem JSON: {text[:300]}")
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError as e:
                    raise ProviderError(f"JSON inválido na resposta: {e}")
    raise ProviderError("JSON incompleto na resposta")
