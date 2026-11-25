"""Ordem das etapas e execução de um job."""

from __future__ import annotations


import asyncio
import time

from .. import config, db
from ..providers import ProviderError
from .core import Ctx, WaitingApproval
from .writing import stage_ideia, stage_roteiro
from .media import stage_capa, stage_imagens, stage_legendas, stage_narracao
from .assembly import stage_render, stage_revisao, stage_som, stage_upload
from .clips import stage_download, stage_recorte, stage_selecao, stage_transcricao

STAGE_FUNCS = {
    "ideia": stage_ideia,
    "roteiro": stage_roteiro,
    "narracao": stage_narracao,
    "imagens": stage_imagens,
    "capa": stage_capa,
    "legendas": stage_legendas,
    "render": stage_render,
    "revisao": stage_revisao,
    "upload": stage_upload,
    "som": stage_som,
    "download": stage_download,
    "transcricao": stage_transcricao,
    "selecao": stage_selecao,
    "recorte": stage_recorte,
}


async def run_job(job_id: str) -> None:
    cfg = config.load()
    job = db.get_job(job_id)
    c = Ctx(job, cfg)
    c.job = db.update_job(job_id, status="running", error=None)
    review_after = (c.ch.get("review") or {}).get("after") or {}
    for stage in config.stages_for(c.kind):
        state = c.job["stages"][stage].get("status")
        if state == "done":
            continue
        if state == "review_pending":
            db.update_job(job_id, stage=stage, status="waiting_approval")
            return
        c.stage = stage
        c.job = db.update_job(job_id, stage=stage,
                              stages={stage: {"status": "running", "started": time.time(), "error": None,
                                              "detail": None}})
        try:
            await STAGE_FUNCS[stage](c)
        except WaitingApproval:
            db.update_job(job_id, status="waiting_approval", stages={stage: {"status": "waiting"}})
            c.log("Aguardando sua aprovação no painel")
            return
        except asyncio.CancelledError:
            db.update_job(job_id, status="canceled", stages={stage: {"status": "canceled", "ended": time.time()}})
            c.log("Cancelado", "warn")
            raise
        except Exception as e:
            msg = f"{type(e).__name__}: {e}" if not isinstance(e, ProviderError) else str(e)
            db.update_job(job_id, status="failed", error=msg,
                          stages={stage: {"status": "failed", "ended": time.time(), "error": msg}})
            c.log(msg, "error")
            from .. import notify
            try:
                await notify.notify_event(c.cfg, "error", db.get_job(job_id), {"error": msg})
            except Exception as ne:
                c.log(f"Aviso de falha não enviado: {ne}", "warn")
            return
        if stage in config.REVIEW_AFTER_STAGES and review_after.get(stage):
            db.update_job(job_id, status="waiting_approval",
                          stages={stage: {"status": "review_pending", "ended": time.time()}})
            c.log(f"{config.STAGE_LABELS[stage]} concluído. Aguardando revisão antes de continuar.")
            return
        c.job = db.update_job(job_id, stages={stage: {"status": "done", "ended": time.time()}})
    db.update_job(job_id, status="done", stage=None)
    c.log("Pipeline concluído")
