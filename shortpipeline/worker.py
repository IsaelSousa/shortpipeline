"""Executor da fila e agendador (cria jobs nos horários configurados por canal)."""

from __future__ import annotations

import asyncio
import time
import traceback

from . import config, db, learn, pipeline


class Worker:
    def __init__(self):
        self.running: dict[str, asyncio.Task] = {}
        self.paused = False
        self._wake = asyncio.Event()
        self._last_schedule: dict[str, str] = {}  # canal|HH:MM -> data em que já rodou
        self._last_learn_check = 0.0

    def wake(self) -> None:
        """Pode ser chamado de qualquer thread (as rotas síncronas do FastAPI rodam num pool)."""
        loop = getattr(self, "_loop", None)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._wake.set)

    def cancel(self, job_id: str) -> bool:
        task = self.running.get(job_id)
        if task:
            task.cancel()
            return True
        return False

    async def stop(self, job_id: str) -> None:
        """Cancela o job (se estiver rodando) e espera ele parar de fato."""
        task = self.running.get(job_id)
        if task:
            task.cancel()
            await asyncio.wait([task], timeout=15)

    async def loop(self) -> None:
        self._loop = asyncio.get_running_loop()
        n = db.recover_interrupted()
        if n:
            print(f"[worker] {n} job(s) interrompido(s) voltaram para a fila")
        while True:
            try:
                self._schedule_tick()
                self._dispatch()
            except Exception:
                traceback.print_exc()
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    def _dispatch(self) -> None:
        if self.paused:
            return
        limit = max(1, int(config.load()["general"].get("max_parallel_jobs") or 1))
        while len(self.running) < limit:
            job = db.next_queued()
            if not job:
                return
            db.update_job(job["id"], status="running")
            task = asyncio.create_task(self._run(job["id"]))
            self.running[job["id"]] = task

    async def _run(self, job_id: str) -> None:
        try:
            await pipeline.run_job(job_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            traceback.print_exc()
            db.update_job(job_id, status="failed", error=f"Erro interno: {e}")
        finally:
            self.running.pop(job_id, None)
            self.wake()

    def _learn_tick(self, cfg: dict) -> None:
        """De tempos em tempos, reanalisa o Analytics de cada canal (aprendizado automático)."""
        if time.time() - self._last_learn_check < 600:
            return
        self._last_learn_check = time.time()
        for cid, ch in cfg["channels"].items():
            if ch.get("enabled") and learn.due(cid, ch):
                asyncio.create_task(self._learn(cid))

    async def _learn(self, cid: str) -> None:
        try:
            res = await learn.run(cid)
            print(f"[learn] {cid}: {res.get('summary')}")
        except Exception as e:
            print(f"[learn] {cid}: {e}")

    def _schedule_tick(self) -> None:
        cfg = config.load()
        self._learn_tick(cfg)
        now = time.localtime()
        today, hhmm = time.strftime("%Y-%m-%d", now), time.strftime("%H:%M", now)
        for cid, ch in cfg["channels"].items():
            sched = ch.get("schedule") or {}
            if not ch.get("enabled") or not sched.get("enabled"):
                continue
            for t in sched.get("times") or []:
                key = f"{cid}|{t}"
                if t == hhmm and self._last_schedule.get(key) != today:
                    self._last_schedule[key] = today
                    job = db.create_job(cid)
                    db.log(job["id"], f"Criado pelo agendamento das {t}")


worker = Worker()
