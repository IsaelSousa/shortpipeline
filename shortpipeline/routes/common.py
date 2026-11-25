"""Utilidades compartilhadas pelas rotas."""

from __future__ import annotations


import os

from fastapi import HTTPException

from .. import db
from ..worker import worker

PORT = int(os.environ.get("SHORTPIPELINE_PORT", "8765"))


# ------------------------------------------------------------------ jobs
def _public(job: dict) -> dict:
    job = dict(job)
    job["running_now"] = job["id"] in worker.running
    return job


def _job_or_404(job_id: str) -> dict:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return job
