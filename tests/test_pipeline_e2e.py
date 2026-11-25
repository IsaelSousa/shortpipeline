"""Um short inteiro, do roteiro ao final.mp4, com IA e voz falsas e o ffmpeg de verdade."""

import asyncio
import json
import subprocess

import pytest
from conftest import needs_ffmpeg

from shortpipeline import config, db
from shortpipeline.pipeline import core, run_job
from shortpipeline.providers import tts

SCRIPT = {
    "title": "A casa do fim da rua #shorts",
    "description": "Uma história curta de teste.",
    "tags": ["teste"],
    "scenes": [
        {"narration": "Toda noite a luz da casa do fim da rua acendia sozinha.", "image_prompt": "old house at night"},
        {"narration": "Um dia eu fui até lá e a porta estava aberta.", "image_prompt": "open door, dark hallway"},
        {"narration": "Lá dentro, alguém tinha escrito o meu nome na parede.", "image_prompt": "name written on wall"},
    ],
}
CRITIC = {"score": 9, "scores": {"hook": 9, "entrega": 9, "ritmo": 8, "final": 9, "titulo": 9}, "issues": []}


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []

    async def text(self, stage_key, prompt):
        calls.append(stage_key)
        return json.dumps({"roteiro": SCRIPT, "critica": CRITIC}[stage_key], ensure_ascii=False)

    async def synthesize(text_, dest, opts, providers_cfg):
        plain = tts.strip_tags(text_)
        seconds = max(1.0, len(plain.split()) * 0.3)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}",
                        "-ac", "1", str(dest)], check=True)
        return tts.even_words(plain, seconds)

    monkeypatch.setattr(core.Ctx, "text", text)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    return calls


@needs_ffmpeg
def test_short_end_to_end(fresh_config, fake_ai):
    cfg = config.load()
    ch = cfg["channels"]["terror"]
    ch["models"]["imagens"] = {"provider": "placeholder", "model": "", "fallback_provider": "", "fallback_model": ""}
    ch["review"].update(require_approval=False, approve_before_render=False)
    ch["video"].update(scenes=3, target_seconds=10)
    ch["creative"]["review_script"] = True
    config.save(cfg)

    job = db.create_job("terror", topic="uma casa abandonada que acende a luz sozinha")
    asyncio.run(asyncio.wait_for(run_job(job["id"]), timeout=600))

    job = db.get_job(job["id"])
    errors = [entry["message"] for entry in db.get_logs(job["id"]) if entry["level"] == "error"]
    assert job["status"] == "done", (job.get("error"), errors)
    assert fake_ai == ["roteiro", "critica"]
    assert job["data"]["critique"]["final"] == 9

    final = config.JOBS_DIR / job["id"] / "final.mp4"
    assert final.is_file()
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                      str(final)], capture_output=True, text=True, check=True).stdout)
    kinds = {s["codec_type"] for s in info["streams"]}
    assert kinds == {"video", "audio"}
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    narration = sum(job["data"]["durations"])
    assert abs(float(info["format"]["duration"]) - narration) < 1.5

    # a timeline do job pronto tem uma faixa de cenas com todas as cenas
    from fastapi.testclient import TestClient

    from shortpipeline.server import app

    tl = TestClient(app).get(f"/api/jobs/{job['id']}/timeline").json()
    assert abs(tl["total_duration"] - narration) < 1.5
    assert len(tl["scenes"]) == len(SCRIPT["scenes"])


def test_failed_stage_marks_job_and_notifies(fresh_config, monkeypatch):
    from shortpipeline import notify
    from shortpipeline.providers import ProviderError

    async def broken(self, stage_key, prompt):
        raise ProviderError("cota esgotada")

    sent = []

    async def fake_notify(cfg, event, job, extra=None):
        sent.append((event, job["id"], (extra or {}).get("error")))

    monkeypatch.setattr(core.Ctx, "text", broken)
    monkeypatch.setattr(notify, "notify_event", fake_notify)
    job = db.create_job("terror", topic="vai falhar")
    asyncio.run(run_job(job["id"]))

    job = db.get_job(job["id"])
    assert job["status"] == "failed"
    assert job["stages"]["roteiro"]["status"] == "failed"
    assert "cota esgotada" in job["error"]
    assert sent == [("error", job["id"], job["error"])]


def test_script_can_pick_special_music(fresh_config, monkeypatch, tmp_path):
    from shortpipeline.pipeline import writing

    folder = tmp_path / "music" / "terror"
    folder.mkdir(parents=True)
    (folder / "natal.mp3").write_bytes(b"x")
    (folder / "music.json").write_text(json.dumps({"natal.mp3": "histórias de Natal"}))
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "music")
    prompts = []

    async def text(self, stage_key, prompt):
        prompts.append(prompt)
        return json.dumps({**SCRIPT, "music": "natal.mp3"} if stage_key == "roteiro" else CRITIC)

    monkeypatch.setattr(core.Ctx, "text", text)
    job = db.create_job("terror", topic="o Papai Noel que não ia embora")
    c = core.Ctx(job, config.load())
    asyncio.run(writing.stage_roteiro(c))
    assert '"natal.mp3": histórias de Natal' in prompts[0]
    assert c.data["script"]["music"] == "natal.mp3"
