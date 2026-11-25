"""Notificações via Telegram Bot e Discord Webhooks."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger("shortpipeline.notify")


async def send_telegram(bot_token: str, chat_id: str, message: str, photo: Path | None = None) -> bool:
    """Envia mensagem (e opcionalmente foto) para um chat do Telegram."""
    if not bot_token or not chat_id:
        return False
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            if photo and photo.exists():
                url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                with open(photo, "rb") as f:
                    r = await client.post(
                        url,
                        data={"chat_id": chat_id, "caption": message, "parse_mode": "HTML"},
                        files={"photo": (photo.name, f, "image/jpeg")},
                    )
            else:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                r = await client.post(
                    url,
                    json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                )
            return r.status_code == 200
        except Exception as e:
            logger.warning(f"Erro ao enviar Telegram: {e}")
            return False


async def send_discord(
    webhook_url: str,
    content: str,
    title: str | None = None,
    url: str | None = None,
    color: int = 0x6366F1,
    fields: list[dict] | None = None,
) -> bool:
    """Envia mensagem formatada com Embed para um Webhook do Discord."""
    if not webhook_url:
        return False
    payload: dict = {}
    if title:
        embed: dict = {
            "title": title,
            "description": content,
            "color": color,
        }
        if url:
            embed["url"] = url
        if fields:
            embed["fields"] = fields
        embed["footer"] = {"text": "ShortPipeline Automation"}
        payload["embeds"] = [embed]
    else:
        payload["content"] = content

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(webhook_url, json=payload)
            return r.status_code in (200, 204)
        except Exception as e:
            logger.warning(f"Erro ao enviar Discord: {e}")
            return False


async def notify_event(cfg: dict, event: str, job: dict, extra: dict | None = None) -> None:
    """Dispara notificações para os canais ativados (Telegram e/ou Discord)."""
    notif = cfg.get("notifications") or {}
    tg = notif.get("telegram") or {}
    dc = notif.get("discord") or {}

    tg_on = bool(tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"))
    dc_on = bool(dc.get("enabled") and dc.get("webhook_url"))

    if not (tg_on or dc_on):
        return

    extra = extra or {}
    job_id = job.get("id", "")
    ch_name = job.get("channel", "")
    data = job.get("data") or {}
    title = (data.get("script") or {}).get("title") or "Short sem título"
    panel_url = extra.get("panel_url") or f"http://localhost:{os.environ.get('SHORTPIPELINE_PORT', '8765')}/#job/{job_id}"

    # Capa para anexo no Telegram se houver
    cover_path = None
    cov = data.get("cover") or {}
    if cov.get("jpg") and Path(cov["jpg"]).exists():
        cover_path = Path(cov["jpg"])
    elif cov.get("image") and Path(cov["image"]).exists():
        cover_path = Path(cov["image"])

    tasks = []

    if event == "review_ready":
        tg_text = (
            f"🎬 <b>Vídeo pronto para revisão!</b>\n\n"
            f"<b>Canal:</b> {ch_name}\n"
            f"<b>Título:</b> {title}\n\n"
            f"👉 <a href='{panel_url}'>Abrir no ShortPipeline para aprovar</a>"
        )
        dc_title = "🎬 Vídeo pronto para revisão"
        dc_desc = f"O vídeo **{title}** (Canal: `{ch_name}`) foi renderizado e está aguardando aprovação."
        dc_color = 0xF59E0B  # Amarelo/Laranja

    elif event == "published":
        pub = data.get("publish") or {}
        yt_url = pub.get("url") or pub.get("studio_url")
        ig_res = pub.get("instagram") or {}

        links_html = []
        if yt_url:
            links_html.append(f"• <a href='{yt_url}'>YouTube Video / Studio</a>")
        if ig_res.get("permalink"):
            links_html.append(f"• <a href='{ig_res.get('permalink')}'>Instagram Reel</a>")

        tg_text = (
            f"🚀 <b>Vídeo Publicado com Sucesso!</b>\n\n"
            f"<b>Canal:</b> {ch_name}\n"
            f"<b>Título:</b> {title}\n"
            + ("\n<b>Links:</b>\n" + "\n".join(links_html) if links_html else "")
        )
        dc_title = "🚀 Vídeo Publicado!"
        dc_desc = f"O vídeo **{title}** foi enviado para as plataformas com sucesso!"
        dc_color = 0x10B981  # Verde

    elif event == "error":
        err_msg = extra.get("error") or "Erro desconhecido durante o pipeline."
        stage = extra.get("stage") or "execução"
        tg_text = (
            f"⚠️ <b>Erro na geração do vídeo</b>\n\n"
            f"<b>Canal:</b> {ch_name}\n"
            f"<b>Etapa:</b> {stage}\n"
            f"<b>Detalhes:</b> <code>{str(err_msg)[:300]}</code>\n\n"
            f"👉 <a href='{panel_url}'>Ver no painel</a>"
        )
        dc_title = f"⚠️ Falha na etapa: {stage}"
        dc_desc = f"Erro no vídeo **{title}**:\n```{str(err_msg)[:500]}```"
        dc_color = 0xEF4444  # Vermelho
    else:
        return

    if tg_on:
        tasks.append(send_telegram(tg["bot_token"], tg["chat_id"], tg_text, photo=cover_path))
    if dc_on:
        tasks.append(send_discord(dc["webhook_url"], dc_desc, title=dc_title, url=panel_url, color=dc_color))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
