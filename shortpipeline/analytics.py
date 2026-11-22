"""Métricas dos canais: YouTube Data API (números gerais) + YouTube Analytics API (relatórios).

Precisa do escopo yt-analytics.readonly: canais conectados antes dele precisam reconectar.
Os resultados ficam em cache por alguns minutos para poupar cota.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, timedelta

from . import config, db, upload

ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
CACHE_TTL = 600
_cache: dict[tuple, tuple[float, dict]] = {}

METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage",
           "subscribersGained", "subscribersLost", "likes", "comments", "shares"]

TRAFFIC_LABELS = {
    "SHORTS": "Feed de Shorts", "YT_SEARCH": "Pesquisa do YouTube", "SUBSCRIBER": "Inscritos / página inicial",
    "RELATED_VIDEO": "Vídeos sugeridos", "BROWSE": "Recursos de navegação", "YT_OTHER_PAGE": "Outras páginas do YouTube",
    "EXT_URL": "Sites externos", "NO_LINK_OTHER": "Direto / desconhecido", "NOTIFICATION": "Notificações",
    "PLAYLIST": "Playlists", "YT_CHANNEL": "Páginas de canal", "HASHTAGS": "Hashtags", "END_SCREEN": "Tela final",
    "ANNOTATION": "Cards", "SOUND_PAGE": "Página de áudio", "VIDEO_REMIXES": "Remixes", "CAMPAIGN_CARD": "Campanhas",
    "ADVERTISING": "Anúncios", "PRODUCT_PAGE": "Página de produto", "LIVE_REDIRECT": "Redirecionamento de live",
    "YT_PLAYLIST_PAGE": "Página de playlist", "IMMERSIVE_LIVE": "Live imersiva",
}


def has_scope(channel_id: str) -> bool:
    tp = upload.token_path(channel_id)
    if not tp.exists():
        return False
    scopes = json.loads(tp.read_text()).get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()
    return ANALYTICS_SCOPE in scopes


def _content_label(v: str) -> str:
    v = (v or "").lower()
    if "short" in v:
        return "Shorts"
    if "demand" in v or v == "video":
        return "Vídeos"
    if "live" in v:
        return "Lives"
    if "post" in v or "story" in v:
        return "Posts"
    return "Outros"


def _iso_seconds(d: str) -> int:
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s


def _rows_to_dicts(resp: dict) -> list[dict]:
    names = [h["name"] for h in resp.get("columnHeaders", [])]
    return [dict(zip(names, r)) for r in resp.get("rows") or []]


def _report_sync(channel_id: str, days: int) -> dict:
    from googleapiclient.discovery import build

    creds = upload._credentials(channel_id)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    ch_items = yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", [])
    if not ch_items:
        raise RuntimeError("A conta conectada não tem canal do YouTube")
    ch = ch_items[0]
    channel = {
        "id": ch["id"], "title": ch["snippet"]["title"],
        "thumbnail": (ch["snippet"].get("thumbnails", {}).get("default") or {}).get("url"),
        "subscribers": int(ch["statistics"].get("subscriberCount", 0)),
        "views": int(ch["statistics"].get("viewCount", 0)),
        "videos": int(ch["statistics"].get("videoCount", 0)),
        "hidden_subscribers": ch["statistics"].get("hiddenSubscriberCount", False),
    }

    end = date.today()
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    def q(start_d, end_d, metrics, **kw):
        return ya.reports().query(ids="channel==MINE", startDate=start_d.isoformat(), endDate=end_d.isoformat(),
                                  metrics=",".join(metrics), **kw).execute()

    totals = (_rows_to_dicts(q(start, end, METRICS)) or [{}])[0]
    prev = (_rows_to_dicts(q(prev_start, prev_end, METRICS)) or [{}])[0]

    daily_rows = {r["day"]: r for r in _rows_to_dicts(
        q(start, end, ["views", "estimatedMinutesWatched", "subscribersGained", "subscribersLost"],
          dimensions="day", sort="day"))}
    daily = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        r = daily_rows.get(d, {})
        daily.append({"day": d, "views": r.get("views", 0), "minutes": r.get("estimatedMinutesWatched", 0),
                      "subs": r.get("subscribersGained", 0) - r.get("subscribersLost", 0)})

    content = []
    try:
        for r in _rows_to_dicts(q(start, end, ["views", "estimatedMinutesWatched"], dimensions="creatorContentType")):
            content.append({"type": _content_label(r["creatorContentType"]), "views": r["views"],
                            "minutes": r["estimatedMinutesWatched"]})
    except Exception:
        pass  # dimensão não disponível para alguns canais

    traffic = []
    try:
        for r in _rows_to_dicts(q(start, end, ["views"], dimensions="insightTrafficSourceType", sort="-views")):
            src = r["insightTrafficSourceType"]
            traffic.append({"source": TRAFFIC_LABELS.get(src, src.replace("_", " ").title()), "views": r["views"]})
    except Exception:
        pass

    top_rows = _rows_to_dicts(q(start, end, ["views", "estimatedMinutesWatched", "averageViewDuration",
                                             "averageViewPercentage", "likes", "subscribersGained"],
                                dimensions="video", sort="-views", maxResults=15))
    # vídeos publicados pelo pipeline (para marcar e listar à parte)
    pipeline_jobs = {}
    for j in db.list_jobs(channel_id, limit=500):
        vid = ((j["data"].get("publish") or {}).get("video_id"))
        if vid:
            pipeline_jobs[vid] = j
    ids = list(dict.fromkeys([r["video"] for r in top_rows] + list(pipeline_jobs)))[:50]
    meta = {}
    if ids:
        for it in yt.videos().list(part="snippet,contentDetails,statistics", id=",".join(ids)).execute().get("items", []):
            meta[it["id"]] = {
                "title": it["snippet"]["title"], "published": it["snippet"]["publishedAt"],
                "thumbnail": (it["snippet"]["thumbnails"].get("medium") or it["snippet"]["thumbnails"].get("default") or {}).get("url"),
                "seconds": _iso_seconds(it["contentDetails"].get("duration")),
                "total_views": int(it["statistics"].get("viewCount", 0)),
                "total_likes": int(it["statistics"].get("likeCount", 0)),
                "total_comments": int(it["statistics"].get("commentCount", 0)),
            }
    top = []
    for r in top_rows:
        m = meta.get(r["video"], {})
        top.append({"id": r["video"], **m, "views": r["views"], "minutes": r["estimatedMinutesWatched"],
                    "avg_duration": r["averageViewDuration"], "avg_percent": r["averageViewPercentage"],
                    "likes": r["likes"], "subs": r["subscribersGained"],
                    "job_id": pipeline_jobs[r["video"]]["id"] if r["video"] in pipeline_jobs else None})
    published = []
    for vid, j in pipeline_jobs.items():
        m = meta.get(vid)
        if m:
            published.append({"id": vid, "job_id": j["id"], "kind": j.get("kind"), **m})
    published.sort(key=lambda x: x.get("published") or "", reverse=True)

    return {"channel": channel, "range": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
            "totals": totals, "previous": prev, "daily": daily, "content": content, "traffic": traffic,
            "top": top, "pipeline": published, "fetched_at": time.time()}


async def report(channel_id: str, days: int = 28, refresh: bool = False) -> dict:
    key = (channel_id, days)
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
        return hit[1]
    data = await asyncio.to_thread(_report_sync, channel_id, days)
    _cache[key] = (time.time(), data)
    return data
