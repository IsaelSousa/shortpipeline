"""Publicação no Instagram Reels (Meta Graph API) via Resumable Binary Upload.

Permite o envio direto de vídeos locais sem necessidade de URL pública ou túnel.
Requer:
- Conta Profissional do Instagram (Business ou Creator) vinculada a uma Página do Facebook.
- Token de Acesso (User/Page Access Token) com escopos: instagram_basic, instagram_content_publish.
- ID da Conta do Instagram (Instagram Account ID).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable

import httpx

from . import config

logger = logging.getLogger("shortpipeline.instagram")

GRAPH_API_VERSION = "v21.0"
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def credentials(cfg: dict, channel_id: str | None = None) -> tuple[str, str]:
    """Retorna (access_token, account_id) da configuração global ou do canal."""
    ig_global = cfg.get("instagram") or {}
    token = (ig_global.get("access_token") or "").strip()
    account_id = (ig_global.get("account_id") or "").strip()

    if channel_id:
        ch = (cfg.get("channels") or {}).get(channel_id) or {}
        ch_ig = ch.get("instagram") or {}
        if ch_ig.get("access_token"):
            token = ch_ig["access_token"].strip()
        if ch_ig.get("account_id"):
            account_id = ch_ig["account_id"].strip()

    return token, account_id


def status(cfg: dict, channel_id: str | None = None) -> dict:
    """Verifica se o canal tem credenciais do Instagram configuradas."""
    token, account_id = credentials(cfg, channel_id)
    return {
        "configured": bool(token and account_id),
        "account_id": account_id if account_id else None,
    }


async def check_connection(cfg: dict, channel_id: str | None = None) -> dict:
    """Valida a conexão com a Meta Graph API e retorna dados do perfil do Instagram."""
    token, account_id = credentials(cfg, channel_id)
    if not token or not account_id:
        return {
            "status": "unconfigured",
            "api": "Meta Graph API (Instagram Reels)",
            "version": GRAPH_API_VERSION,
            "error": "Access Token ou Account ID do Instagram não configurados",
        }
    try:
        t0 = time.time()
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{GRAPH_BASE_URL}/{account_id}",
                params={
                    "fields": "id,username,name,profile_picture_url",
                    "access_token": token,
                },
            )
        latency_ms = round((time.time() - t0) * 1000)
        if res.status_code == 200:
            data = res.json()
            return {
                "status": "ok",
                "api": "Meta Graph API (Instagram Reels)",
                "version": GRAPH_API_VERSION,
                "username": data.get("username"),
                "name": data.get("name"),
                "account_id": data.get("id"),
                "latency_ms": latency_ms,
            }
        else:
            err = res.json().get("error", {}).get("message") or res.text[:200]
            return {
                "status": "error",
                "api": "Meta Graph API (Instagram Reels)",
                "version": GRAPH_API_VERSION,
                "code": res.status_code,
                "error": err,
                "latency_ms": latency_ms,
            }
    except Exception as e:
        return {
            "status": "error",
            "api": "Meta Graph API (Instagram Reels)",
            "version": GRAPH_API_VERSION,
            "error": str(e)[:300],
        }


async def upload(
    channel_id: str,
    video: Path,
    meta: dict,
    opts: dict,
    progress: Callable[[int], None] | None = None,
) -> dict:
    """Envia vídeo para o Instagram Reels usando Resumable Binary Upload da Meta Graph API."""
    if not video.exists():
        raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {video}")

    cfg = config.load()
    token, account_id = credentials(cfg, channel_id)
    if not token or not account_id:
        raise RuntimeError("Instagram não configurado (Access Token ou Account ID ausentes)")

    video_size = video.stat().st_size
    title = meta.get("title") or "Short"
    tags = meta.get("tags") or []
    tag_str = " ".join(f"#{t.replace(' ', '')}" for t in tags[:10] if t)
    caption = f"{title}\n\n{tag_str}".strip()[:2200]

    async with httpx.AsyncClient(timeout=120) as client:
        # 1. Inicializar sessão de upload resumable
        if progress:
            progress(10)
        init_res = await client.post(
            f"{GRAPH_BASE_URL}/{account_id}/media",
            data={
                "access_token": token,
                "upload_type": "resumable",
                "media_type": "REELS",
                "caption": caption,
            },
        )
        if init_res.status_code != 200:
            err = init_res.json().get("error", {}).get("message") or init_res.text
            raise RuntimeError(f"Erro ao iniciar container do Reels ({init_res.status_code}): {err}")

        init_data = init_res.json()
        container_id = init_data.get("id")
        upload_uri = init_data.get("uri")

        if not container_id or not upload_uri:
            raise RuntimeError(f"Resposta inválida da Meta: {init_data}")

        # 2. Upload do arquivo binário diretamente para a Meta (rupload.facebook.com)
        if progress:
            progress(30)
        with open(video, "rb") as f:
            video_bytes = f.read()

        upload_res = await client.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {token}",
                "file_size": str(video_size),
                "offset": "0",
                "Content-Type": "application/octet-stream",
            },
            content=video_bytes,
        )
        if upload_res.status_code not in (200, 204):
            err = upload_res.text[:300]
            raise RuntimeError(f"Falha no envio do binário para o Instagram: {err}")

        if progress:
            progress(60)

        # 3. Aguardar processamento do vídeo pela Meta (status_code == FINISHED)
        poll_start = time.time()
        container_ready = False
        while time.time() - poll_start < 120:
            st_res = await client.get(
                f"{GRAPH_BASE_URL}/{container_id}",
                params={"fields": "status_code,status", "access_token": token},
            )
            if st_res.status_code == 200:
                st_data = st_res.json()
                status_code = st_data.get("status_code")
                if status_code == "FINISHED":
                    container_ready = True
                    break
                elif status_code == "ERROR":
                    err_msg = st_data.get("status", {}).get("error", {}).get("message") or str(st_data)
                    raise RuntimeError(f"Erro no processamento do Reel pela Meta: {err_msg}")
            await asyncio.sleep(4)

        if not container_ready:
            raise RuntimeError("Tempo limite de processamento do vídeo no Instagram excedido")

        if progress:
            progress(85)

        # 4. Publicar o container
        pub_res = await client.post(
            f"{GRAPH_BASE_URL}/{account_id}/media_publish",
            data={
                "access_token": token,
                "creation_id": container_id,
            },
        )
        if pub_res.status_code != 200:
            err = pub_res.json().get("error", {}).get("message") or pub_res.text
            raise RuntimeError(f"Erro ao publicar Reel no Instagram ({pub_res.status_code}): {err}")

        media_id = pub_res.json().get("id")

        # 5. Buscar link permanente (permalink)
        permalink = None
        try:
            link_res = await client.get(
                f"{GRAPH_BASE_URL}/{media_id}",
                params={"fields": "permalink", "access_token": token},
            )
            if link_res.status_code == 200:
                permalink = link_res.json().get("permalink")
        except Exception:
            pass

        if progress:
            progress(100)

        return {
            "status": "published",
            "media_id": media_id,
            "permalink": permalink or f"https://www.instagram.com/reel/{media_id}",
            "container_id": container_id,
            "uploaded_at": time.time(),
        }
