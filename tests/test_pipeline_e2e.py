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
    "title": "Pão de frigideira em 10 minutos #shorts",
    "description": "Um roteiro curto de teste.",
    "tags": ["teste"],
    "scenes": [
        {"narration": "Você não precisa de forno para fazer pão em casa.", "image_prompt": "flatbread in a frying pan"},
        {"narration": "Misture farinha, iogurte e uma pitada de sal.", "image_prompt": "hands mixing dough in a bowl"},
        {"narration": "Dois minutos de cada lado e ele estufa sozinho.", "image_prompt": "flatbread puffing up in a pan"},
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
def test_short_end_to_end(channel, fake_ai):
    cfg = config.load()
    ch = cfg["channels"][channel]
    ch["models"]["imagens"] = {"provider": "placeholder", "model": "", "fallback_provider": "", "fallback_model": ""}
    ch["review"].update(require_approval=False, approve_before_render=False)
    ch["video"].update(scenes=3, target_seconds=10)
    ch["creative"]["review_script"] = True
    config.save(cfg)

    job = db.create_job(channel, topic="pão sem forno")
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

    client = TestClient(app)
    tl = client.get(f"/api/jobs/{job['id']}/timeline").json()
    assert abs(tl["total_duration"] - narration) < 1.5
    assert len(tl["scenes"]) == len(SCRIPT["scenes"])
    assert tl["status"]["is_rendered"] and not tl["status"]["needs_render"]

    # remover um som depois do render: o painel pede um novo render, e ele refaz o final.mp4
    events = job["data"]["sound"]["events"]
    assert events, "o teste precisa de pelo menos um efeito (whoosh entre cenas)"
    before = final.stat().st_mtime
    old_urls = [e["audio_url"] for e in tl["sound_events"]]
    assert all(old_urls) and len(old_urls) >= 2
    second = client.get(old_urls[1]).content
    res = client.post(f"/api/jobs/{job['id']}/delete-sfx", json={"index": 0})
    assert res.status_code == 200, res.text
    assert res.json()["timeline"]["status"]["needs_render"]
    # uma página aberta antes da remoção continua ouvindo o som certo, e o removido avisa que mudou
    assert client.get(old_urls[1]).content == second
    assert client.get(old_urls[0]).status_code == 410
    assert client.post(f"/api/jobs/{job['id']}/start-render").status_code == 200
    job = db.get_job(job["id"])
    assert job["status"] == "queued" and job["stages"]["render"]["status"] == "pending"
    assert job["stages"]["som"]["status"] == "done"  # a edição do som não é refeita do zero
    asyncio.run(asyncio.wait_for(run_job(job["id"]), timeout=600))
    job = db.get_job(job["id"])
    assert job["status"] == "done", job.get("error")
    assert len(job["data"]["sound"]["events"]) == len(events) - 1
    assert final.stat().st_mtime > before
    assert not client.get(f"/api/jobs/{job['id']}/timeline").json()["status"]["needs_render"]

    # um vídeo feito com a mixagem antiga (ambiente salvo a 0.01) é remixado ao abrir a timeline
    bed = config.JOBS_DIR / job["id"] / "bed.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=3:a=0.02", str(bed)], check=True)
    snd = {**job["data"]["sound"], "beds": [{"sound": "rain", "start": 0.0, "dur": 3.0, "volume": 0.01, "file": str(bed)}]}
    snd.pop("mix_version", None)
    db.update_job(job["id"], data={"sound": snd})
    assert client.get(f"/api/jobs/{job['id']}/timeline").json()["status"]["needs_render"]
    snd = db.get_job(job["id"])["data"]["sound"]
    from shortpipeline import sound
    assert snd["mix_version"] == sound.MIX_VERSION
    assert snd["beds"][0]["volume"] == config.load()["channels"][channel]["creative"]["ambience_volume"]


def test_failed_stage_marks_job_and_notifies(channel, monkeypatch):
    from shortpipeline import notify
    from shortpipeline.providers import ProviderError

    async def broken(self, stage_key, prompt):
        raise ProviderError("cota esgotada")

    sent = []

    async def fake_notify(cfg, event, job, extra=None):
        sent.append((event, job["id"], (extra or {}).get("error")))

    monkeypatch.setattr(core.Ctx, "text", broken)
    monkeypatch.setattr(notify, "notify_event", fake_notify)
    job = db.create_job(channel, topic="vai falhar")
    asyncio.run(run_job(job["id"]))

    job = db.get_job(job["id"])
    assert job["status"] == "failed"
    assert job["stages"]["roteiro"]["status"] == "failed"
    assert "cota esgotada" in job["error"]
    assert sent == [("error", job["id"], job["error"])]


def test_script_can_pick_special_music(channel, monkeypatch, tmp_path):
    from shortpipeline.pipeline import writing

    folder = tmp_path / "music" / channel
    folder.mkdir(parents=True)
    (folder / "festa.mp3").write_bytes(b"x")
    (folder / "music.json").write_text(json.dumps({"festa.mp3": "receitas de festa de aniversário"}))
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "music")
    prompts = []

    async def text(self, stage_key, prompt):
        prompts.append(prompt)
        return json.dumps({**SCRIPT, "music": "festa.mp3"} if stage_key == "roteiro" else CRITIC)

    monkeypatch.setattr(core.Ctx, "text", text)
    job = db.create_job(channel, topic="bolo de aniversário de caneca")
    c = core.Ctx(job, config.load())
    asyncio.run(writing.stage_roteiro(c))
    assert '"festa.mp3": receitas de festa de aniversário' in prompts[0]
    assert c.data["script"]["music"] == "festa.mp3"
