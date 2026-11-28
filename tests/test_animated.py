"""Short animado: schema, catálogo, física, sincronia com a narração e um vídeo inteiro com a engine de verdade."""

import asyncio
import json
import re
import shutil
import subprocess

import cv2
import pytest
from conftest import needs_ffmpeg

from shortpipeline import config, db
from shortpipeline.motion import catalog, physics, schema
from shortpipeline.motion import render as motion
from shortpipeline.pipeline import animated, core, run_job
from shortpipeline.providers import tts

EXAMPLE = config.ROOT / "docs" / "motion" / "examples"
needs_engine = pytest.mark.skipif(not (motion.available() and shutil.which("node")),
                                  reason="engine de animação não construída (npm ci && npm run build em motion-canvas)")


def test_examples_follow_the_schema():
    for path in EXAMPLE.glob("*.json"):
        video = schema.validate(json.loads(path.read_text()))
        assert video.scenes, path.name


def test_catalog_schema_and_engine_agree_on_assets():
    engine = (config.ROOT / "motion-canvas" / "engine" / "objects.js").read_text()
    drawn = set(re.findall(r"^  (\w+): \{\n    size:", engine, re.M))
    assert set(catalog.asset_ids()) == set(schema.ASSETS) == drawn
    assert "air_conditioner" in catalog.prompt_catalog()


def test_schema_rejects_unknown_targets_and_assets():
    data = json.loads((EXAMPLE / "ar-condicionado.json").read_text())
    data["scenes"][2]["overlays"][0]["target"] = "nao_existe"
    data["scenes"][0]["objects"][0]["asset"] = "piano"
    with pytest.raises(schema.ValidationError) as exc:
        schema.validate(data)
    text = schema.errors_text(exc.value)
    assert "nao_existe" in text and "asset" in text


def test_free_fall_numbers():
    f = physics.free_fall(28.8)
    assert abs(f["seconds"] - 2.42) < 0.01 and abs(f["kmh"] - 85.6) < 0.2
    video = schema.validate(json.loads((EXAMPLE / "ar-condicionado.json").read_text()))
    facts = physics.fall_facts(video)
    assert any("28.8 m" in f["claim"] and f["kind"] == "calculation" for f in facts)


def test_prepare_syncs_scenes_and_words_with_narration():
    data = {"schema_version": 1, "characters": [], "scenes": [
        {"id": "a", "start": 0, "end": 9, "objects": [{"id": "box", "asset": "crate",
                                                      "actions": [{"type": "fall", "at_word": "caiu"}]}]},
        {"id": "b", "start": 9, "end": 20, "overlays": [{"type": "title", "text": "x", "at_word": "nada"}]},
    ]}
    words = [[{"text": "A", "start": 0.0, "end": 0.2}, {"text": "caixa", "start": 0.25, "end": 0.6},
              {"text": "caiu!", "start": 0.7, "end": 1.0}], [{"text": "Fim.", "start": 0.1, "end": 0.4}]]
    spec, warnings = motion.prepare(data, words, [1.5, 1.0])
    assert [(s["start"], s["end"]) for s in spec["scenes"]] == [(0.0, 1.5), (1.5, 2.5)]
    assert spec["scenes"][0]["objects"][0]["actions"][0]["start"] == 0.7
    assert spec["captions"]["words"][-1] == {"text": "Fim.", "start": 1.6, "end": 1.9}
    assert warnings and "nada" in warnings[0]


