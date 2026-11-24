"""Upload para o YouTube (Data API v3) com OAuth por canal.

Configuração única: crie um projeto no Google Cloud, ative a "YouTube Data API v3",
crie uma credencial OAuth do tipo "App para computador" e salve o JSON em
data/youtube/client_secret.json (ou no caminho definido no painel). Depois, no painel,
clique em "Conectar YouTube" em cada canal e escolha a conta/canal certo.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from . import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly",
          "https://www.googleapis.com/auth/yt-analytics.readonly"]
_pending_flows: dict[str, tuple[str, object]] = {}  # state -> (channel_id, flow)


def token_path(channel_id: str) -> Path:
    return config.YOUTUBE_DIR / f"token_{channel_id}.json"


def client_secret(cfg: dict) -> Path:
    return Path(cfg["youtube"].get("client_secret_path") or config.YOUTUBE_DIR / "client_secret.json").expanduser()


def status(cfg: dict, channel_id: str) -> dict:
    tp = token_path(channel_id)
    info = {"client_secret": client_secret(cfg).exists(), "connected": tp.exists(), "channel_title": None,
            "analytics": False}
    if tp.exists():
        try:
            data = json.loads(tp.read_text())
            info["channel_title"] = data.get("_channel_title")
            scopes = data.get("scopes") or []
            info["analytics"] = "https://www.googleapis.com/auth/yt-analytics.readonly" in (
                scopes.split() if isinstance(scopes, str) else scopes)
        except Exception:
            pass
    return info


def start_auth(cfg: dict, channel_id: str, redirect_uri: str) -> str:
    from google_auth_oauthlib.flow import Flow

    secret = client_secret(cfg)
    if not secret.exists():
        raise FileNotFoundError(f"Arquivo do OAuth não encontrado: {secret}")
    flow = Flow.from_client_secrets_file(str(secret), scopes=SCOPES, redirect_uri=redirect_uri)
    url, state = flow.authorization_url(access_type="offline", prompt="consent select_account",
                                        include_granted_scopes="true")
    _pending_flows[state] = (channel_id, flow)
    return url


def finish_auth(state: str, code: str) -> str:
    channel_id, flow = _pending_flows.pop(state)
    flow.fetch_token(code=code)
    creds = flow.credentials
    data = json.loads(creds.to_json())
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
        if items:
            data["_channel_title"] = items[0]["snippet"]["title"]
    except Exception:
        pass
    config.YOUTUBE_DIR.mkdir(parents=True, exist_ok=True)
    token_path(channel_id).write_text(json.dumps(data))
    return channel_id


def disconnect(channel_id: str) -> None:
    token_path(channel_id).unlink(missing_ok=True)


def _credentials(channel_id: str):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tp = token_path(channel_id)
    if not tp.exists():
        raise RuntimeError("Canal não conectado ao YouTube (painel → Canais → Conectar YouTube)")
    data = json.loads(tp.read_text())
    title = data.pop("_channel_title", None)
    creds = Credentials.from_authorized_user_info(data)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        new = json.loads(creds.to_json())
        if title:
            new["_channel_title"] = title
        tp.write_text(json.dumps(new))
    return creds


def check_connection(channel_id: str) -> dict:
    """Verifica a integridade da conexão com a YouTube Data API v3."""
    import time
    try:
        from googleapiclient.discovery import build
        t0 = time.time()
        creds = _credentials(channel_id)
        yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
        resp = yt.channels().list(part="snippet", mine=True).execute()
        latency_ms = round((time.time() - t0) * 1000)
        items = resp.get("items") or []
        title = items[0]["snippet"]["title"] if items else None
        return {
            "status": "ok",
            "api": "YouTube Data API",
            "version": "v3",
            "channel_title": title,
            "latency_ms": latency_ms,
        }
    except Exception as e:
        return {
            "status": "error",
            "api": "YouTube Data API",
            "version": "v3",
            "error": str(e)[:300],
        }


def _upload_sync(channel_id: str, video: Path, meta: dict, opts: dict, progress,
                 thumbnail: Path | None = None) -> dict:
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=_credentials(channel_id), cache_discovery=False)
    title = (meta.get("title") or "Short")[:100]
    if opts.get("is_short", True) and "#shorts" not in title.lower() and len(title) < 92:
        title += " #shorts"
    status = {"privacyStatus": opts.get("privacy") or "private",
              "selfDeclaredMadeForKids": bool(opts.get("made_for_kids"))}
    publish_at = None if opts.get("draft") else opts.get("publish_at")
    if opts.get("draft"):
        status["privacyStatus"] = "private"
    if publish_at:  # agendamento exige vídeo privado
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    body = {
        "snippet": {"title": title, "description": meta.get("description") or "",
                    "tags": (meta.get("tags") or [])[:30], "categoryId": str(opts.get("category_id") or "24")},
        "status": status,
    }
    req = yt.videos().insert(part="snippet,status", body=body, notifySubscribers=not opts.get("draft"),
                             media_body=MediaFileUpload(str(video), chunksize=8 * 1024 * 1024, resumable=True))
    resp = None
    while resp is None:
        st, resp = req.next_chunk()
        if st and progress:
            progress(int(st.progress() * 100))
    result = {"video_id": resp["id"], "url": f"https://youtube.com/shorts/{resp['id']}",
              "studio_url": f"https://studio.youtube.com/video/{resp['id']}/edit",
              "draft": bool(opts.get("draft")),
              "privacy": status["privacyStatus"], "publish_at": publish_at,
              "uploaded_at": datetime.now(timezone.utc).isoformat()}
    if thumbnail and thumbnail.exists():
        # Para Shorts e vídeos recém-enviados (especialmente como rascunho/privado),
        # o YouTube sobrescreve a thumbnail com um frame automático se a imagem for
        # enviada enquanto o vídeo ainda estiver sendo processado nos servidores do Google.
        # Aguardamos o processamento concluir (processingStatus == "succeeded") antes de definir a capa.
        import time as _time
        mimetype = "image/png" if thumbnail.suffix.lower() == ".png" else "image/jpeg"
        t0 = _time.time()
        applied = False
        last_err = None
        while _time.time() - t0 < 90:
            try:
                v_res = yt.videos().list(part="processingDetails,status", id=resp["id"]).execute()
                items = v_res.get("items") or []
                if items:
                    pstatus = items[0].get("processingDetails", {}).get("processingStatus")
                    if pstatus == "succeeded":
                        yt.thumbnails().set(
                            videoId=resp["id"],
                            media_body=MediaFileUpload(str(thumbnail), mimetype=mimetype, resumable=True)
                        ).execute()
                        result["thumbnail"] = True
                        applied = True
                        break
                    elif pstatus == "failed":
                        last_err = "Processamento do vídeo falhou no YouTube"
                        break
            except Exception as e:
                last_err = str(e)[:300]
            _time.sleep(3)

        if not applied:
            try:
                yt.thumbnails().set(
                    videoId=resp["id"],
                    media_body=MediaFileUpload(str(thumbnail), mimetype=mimetype, resumable=True)
                ).execute()
                result["thumbnail"] = True
            except Exception as e:
                result["thumbnail_error"] = str(last_err or e)[:300]
    return result


async def upload(channel_id: str, video: Path, meta: dict, opts: dict, progress=None,
                 thumbnail: Path | None = None) -> dict:
    return await asyncio.to_thread(_upload_sync, channel_id, video, meta, opts, progress, thumbnail)
