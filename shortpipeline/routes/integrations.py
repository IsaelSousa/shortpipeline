"""Integrações: tendências, avisos, ElevenLabs, YouTube, Analytics, aprendizado e diagnóstico."""

from __future__ import annotations


import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from .. import config, upload
from ..providers import resolve_bin, ProviderError
from ..worker import worker
from .common import PORT

router = APIRouter()

@router.get("/api/trends")
async def get_trends(geo: str = "BR"):
    """Retorna tópicos em alta do Google Trends."""
    from .. import trends
    return await trends.fetch_trends(geo)


@router.post("/api/notifications/test")
async def test_notification_endpoint(body: dict = Body(...)):
    """Envia notificação de teste para Telegram ou Discord."""
    from .. import notify
    cfg = config.load()
    target = body.get("target") or body.get("service")

    if target == "telegram":
        tg = cfg.get("notifications", {}).get("telegram", {})
        token = tg.get("bot_token")
        chat_id = tg.get("chat_id")
        if not token or not chat_id:
            raise HTTPException(400, "Bot Token ou Chat ID do Telegram não configurados")
        ok = await notify.send_telegram(token, chat_id, "🔔 <b>Teste do ShortPipeline:</b> Notificações via Telegram conectadas com sucesso!")
        if not ok:
            raise HTTPException(502, "Falha ao enviar mensagem de teste pelo Telegram")
        return {"ok": True, "target": "telegram"}

    elif target == "discord":
        dc = cfg.get("notifications", {}).get("discord", {})
        webhook_url = dc.get("webhook_url")
        if not webhook_url:
            raise HTTPException(400, "Webhook URL do Discord não configurada")
        ok = await notify.send_discord(webhook_url, "Notificações via Discord Webhook conectadas com sucesso!", title="🔔 Teste do ShortPipeline", color=0x10B981)
        if not ok:
            raise HTTPException(502, "Falha ao enviar mensagem de teste pelo Discord")
        return {"ok": True, "target": "discord"}

    raise HTTPException(400, "Target inválido (deve ser 'telegram' ou 'discord')")


@router.get("/api/elevenlabs/voices")
async def el_voices():
    from ..providers import tts
    try:
        return {"voices": await tts.elevenlabs_voices(config.load()["providers"])}
    except ProviderError as e:
        raise HTTPException(400, str(e))


@router.get("/api/elevenlabs/usage")
async def el_usage():
    from ..providers import tts
    try:
        return await tts.elevenlabs_usage(config.load()["providers"])
    except ProviderError as e:
        raise HTTPException(400, str(e))


@router.post("/api/tts/preview")
async def tts_preview(body: dict = Body(...)):
    """Gera um trecho curto com a voz configurada do canal, para ouvir no painel."""
    from ..providers import tts
    cfg = config.load()
    ch = config.channel(cfg, body["channel"])
    opts = {**ch["models"]["narracao"], **(body.get("opts") or {})}
    out = config.DATA_DIR / "previews" / f"{body['channel']}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = body.get("text") or "Naquela noite, a porta do porão se abriu sozinha. E alguém desceu a escada."
    try:
        await tts.synthesize(text[:300], out, opts, cfg["providers"])
    except ProviderError as e:
        raise HTTPException(400, str(e))
    return FileResponse(out, media_type="audio/mpeg")


# ------------------------------------------------------------------ worker
@router.post("/api/worker/{action}")
def worker_action(action: str):
    if action not in ("pause", "resume"):
        raise HTTPException(400)
    worker.paused = action == "pause"
    worker.wake()
    return {"paused": worker.paused}


# ------------------------------------------------------------------ youtube
@router.get("/api/youtube")
def youtube_status():
    cfg = config.load()
    return {cid: upload.status(cfg, cid) for cid in cfg["channels"]}


@router.get("/api/youtube/connect/{cid}")
def youtube_connect(cid: str, request: Request):
    cfg = config.load()
    redirect = f"http://localhost:{request.url.port or PORT}/api/youtube/callback"
    try:
        return RedirectResponse(upload.start_auth(cfg, cid, redirect))
    except FileNotFoundError as e:
        return HTMLResponse(f"<p>{e}</p><p>Veja as instruções na aba Provedores.</p>", status_code=400)