@needs_ffmpeg
@needs_engine
def test_three_layer_reveals_an_animated_shape_at_the_spoken_word(tmp_path):
    video = schema.validate({"captions": {"enabled": False}, "scenes": [{
        "id": "three", "start": 0, "end": 2, "environment": {"type": "studio", "color": "#253347"},
        "layer_3d": {"objects": [{
            "shape": "box", "color": "#E57631", "spin": [0, 90, 0],
            "reveal": {"at_word": "caixa", "dur": 0.2},
        }]},
    }]})
    assert not animated.auto_checks(video, [])
    spec, warnings = motion.prepare(video.model_dump(exclude_none=True),
                                    [[{"text": "Caixa!", "start": 0.5, "end": 0.7}]], [2])
    assert not warnings
    reveal = spec["scenes"][0]["layer_3d"]["objects"][0]["reveal"]
    assert reveal["start"] == 0.5
    clips = asyncio.run(motion.render_scenes(spec, tmp_path, width=180, height=320, fps=12))
    capture = cv2.VideoCapture(str(clips[0]))

    def orange_pixels(index):
        capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, image = capture.read()
        assert ok
        blue, green, red = (channel.astype(int) for channel in cv2.split(image))
        return ((red > green + 25) & (green > blue + 15)).sum()

    try:
        assert orange_pixels(4) == 0
        first_view, second_view = orange_pixels(10), orange_pixels(15)
        assert min(first_view, second_view) > 500
        assert abs(first_view - second_view) > 100
    finally:
        capture.release()


def test_auto_checks_flag_static_scenes_and_unshown_numbers():
    video = schema.validate({"schema_version": 1, "scenes": [
        {"id": "parada", "start": 0, "end": 3, "narration": "São 86 km/h."},
        {"id": "viva", "start": 3, "end": 5, "camera": {"moves": [{"type": "zoom", "start": 0, "zoom": 1.3}]}},
    ]})
    issues = animated.auto_checks(video, [(3.2, 1.8)])
    problems = {(i["scene"], i["problem"].split(" ")[0]) for i in issues}
    assert ("parada", "cena") in problems and ("parada", "a") in problems and ("viva", "1.8") in problems


SCRIPT = {
    "title": "E se uma caixa caísse da prateleira? #shorts",
    "description": "Teste.", "tags": ["teste"], "cover_text": "a [queda]",
    "scenes": [
        {"narration": "Uma caixa está na beira da prateleira.", "visual": "caixa balança"},
        {"narration": "Ela cai três metros em menos de um segundo.", "visual": "caixa cai com velocímetro"},
        {"narration": "E chega ao chão a vinte e oito quilômetros por hora.", "visual": "impacto e número"},
    ],
}


def _storyboard(n):
    scenes = [
        {"id": "s1", "start": 0, "end": 1, "environment": {"type": "room"},
         "characters": [{"ref": "ana", "x": -1.2, "actions": [{"type": "look_up", "start": 0.1}]}],
         "objects": [{"id": "box", "asset": "crate", "x": 0.6, "height": 3,
                      "actions": [{"type": "wobble", "start": 0, "end": 1}]}],
         "overlays": [{"type": "title", "text": "E se a [caixa] caísse?", "start": 0}]},
        {"id": "s2", "start": 1, "end": 2, "environment": {"type": "room"},
         "objects": [{"id": "box", "asset": "crate", "x": 0.6, "height": 3,
                      "actions": [{"type": "fall", "at_word": "cai"}]}],
         "camera": {"moves": [{"type": "cut", "target": "box", "start": 0, "zoom": 2},
                              {"type": "follow", "target": "box", "start": 0}]},
         "overlays": [{"type": "speed", "target": "box", "start": 0}, {"type": "distance", "target": "box", "start": 0}]},
        {"id": "s3", "start": 2, "end": 3, "environment": {"type": "studio"},
         "overlays": [{"type": "counter", "from": 0, "to": 28, "suffix": " km/h", "start": 0}],
         "camera": {"moves": [{"type": "zoom", "start": 0, "zoom": 1.2}]}},
    ]
    return {"schema_version": 1, "characters": [{"id": "ana", "look": {"hair_style": "bun"}}],
            "captions": {"emphasis": ["metros"], "fixed_position": True}, "cover_time": 0.5, "scenes": scenes[:n]}


