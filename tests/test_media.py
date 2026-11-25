"""Montagem de som, legendas e capa com o ffmpeg de verdade (arquivos pequenos)."""

import asyncio
import json
import subprocess

from conftest import needs_ffmpeg

from shortpipeline import render, sound


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def words(text, step=0.4):
    return [{"text": w, "start": i * step, "end": i * step + step * 0.9} for i, w in enumerate(text.split())]


@needs_ffmpeg
def test_build_mix_has_exact_length_and_finishes(tmp_path):
    """Regressão: a mixagem com ambiente em loop travava o ffmpeg para sempre."""
    async def go():
        whoosh = await sound.library_sound("whoosh", "neutro", {})
        bed = await sound.fallback_ambience("neutro", "room tone")
        dest = tmp_path / "sfx.wav"
        await asyncio.wait_for(sound.build_mix(
            [{"file": whoosh, "at": 0.5, "volume": 0.6}, {"file": whoosh, "at": 3.2, "volume": 0.4}],
            [{"file": bed, "start": 0.0, "dur": 4.0, "volume": 0.15}],
            4.0, dest), timeout=60)
        return dest

    dest = asyncio.run(go())
    assert abs(float(probe(dest)["format"]["duration"]) - 4.0) < 0.1


def test_unknown_sound_style_falls_back_to_neutral():
    assert sound.LIBRARY.get("culinaria", sound.LIBRARY["neutro"]) is sound.LIBRARY["neutro"]
    for style in sound.LIBRARY.values():
        assert {"whoosh", "impact", "riser", "blip"} <= set(style)


def test_build_ass_highlights_each_word(tmp_path):
    dest = tmp_path / "subs.ass"
    render.build_ass(words("uma casa no fim da rua"), {"words_per_caption": 3, "highlight_color": "#FF0000"}, dest)
    text = dest.read_text()
    dialogues = [ln for ln in text.splitlines() if ln.startswith("Dialogue:")]
    assert len(dialogues) == 6  # uma linha por palavra falada
    assert all("\\c&H" in d for d in dialogues)
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text


def test_wrap_cover_text_marks_highlight():
    lines = render.wrap_cover_text("o elevador [parou] no 13")
    assert any(h for _, h in lines)
    assert all("[" not in t for t, _ in lines)
    assert all(len(t) <= 12 or " " not in t for t, _ in lines)


@needs_ffmpeg
def test_build_cover_outputs_frame_sized_images(tmp_path):
    bg = tmp_path / "bg.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x334455:s=800x600", "-frames:v", "1",
                    str(bg)], check=True)
    png, jpg = tmp_path / "cover.png", tmp_path / "cover.jpg"
    asyncio.run(render.build_cover(bg, "teste de [capa]", {}, png, jpg))
    v = next(s for s in probe(png)["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (render.W, render.H)
    assert jpg.stat().st_size > 0


def test_special_music_only_when_the_script_asks(tmp_path, monkeypatch):
    from shortpipeline import config

    folder = tmp_path / "music" / "canal"
    folder.mkdir(parents=True)
    for name in ("normal.mp3", "natal.mp3"):
        (folder / name).write_bytes(b"x")
    (folder / "music.json").write_text(json.dumps({"natal.mp3": "histórias de Natal", "sumiu.mp3": "não existe"}))
    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "music")

    common, special = render.music_tracks("canal")
    assert [p.name for p in common] == ["normal.mp3"]
    assert special == {"natal.mp3": "histórias de Natal"}
    assert render.pick_music("canal", "natal.mp3").name == "natal.mp3"
    assert {render.pick_music("canal").name for _ in range(20)} == {"normal.mp3"}
    assert render.pick_music("canal", "outra.mp3").name == "normal.mp3"

    (folder / "normal.mp3").unlink()
    assert render.pick_music("canal") is None  # só a especial: sem música quando o roteiro não pede
