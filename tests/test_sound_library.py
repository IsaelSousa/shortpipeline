"""Biblioteca de sons do usuário (data/sound-packs): estilos, variações e busca por palavra-chave."""

import asyncio
import json

import pytest

from shortpipeline import sound


@pytest.fixture
def packs(tmp_path, monkeypatch):
    root = tmp_path / "sound-packs"
    horror = root / "horror"
    horror.mkdir(parents=True)
    for name in ("impact.mp3", "scream-1.mp3", "scream-2.mp3", "ambience-1.mp3", "ambience-rain.mp3"):
        (horror / name).write_bytes(b"x")
    (horror / "pack.json").write_text(json.dumps({"styles": ["terror"], "tags": {"ambience": ["paranormal"]}}))
    common = root / "comum"
    common.mkdir()
    (common / "blip.ogg").write_bytes(b"x")
    monkeypatch.setattr(sound, "USER_PACKS", root)
    return root


def test_styles_limit_packs(packs):
    assert [x["name"] for x in sound.library("terror")] == ["blip", "impact", "scream"]
    assert [x["name"] for x in sound.library("tech")] == ["blip"]
    assert next(x for x in sound.library("terror") if x["name"] == "scream")["variants"] == 2


def test_variants_are_drawn(packs):
    picks = {sound.packed_sound("scream", "terror").name for _ in range(40)}
    assert picks == {"scream-1.mp3", "scream-2.mp3"}
    assert sound.packed_sound("scream", "tech") is None


def test_match_by_keyword_in_english_or_portuguese(packs):
    assert sound.match_sound("a woman screaming far away", "terror").stem.startswith("scream")
    assert sound.match_sound("um grito no corredor", "terror").stem.startswith("scream")
    assert sound.match_sound("door creaking", "terror") is None
    assert sound.match_sound("woman screaming", "tech") is None
    # ambientes só aparecem quando pedidos
    assert sound.match_sound("paranormal hum", "terror") is None
    assert sound.match_sound("paranormal hum", "terror", prefix="ambience").name == "ambience-1.mp3"
    assert sound.match_sound("rain on the roof", "terror", prefix="ambience").name == "ambience-rain.mp3"


def test_user_sounds_come_before_elevenlabs(packs, monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError("não devia chamar o ElevenLabs")

    monkeypatch.setattr(sound, "generate", never)
    assert asyncio.run(sound.library_sound("impact", "terror", {})).name == "impact.mp3"
    assert asyncio.run(sound.fallback_ambience("terror", "wind outside")).name == "ambience-1.mp3"


def test_library_files_are_playable_in_the_timeline(packs):
    assert sound.in_library(packs / "horror" / "impact.mp3")
    assert not sound.in_library(packs.parent / "outro.mp3")