@needs_ffmpeg
@needs_engine
def test_animated_short_end_to_end(channel, monkeypatch):
    calls = []

    async def text(self, stage_key, prompt, *, image=None):
        calls.append(stage_key)
        if "pesquisador" in prompt:
            return json.dumps({"question": "Quão rápido cai?", "facts": [
                {"claim": "3 m de queda levam 0,78 s", "kind": "calculation", "value": 0.78}], "safety": "", "avoid": []})
        if "diretor visual" in prompt:
            assert "Palavras:" in prompt and "crate" in prompt  # tempos da fala e catálogo chegam ao storyboard
            return json.dumps(_storyboard(3))
        if "editor de qualidade" in prompt:
            assert image is not None and image.is_file()
            assert "s1 (" in prompt and "s3 (" in prompt
            return json.dumps({"score": 9, "issues": []})
        if "editor-chefe" in prompt:
            return json.dumps({"score": 9, "scores": {}, "issues": []})
        assert "FATOS DA PESQUISA" in prompt  # o roteiro recebe a pesquisa
        return json.dumps(SCRIPT, ensure_ascii=False)

    async def synthesize(text_, dest, opts, providers_cfg):
        plain = tts.strip_tags(text_)
        seconds = max(1.0, len(plain.split()) * 0.12)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=220:d={seconds}", "-ac", "1",
                        str(dest)], check=True)
        return tts.even_words(plain, seconds)

    monkeypatch.setattr(core.Ctx, "text", text)
    monkeypatch.setattr(tts, "synthesize", synthesize)
    cfg = config.load()
    ch = cfg["channels"][channel]
    ch["review"].update(require_approval=False, approve_before_render=False)
    ch["creative"].update(sound=False, review_script=True)
    ch["models"]["critica"]["provider"] = "codex"
    config.save(cfg)

    job = db.create_job(channel, topic="uma caixa caindo da prateleira", kind="animado")
    asyncio.run(asyncio.wait_for(run_job(job["id"]), timeout=900))
    job = db.get_job(job["id"])
    errors = [e["message"] for e in db.get_logs(job["id"]) if e["level"] == "error"]
    assert job["status"] == "done", (job.get("error"), errors)
    assert [s for s in config.stages_for("animado") if job["stages"][s]["status"] != "done"] == []
    assert "roteiro" in calls and calls.count("critica") >= 2  # revisor do roteiro e de qualidade

    d = job["data"]
    jdir = config.JOBS_DIR / job["id"]
    assert d["research"]["facts"] and d["qa"]["score"] == 9 and d["assets"]["catalog"] == {"crate": 2}
    board = json.loads((jdir / "storyboard.json").read_text())
    assert any(f["kind"] == "calculation" and "3.0 m" in f["claim"] for f in board["facts"])
    final = jdir / "final.mp4"
    info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                      str(final)], capture_output=True, text=True, check=True).stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (video["width"], video["height"]) == (1080, 1920)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert abs(float(info["format"]["duration"]) - sum(d["durations"])) < 0.2
    assert (jdir / "preview.mp4").is_file() and (jdir / "cover" / "cover.jpg").is_file()

    # mudar uma cena re-renderiza só ela; as outras vêm do cache
    parts = sorted((jdir / "motion" / "final").glob("*.mp4"))
    board["scenes"][2]["environment"]["color"] = "#334155"
    (jdir / "storyboard.json").write_text(json.dumps(board))
    c = core.Ctx(job, config.load())
    asyncio.run(animated.render_final(c, lambda m: None))
    after = sorted((jdir / "motion" / "final").glob("*.mp4"))
    assert len(set(parts) & set(after)) == 2 and len(after) == 3


def test_published_json_schema_is_current():
    """docs/motion/schema.v1.json é gerado do código; se o schema mudar, regenere o arquivo."""
    published = json.loads((config.ROOT / "docs" / "motion" / "schema.v1.json").read_text())
    assert published == schema.json_schema()


def test_clean_drops_ai_noise_before_validation():
    """A IA costuma escrever 0 ou null em campos opcionais; isso não deve derrubar o storyboard."""
    scene = {"id": "a", "start": 0, "end": 2, "enter": {"type": "cut", "dur": 0},
             "time_warp": [{"start": 0, "end": 1, "rate": 0}], "camera": {"moves": [
                 {"type": "zoom", "start": 0.5, "end": 0.2, "zoom": 1.2, "dur": 0, "target": None}]}}
    video = schema.validate({"schema_version": 1, "scenes": [scene]})
    sc = video.scenes[0]
    assert sc.enter.dur == 0.35 and sc.time_warp == [] and sc.camera.moves[0].end is None