@router.get("/api/youtube/callback")
def youtube_callback(state: str, code: str | None = None, error: str | None = None):
    if error or not code:
        return HTMLResponse(f"<p>Autorização cancelada: {error}</p><a href='/'>voltar</a>")
    try:
        upload.finish_auth(state, code)
    except KeyError:
        return HTMLResponse("<p>Sessão de login expirou; tente de novo.</p><a href='/'>voltar</a>", 400)
    return RedirectResponse("/#canais")


@router.get("/api/analytics/{cid}")
async def channel_analytics(cid: str, days: int = 28, refresh: bool = False):
    from .. import analytics
    cfg = config.load()
    if cid not in cfg["channels"]:
        raise HTTPException(404, "Canal desconhecido")
    st = upload.status(cfg, cid)
    if not st["connected"]:
        return {"state": "disconnected"}
    if not analytics.has_scope(cid):
        return {"state": "needs_reconnect"}
    try:
        return {"state": "ok", **(await analytics.report(cid, max(7, min(days, 365)), refresh))}
    except Exception as e:
        msg = str(e)
        if "accessNotConfigured" in msg or "has not been used" in msg or "is disabled" in msg:
            msg = "A YouTube Analytics API não está ativada no projeto do Google Cloud."
        raise HTTPException(502, msg[:500])


@router.get("/api/learn/{cid}")
def learn_get(cid: str):
    from .. import learn
    return {**learn.load(cid), "running": learn.running(cid)}


@router.post("/api/learn/{cid}")
async def learn_now(cid: str):
    from .. import analytics, learn
    if cid not in config.load()["channels"]:
        raise HTTPException(404, "Canal desconhecido")
    if not analytics.has_scope(cid):
        raise HTTPException(400, "Conecte o YouTube deste canal com acesso ao Analytics primeiro")
    try:
        return await learn.run(cid)
    except Exception as e:
        raise HTTPException(502, str(e)[:500])


@router.delete("/api/learn/{cid}")
def learn_clear(cid: str):
    from .. import learn
    learn.path(cid).unlink(missing_ok=True)
    return {"ok": True}


@router.delete("/api/youtube/{cid}")
def youtube_disconnect(cid: str):
    upload.disconnect(cid)
    return {"ok": True}


# ------------------------------------------------------------------ diagnóstico
@router.get("/api/diagnostics")
async def api_diagnostics(channel_id: str | None = None):
    """Executa diagnóstico em tempo real das APIs e integrações."""
    from ..providers import tts
    cfg = config.load()
    results = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "youtube": {},
        "instagram": {},
        "elevenlabs": {},
        "notifications": {},
        "cli": {},
    }

    # 1. YouTube
    cids = [channel_id] if channel_id and channel_id in cfg.get("channels", {}) else list(cfg.get("channels", {}).keys())
    for cid in cids:
        st = upload.status(cfg, cid)
        if not st.get("client_secret"):
            results["youtube"][cid] = {
                "status": "unconfigured",
                "api": "YouTube Data API",
                "version": "v3",
                "error": "client_secret.json não encontrado (veja Provedores)",
            }
        elif not st.get("connected"):
            results["youtube"][cid] = {
                "status": "disconnected",
                "api": "YouTube Data API",
                "version": "v3",
                "error": "Canal não conectado ao YouTube",
            }
        else:
            results["youtube"][cid] = await asyncio.to_thread(upload.check_connection, cid)

    # 2. Instagram Reels
    from .. import instagram
    for cid in cids:
        results["instagram"][cid] = await instagram.check_connection(cfg, cid)

    # 3. ElevenLabs
    results["elevenlabs"] = await tts.check_connection(cfg.get("providers", {}))

    # 4. Notificações
    notif = cfg.get("notifications") or {}
    results["notifications"] = {
        "telegram": bool(notif.get("telegram", {}).get("enabled") and notif.get("telegram", {}).get("bot_token")),
        "discord": bool(notif.get("discord", {}).get("enabled") and notif.get("discord", {}).get("webhook_url")),
    }

    # 5. CLIs locais
    for name in ("ffmpeg", "claude", "codex", "agy"):
        try:
            path = resolve_bin(name)
            results["cli"][name] = {"status": "ok", "path": path}
        except ProviderError:
            results["cli"][name] = {"status": "missing", "error": "Não encontrado no PATH"}

    return results
