"""Provedores de IA. Todos usam as CLIs logadas por OAuth (sem API key)."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

# Variáveis que fariam as CLIs cobrarem por API em vez de usar o login da assinatura.
_API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CODEX_API_KEY",
                 "GEMINI_API_KEY", "GOOGLE_API_KEY")


class ProviderError(RuntimeError):
    pass


def oauth_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _API_KEY_VARS}
    env.setdefault("NO_COLOR", "1")
    return env


def resolve_bin(name: str) -> str:
    found = shutil.which(name) or (str(Path.home() / ".local/bin" / name)
                                   if (Path.home() / ".local/bin" / name).exists() else None)
    if not found:
        raise ProviderError(f"CLI '{name}' não encontrada no PATH")
    return found


async def run(args: list[str], *, stdin: bytes | None = None, cwd: str | Path | None = None,
              timeout: int = 300) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=oauth_env(),
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")
