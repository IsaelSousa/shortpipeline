"""Biblioteca de sons do usuário (data/sound-packs): estilos, variações e busca por palavra-chave."""

import asyncio
import json

import pytest

from shortpipeline import sound


@pytest.fixture
def packs(tmp_path, monkeypatch):
    root = tmp_path / "sound-packs"
    show = root / "programa"
    show.mkdir(parents=True)
    for name in ("impact.mp3", "applause-1.mp3", "applause-2.mp3", "ambience-1.mp3", "ambience-rain.mp3"):
        (show / name).write_bytes(b"x")
    (show / "pack.json").write_text(json.dumps({"styles": ["neutro"], "tags": {"ambience": ["cafe"]}}))
    common = root / "comum"
    common.mkdir()
    (common / "blip.ogg").write_bytes(b"x")
    monkeypatch.setattr(sound, "USER_PACKS", root)
    return root


def test_styles_limit_packs(packs):
    assert [x["name"] for x in sound.library("neutro")] == ["applause", "blip", "impact"]
    assert [x["name"] for x in sound.library("tech")] == ["blip"]
    assert next(x for x in sound.library("neutro") if x["name"] == "applause")["variants"] == 2


def test_variants_are_drawn(packs):
    picks = {sound.packed_sound("applause", "neutro").name for _ in range(40)}
    assert picks == {"applause-1.mp3", "applause-2.mp3"}
    assert sound.packed_sound("applause", "tech") is None


def test_match_by_keyword_in_english_or_portuguese(packs):
    assert sound.match_sound("a crowd clapping", "neutro").stem.startswith("applause")
    assert sound.match_sound("palmas da plateia", "neutro").stem.startswith("applause")
    assert sound.match_sound("door creaking", "neutro") is None
    assert sound.match_sound("people clapping", "tech") is None
    # ambientes só aparecem quando pedidos
    assert sound.match_sound("busy cafe", "neutro") is None
    assert sound.match_sound("busy cafe", "neutro", prefix="ambience").name == "ambience-1.mp3"
    assert sound.match_sound("rain on the roof", "neutro", prefix="ambience").name == "ambience-rain.mp3"


def test_user_sounds_come_before_elevenlabs(packs, monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError("não devia chamar o ElevenLabs")

    monkeypatch.setattr(sound, "generate", never)
    assert asyncio.run(sound.library_sound("impact", "neutro", {})).name == "impact.mp3"
    assert asyncio.run(sound.fallback_ambience("neutro", "quiet office")).name == "ambience-1.mp3"


def test_library_files_are_playable_in_the_timeline(packs):
    assert sound.in_library(packs / "programa" / "impact.mp3")
    assert not sound.in_library(packs.parent / "outro.mp3")
