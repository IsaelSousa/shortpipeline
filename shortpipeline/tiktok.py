"""Publicação no TikTok (Content Posting API v2) com OAuth por canal.

Configuração no painel:
1. Em developers.tiktok.com, crie um aplicativo.
2. Adicione os produtos "TikTok Login Kit" e "Content Posting API".
3. Configure a Redirect URL para http://localhost:8765/api/tiktok/callback.
4. Em Provedores, insira o Client Key e Client Secret.
5. Em Canais → Revisão e publicação, clique em "Conectar TikTok".
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from . import config

TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
TIKTOK_PUBLISH_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
TIKTOK_PUBLISH_STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

SCOPES = "user.info.basic,video.upload,video.publish"

_pending_states: dict[str, str] = {}  # state -> channel_id


def token_path(channel_id: str) -> Path:
    return config.TIKTOK_DIR / f"token_{channel_id}.json"


def credentials(cfg: dict) -> tuple[str, str]:
    tt = cfg.get("tiktok") or {}
    return (tt.get("client_key") or "").strip(), (tt.get("client_secret") or "").strip()


def status(cfg: dict, channel_id: str) -> dict:
    ck, cs = credentials(cfg)
    tp = token_path(channel_id)
    info = {
        "client_configured": bool(ck and cs),
        "connected": tp.exists(),
        "username": None,
        "display_name": None,
        "avatar_url": None,
    }
    if tp.exists():
        try:
            data = json.loads(tp.read_text())
            info["username"] = data.get("username")
            info["display_name"] = data.get("display_name")
            info["avatar_url"] = data.get("avatar_url")
        except Exception:
            pass
    return info


async def check_connection(cfg: dict, channel_id: str) -> dict:
    """Verifica a integridade da conexão com a TikTok Content Posting API v2."""
    ck, cs = credentials(cfg)
    if not ck or not cs:
        return {
            "status": "unconfigured",
            "api": "TikTok Content Posting API",
            "version": "v2",
            "error": "Client Key e Secret não configurados (veja Provedores)",
        }
    tp = token_path(channel_id)
    if not tp.exists():
        return {
            "status": "disconnected",
            "api": "TikTok Content Posting API",
            "version": "v2",
            "error": "Canal não conectado ao TikTok",
        }
    try:
        token = await get_valid_token(cfg, channel_id)
        t0 = time.time()
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{TIKTOK_USER_INFO_URL}?fields=open_id,union_id,avatar_url,display_name,username",
                headers={"Authorization": f"Bearer {token}"},
            )
        latency_ms = round((time.time() - t0) * 1000)
        if res.status_code == 200:
            user = (res.json().get("data") or {}).get("user") or {}
            if user.get("username") or user.get("display_name"):
                try:
                    data = json.loads(tp.read_text())
                    data["username"] = user.get("username") or data.get("username")
                    data["display_name"] = user.get("display_name") or data.get("display_name")
                    data["avatar_url"] = user.get("avatar_url") or data.get("avatar_url")
                    tp.write_text(json.dumps(data, indent=2))
                except Exception:
                    pass
            return {
                "status": "ok",
                "api": "TikTok Content Posting API",
                "version": "v2",
                "username": user.get("username"),
                "display_name": user.get("display_name"),
                "latency_ms": latency_ms,
            }
        else:
            return {
                "status": "error",
                "api": "TikTok Content Posting API",
                "version": "v2",
                "code": res.status_code,
                "error": res.text[:200],
                "latency_ms": latency_ms,
            }
    except Exception as e:
        return {
            "status": "error",
            "api": "TikTok Content Posting API",
            "version": "v2",
            "error": str(e)[:300],
        }


def start_auth(cfg: dict, channel_id: str, redirect_uri: str) -> str:
    ck, cs = credentials(cfg)
    if not ck or not cs:
        raise ValueError("Client Key e Client Secret do TikTok não configurados (veja Provedores)")
    state = secrets.token_urlsafe(16)
    _pending_states[state] = channel_id

    params = {
        "client_key": ck,
        "scope": SCOPES,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    req = httpx.Request("GET", TIKTOK_AUTH_URL, params=params)
    return str(req.url)


async def finish_auth(cfg: dict, state: str, code: str, redirect_uri: str) -> str:
    channel_id = _pending_states.pop(state, None)
    if not channel_id:
        raise ValueError("Estado de autenticação do TikTok expirado ou inválido")
    ck, cs = credentials(cfg)

    async with httpx.AsyncClient(timeout=30) as client:
        # Obter access_token
        res = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": ck,
                "client_secret": cs,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code != 200:
            raise RuntimeError(f"Erro ao obter token do TikTok ({res.status_code}): {res.text}")
        payload = res.json()
        token_data = payload.get("data") or payload

        if not token_data.get("access_token"):
            err_msg = payload.get("error_description") or payload.get("message") or str(payload)
            raise RuntimeError(f"Falha na resposta do TikTok: {err_msg}")

        token_data["created_at"] = time.time()

        # Obter info do criador (perfil)
        try:
            user_res = await client.get(
                f"{TIKTOK_USER_INFO_URL}?fields=open_id,union_id,avatar_url,display_name,username",
                headers={"Authorization": f"Bearer {token_data['access_token']}"},
            )
            if user_res.status_code == 200:
                user_data = (user_res.json().get("data") or {}).get("user") or {}
                token_data["username"] = user_data.get("username")
                token_data["display_name"] = user_data.get("display_name")
                token_data["avatar_url"] = user_data.get("avatar_url")
        except Exception:
            pass

    config.TIKTOK_DIR.mkdir(parents=True, exist_ok=True)
    token_path(channel_id).write_text(json.dumps(token_data, indent=2))
    return channel_id


def disconnect(channel_id: str) -> None:
    token_path(channel_id).unlink(missing_ok=True)


async def get_valid_token(cfg: dict, channel_id: str) -> str:
    tp = token_path(channel_id)
    if not tp.exists():
        raise RuntimeError("Canal não conectado ao TikTok (Canais → Revisão e publicação → Conectar TikTok)")

    data = json.loads(tp.read_text())
    expires_in = data.get("expires_in") or 86400
    created_at = data.get("created_at") or 0

    # Se ainda estiver válido com pelo menos 5 minutos de folga
    if time.time() < (created_at + expires_in - 300):
        return data["access_token"]

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return data["access_token"]

    ck, cs = credentials(cfg)
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            TIKTOK_TOKEN_URL,
            data={
                "client_key": ck,
                "client_secret": cs,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code == 200:
            payload = res.json()
            new_data = payload.get("data") or payload
            if new_data.get("access_token"):
                data.update(new_data)
                data["created_at"] = time.time()
                tp.write_text(json.dumps(data, indent=2))
                return data["access_token"]

    return data["access_token"]


async def upload(
    channel_id: str,
    video: Path,
    meta: dict,
    opts: dict,
    progress: Callable[[int], None] | None = None,
) -> dict:
    """Envia vídeo para o TikTok usando a Content Posting API v2."""
    if not video.exists():
        raise FileNotFoundError(f"Arquivo de vídeo não encontrado: {video}")

    cfg = config.load()
    token = await get_valid_token(cfg, channel_id)

    video_size = video.stat().st_size
    # TikTok recomenda chunk size de pelo menos 10MB ou o tamanho total se menor que 64MB
    chunk_size = min(video_size, 10 * 1024 * 1024)
    total_chunks = (video_size + chunk_size - 1) // chunk_size

    # Preparar título / descrição
    title = meta.get("title") or "Short"
    tags = meta.get("tags") or []
    # No TikTok as hashtags entram no texto do título/legenda
    tag_str = " ".join(f"#{t.replace(' ', '')}" for t in tags[:6] if t)
    caption = f"{title} {tag_str}".strip()[:150]

    # Privacidade: SELF_ONLY (Rascunho/Privado), MUTUAL_FOLLOW_FRIENDS ou PUBLIC_TO_EVERYONE
    privacy = opts.get("tiktok_privacy") or "SELF_ONLY"
    if opts.get("draft"):
        privacy = "SELF_ONLY"

    # Timestamp da capa no TikTok:
    # A API oficial do TikTok não aceita envio de imagem externa avulsa para capa/thumbnail;
    # ela extrai um frame do próprio vídeo especificado em post_info.video_cover_timestamp_ms.
    # Como o pipeline insere a capa com texto nos primeiros frames (ex: 0.3s = 300ms),
    # definir ~150ms seleciona com precisão a capa gerada como a capa oficial no TikTok.
    cover_ms = opts.get("cover_timestamp_ms")
    if cover_ms is None:
        cover_ms = 150 if opts.get("cover_in_video", True) else 1000

    init_payload = {
        "post_info": {
            "title": caption,
            "privacy_level": privacy,
            "disable_duet": bool(opts.get("disable_duet", False)),
            "disable_stitch": bool(opts.get("disable_stitch", False)),
            "disable_comment": bool(opts.get("disable_comment", False)),
            "video_cover_timestamp_ms": int(cover_ms),
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        # 1. Iniciar upload
        init_res = await client.post(
            TIKTOK_PUBLISH_INIT_URL,
            json=init_payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
        )
        if init_res.status_code != 200:
            raise RuntimeError(f"Erro ao inicializar post no TikTok ({init_res.status_code}): {init_res.text}")

        init_data = init_res.json()
        data = init_data.get("data") or {}
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")

        if not upload_url or not publish_id:
            err = init_data.get("error", {}).get("message") or str(init_data)
            raise RuntimeError(f"TikTok não retornou URL de upload: {err}")

        # 2. Upload dos chunks
        with open(video, "rb") as f:
            for chunk_idx in range(total_chunks):
                chunk_data = f.read(chunk_size)
                start_byte = chunk_idx * chunk_size
                end_byte = start_byte + len(chunk_data) - 1

                headers = {
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{video_size}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(chunk_data)),
                }

                up_res = await client.put(upload_url, content=chunk_data, headers=headers)
                if up_res.status_code not in (200, 201, 206):
                    raise RuntimeError(f"Erro ao enviar chunk {chunk_idx + 1} para TikTok: {up_res.text}")

                if progress:
                    pct = int(((chunk_idx + 1) / total_chunks) * 100)
                    progress(pct)

        # 3. Consultar status inicial
        status_text = "PROCESSING_UPLOAD"
        for _ in range(6):
            await asyncio.sleep(2)
            try:
                st_res = await client.post(
                    TIKTOK_PUBLISH_STATUS_URL,
                    json={"publish_id": publish_id},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=UTF-8",
                    },
                )
                if st_res.status_code == 200:
                    st_data = st_res.json().get("data") or {}
                    status_text = st_data.get("status") or status_text
                    if status_text in ("PUBLISH_COMPLETE", "FAILED_TO_POST", "FAILED"):
                        break
            except Exception:
                pass

        return {
            "platform": "tiktok",
            "publish_id": publish_id,
            "status": status_text,
            "privacy": privacy,
            "caption": caption,
            "url": f"https://www.tiktok.com/",
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
