"""Configuração geral e canais."""

from __future__ import annotations


import re

from fastapi import APIRouter, Body, HTTPException

from .. import config
from ..worker import worker

router = APIRouter()

# ------------------------------------------------------------------ config
@router.get("/api/config")
def get_config():
    return config.load()


@router.put("/api/config")
def put_config(cfg: dict = Body(...)):
    if "channels" not in cfg or "general" not in cfg:
        raise HTTPException(400, "Config inválida")
    config.save(cfg)
    worker.wake()
    return config.load()


@router.post("/api/channels")
def add_channel(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    cid = re.sub(r"[^a-z0-9]+", "", name.lower())
    if not cid:
        raise HTTPException(400, "Nome inválido")
    cfg = config.load()
    if cid in cfg["channels"]:
        raise HTTPException(409, "Canal já existe")
    cfg["channels"][cid] = config.new_channel_config(name)
    config.save(cfg)
    (config.MUSIC_DIR / cid).mkdir(parents=True, exist_ok=True)
    return {"id": cid}


@router.delete("/api/channels/{cid}")
def delete_channel(cid: str):
    cfg = config.load()
    cfg["channels"].pop(cid, None)
    config.save(cfg)
    return {"ok": True}


@router.post("/api/config/reset-prompt/{cid}/{key}")
def reset_prompt(cid: str, key: str):
    defaults = config.channel_defaults(cid, config.load()["channels"].get(cid))
    return {"value": defaults["prompts"].get(key, "")}
