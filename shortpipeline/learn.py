"""Aprendizado automático: lê o desempenho real dos vídeos no YouTube Analytics e transforma em
"o que repetir / o que evitar" (vai para os prompts de pauta, roteiro e revisor) e em notas por formato
(os formatos que rendem mais voltam mais vezes).

Fica em data/learn/<canal>.json, separado do config.json, para não brigar com o que você edita no painel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, timedelta

from . import config, db, upload
from .providers import ProviderError, llm

log = logging.getLogger(__name__)

LEARN_DIR = config.DATA_DIR / "learn"
POINTS = (0.1, 0.25, 0.5, 0.75, 0.95)
_running: set[str] = set()


def path(cid: str):
    return LEARN_DIR / f"{cid}.json"


def load(cid: str) -> dict:
    try:
        return json.loads(path(cid).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(cid: str, data: dict) -> None:
    LEARN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path(cid).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path(cid))


def running(cid: str) -> bool:
    return cid in _running


def due(cid: str, ch: dict) -> bool:
    cr = ch.get("creative") or {}
    if not cr.get("auto_learn", True) or cid in _running:
        return False
    from . import analytics
    if not analytics.has_scope(cid):
        return False
    last = load(cid)
    every = float(cr.get("learn_every_days") or 7) * 86400
    # depois de uma falha, espera 6h antes de tentar de novo
    ref = max(last.get("learned_at") or 0, (last.get("failed_at") or 0) - every + 6 * 3600)
    return time.time() - ref >= every


def _collect_sync(cid: str, days: int) -> list[dict]:
    from googleapiclient.discovery import build

    from .analytics import _iso_seconds, _rows_to_dicts

    creds = upload._credentials(cid)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)
    end = date.today()
    start = end - timedelta(days=days - 1)
    rows = _rows_to_dicts(ya.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        metrics="views,averageViewDuration,averageViewPercentage,likes,shares,subscribersGained",
        dimensions="video", sort="-views", maxResults=40).execute())
    if not rows:
        return []
    meta = {}
    for it in yt.videos().list(part="snippet,contentDetails", id=",".join(r["video"] for r in rows)).execute().get("items", []):
        meta[it["id"]] = {"title": it["snippet"]["title"], "published": it["snippet"]["publishedAt"][:10],
                          "seconds": _iso_seconds(it["contentDetails"].get("duration"))}
    jobs = {}
    for j in db.list_jobs(cid, limit=500):
        vid = (j["data"].get("publish") or {}).get("video_id")
        if vid:
            jobs[vid] = j
    out = []
    for i, r in enumerate(rows):
        m = meta.get(r["video"])
        if not m:
            continue
        v = {"titulo": m["title"], "publicado": m["published"], "duracao_s": m["seconds"], "views": r["views"],
             "pct_assistido": round(r["averageViewPercentage"], 1), "seg_assistidos": r["averageViewDuration"],
             "likes": r["likes"], "shares": r["shares"], "inscritos": r["subscribersGained"]}
        j = jobs.get(r["video"])
        if j:
            sc = (j["data"].get("script") or {}).get("scenes") or [{}]
            ed = j["data"].get("editorial_idea") or {}
            v["pauta"] = str(j.get("topic") or ed.get("topic") or "")[:300]
            if ed.get("family"):
                v["familia"] = ed["family"]
            v["formato"] = j["data"].get("format") or ""
            v["gancho"] = (sc[0].get("narration") or "")[:200]
            v["nota_revisor"] = (j["data"].get("critique") or {}).get("final")
        if i < 15:  # curva de retenção dos mais vistos (1 consulta por vídeo)
            try:
                curve = _rows_to_dicts(ya.reports().query(
                    ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
                    metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
                    filters=f"video=={r['video']}").execute())
                pts = {}
                for p in POINTS:
                    near = min(curve, key=lambda c: abs(c["elapsedVideoTimeRatio"] - p), default=None)
                    if near:
                        pts[f"{int(p * 100)}%"] = round(near["audienceWatchRatio"] * 100)
                if pts:
                    v["retencao"] = pts
            except Exception as exc:
                log.warning("Curva de retenção indisponível para %s: %s", r["video"], exc)
        out.append(v)
    return out


def _themes(raw) -> list[dict]:
    out = []
    for t in raw if isinstance(raw, list) else []:
        if not isinstance(t, dict) or not str(t.get("theme") or "").strip():
            continue
        try:
            score = max(0.0, min(1.0, float(t.get("score", 0.5))))
        except (TypeError, ValueError):
            score = 0.5
        out.append({"theme": str(t["theme"]).strip()[:160], "score": score,
                    "evidence": str(t.get("evidence") or "").strip()[:240]})
    return sorted(out, key=lambda t: -t["score"])[:8]


def _performance(videos: list[dict]) -> list[dict]:
    """Os números de cada vídeo, curtos, para a etapa de pauta comparar."""
    keep = ("titulo", "pauta", "familia", "views", "pct_assistido", "inscritos")
    return [{k: v[k] for k in keep if v.get(k) not in (None, "")} for v in videos[:40]]


def topic_brief(cid: str, ch: dict) -> str:
    """O que o Analytics diz sobre temas, para guiar a escolha da pauta. Vazio se desligado ou sem análise."""
    cr = ch.get("creative") or {}
    if not cr.get("auto_learn", True) or not cr.get("learn_topics", True):
        return ""
    data = load(cid)
    themes, perf = data.get("themes") or [], data.get("performance") or []
    if not themes and not perf:
        return ""
    lines = []
    if themes:
        lines.append("Temas pelo desempenho real (nota 0–1, do que mais rende para o que menos rende):")
        lines += [f"- {t['theme']} ({t['score']:.2f})" + (f": {t['evidence']}" if t.get("evidence") else "")
                  for t in themes]
    if perf:
        ranked = sorted(perf, key=lambda v: -(v.get("views") or 0))
        top, bottom = ranked[:8], ranked[8:][-5:]
        fmt = lambda v: (f"- {v.get('titulo')}" + (f" [{v['familia']}]" if v.get("familia") else "")
                         + f": {v.get('views', 0)} views, {v.get('pct_assistido', 0)}% assistido"
                         + (f", +{v['inscritos']} inscritos" if v.get("inscritos") else ""))
        lines.append("Vídeos que mais renderam:")
        lines += [fmt(v) for v in top]
        if bottom:
            lines.append("Vídeos que menos renderam:")
            lines += [fmt(v) for v in bottom]
    if data.get("next_topics"):
        lines.append("Pautas sugeridas pela análise (use, adapte ou combine, se ainda não foram feitas):")
        lines += [f"- {t}" for t in data["next_topics"]]
    return "\n".join(lines)


async def _ask(cfg: dict, ch: dict, prompt: str) -> str:
    m = ch["models"].get("critica") or ch["models"]["ideia"]
    attempts = [(m["provider"], m.get("model") or "")]
    if m.get("fallback_provider"):
        attempts.append((m["fallback_provider"], m.get("fallback_model") or ""))
    last = None
    for prov, model in attempts:
        try:
            return await llm.generate(prov, model, prompt, timeout=int(cfg["general"].get("llm_timeout") or 300),
                                      providers_cfg=cfg["providers"])
        except ProviderError as e:
            last = e
    raise ProviderError(str(last))


async def run(cid: str, days: int = 60) -> dict:
    """Coleta os números, pede a análise para a IA e salva. Devolve o resultado salvo."""
    if cid in _running:
        raise ProviderError("Já está analisando este canal")
    _running.add(cid)
    try:
        cfg = config.load()
        ch = config.channel(cfg, cid)
        prev = load(cid)
        try:
            videos = await asyncio.to_thread(_collect_sync, cid, days)
            if len([v for v in videos if v["views"] > 0]) < 3:
                raise ProviderError("Poucos vídeos com views ainda (precisa de pelo menos 3)")
            formats = [f for f in (ch.get("creative") or {}).get("formats") or [] if f.strip()]
            prompt = config.LEARN_PROMPT.format(
                channel=ch["name"], niche=ch.get("niche", ""), days=days,
                videos=json.dumps(videos, ensure_ascii=False, indent=1),
                formats=json.dumps(formats, ensure_ascii=False),
                rules=("Regra fixa do canal: os vídeos terminam em loop (a última frase emenda na primeira), sem pedir "
                       "like, inscrição, comentário ou compartilhamento. Não sugira o contrário."
                       if (ch.get("creative") or {}).get("loop_ending", True) else ""))
            out = llm.extract_json(await _ask(cfg, ch, prompt))
            insights = (out.get("insights") or "").strip()
            if not insights:
                raise ProviderError("A IA não devolveu aprendizados")
            scores = {}
            for f in formats:
                try:
                    scores[f] = max(0.0, min(1.0, float((out.get("format_scores") or {}).get(f, 0.5))))
                except (TypeError, ValueError):
                    scores[f] = 0.5
            data = {"insights": insights, "format_scores": scores, "summary": out.get("summary") or "",
                    "themes": _themes(out.get("themes")),
                    "next_topics": [str(t).strip()[:400] for t in out.get("next_topics") or [] if str(t).strip()][:8],
                    "performance": _performance(videos),
                    "learned_at": time.time(), "videos": len(videos), "days": days}
        except Exception as e:
            data = {**prev, "failed_at": time.time(), "error": str(e)[:300]}
            _save(cid, data)
            raise ProviderError(str(e)) from e
        _save(cid, data)
        return data
    finally:
        _running.discard(cid)
