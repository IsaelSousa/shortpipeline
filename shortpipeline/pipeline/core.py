"""Contexto do job e tipos compartilhados pelas etapas."""

from __future__ import annotations


import math
import time
from pathlib import Path

from .. import config, db, learn
from ..providers import ProviderError, llm

SHORT_FRAME = (1080, 1920)
LONG_FRAME = (1920, 1080)
THUMB_FRAME = (1280, 720)


class WaitingApproval(Exception):
    """A etapa de revisão para o job até alguém aprovar no painel."""


class Ctx:
    def __init__(self, job: dict, cfg: dict):
        self.job = job
        self.cfg = cfg
        self.channel_id = job["channel"]
        self.ch = config.channel(cfg, self.channel_id)
        self.dir = config.JOBS_DIR / job["id"]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.stage = None
        self.kind = job.get("kind") or "short"

    @property
    def is_long(self) -> bool:
        return self.kind == "long"

    @property
    def frame(self) -> tuple[int, int]:
        return LONG_FRAME if self.is_long else SHORT_FRAME

    @property
    def aspect(self) -> str:
        return "16:9" if self.is_long else "9:16"

    def creative(self) -> dict:
        return self.ch.get("creative") or {}

    def insights(self) -> str:
        """Aprendizados escritos à mão + os aprendidos do Analytics."""
        parts = [(self.creative().get("insights") or "").strip()]
        if self.creative().get("auto_learn", True):
            parts.append((learn.load(self.channel_id).get("insights") or "").strip())
        return "\n".join(p for p in parts if p)

    def long_opts(self) -> dict:
        lo = dict(self.ch.get("long") or {})
        if self.data.get("long_minutes"):
            lo["target_minutes"] = self.data["long_minutes"]
        return lo

    @property
    def data(self) -> dict:
        return self.job["data"]

    def save(self, **data) -> None:
        self.job = db.update_job(self.job["id"], data=data)

    def log(self, msg: str, level: str = "info") -> None:
        db.log(self.job["id"], msg, level, self.stage)

    def detail(self, text: str) -> None:
        self.job = db.set_stage(self.job["id"], self.stage, detail=text)

    def fmt(self, template: str, **extra) -> str:
        v = self.ch["video"]
        if self.is_long:
            lo = self.long_opts()
            minutes = float(lo.get("target_minutes") or 8)
            seconds = int(minutes * 60)
            scenes = max(6, math.ceil(seconds / float(lo.get("seconds_per_image") or 15)))
        else:
            minutes = round((v.get("target_seconds") or 45) / 60, 1)
            seconds = int(v.get("target_seconds") or 45)
            scenes = v.get("scenes") or 6
        values = {"channel": self.ch["name"], "niche": self.ch.get("niche", ""), "language": self.ch.get("language"),
                  "scenes": scenes, "seconds": seconds, "minutes": f"{minutes:g}", "words": int(seconds * 2.5),
                  "topic": self.job.get("topic") or ""}
        values.update(extra)
        return template.format(**values)

    async def text(self, stage_key: str, prompt: str, *, image: Path | None = None) -> str:
        """Chama o modelo da etapa; se falhar, tenta o fallback configurado."""
        m = self.ch["models"][stage_key]
        attempts = [(m["provider"], m.get("model") or "")]
        if m.get("fallback_provider"):
            attempts.append((m["fallback_provider"], m.get("fallback_model") or ""))
        timeout = int(self.cfg["general"].get("llm_timeout") or 300)
        last: Exception | None = None
        for prov, model in attempts:
            self.log(f"Chamando {prov}{' / ' + model if model else ''}")
            try:
                t0 = time.time()
                options = {"image": image} if image is not None and prov == "codex" else {}
                out = await llm.generate(prov, model, prompt, timeout=timeout, providers_cfg=self.cfg["providers"],
                                         **options)
                self.log(f"{prov} respondeu em {time.time() - t0:.0f}s")
                return out
            except ProviderError as e:
                last = e
                self.log(f"{prov} falhou: {e}", "warn")
        raise ProviderError(str(last))
