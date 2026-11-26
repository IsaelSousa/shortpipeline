"""Biblioteca CC0 (shortpipeline-sounds): nomes, pacotes e prioridade — sem rede."""

import json

import pytest

from shortpipeline import sound, sound_packs as sp


@pytest.mark.parametrize("source,name,expected", [
    ("kenney-impact-sounds", "impactPunch_heavy_003.ogg", "punch"),
    ("kenney-impact-sounds", "footstep_concrete_001.ogg", "footsteps"),
    ("kenney-rpg-audio", "doorClose_2.ogg", "door-close"),
    ("kenney-interface-sounds", "glass_004.ogg", "glass-tap"),
    ("kenney-sci-fi-sounds", "laserSmall_002.ogg", "laser"),
    ("kenney-music-jingles", "jingles_HIT07.ogg", "sting"),
    ("oga-75-cc0-breaking-falling-hit-sfx", "bfh1_glass_breaking_03.ogg", "glass-break"),
    ("oga-80-cc0-rpg-sfx", "item_coins_02.ogg", "item"),
    ("oga-30-cc0-sfx-loops", "loop_machine_04.ogg", "ambience-machine"),
    ("oga-30-cc0-sfx-loops", "saw_01.ogg", None),
    ("oga-100-cc0-sfx", "misc_07.ogg", None),
])
def test_original_names_map_to_library_categories(source, name, expected):
    assert sp.category(source, name) == expected


def test_every_category_has_a_pack_and_tags():
    cats = {c for rules in [sp.RULES, *sp.SOURCE_RULES.values()] for _, c in rules if c}
    packed = {c for _, cs in sp.PACKS.values() for c in cs}
    assert cats <= packed
    assert packed <= set(sp.TAGS)
    assert all(src["page"].startswith("https://") for src in sp.SOURCES)


def _pack(root, name, files, **meta):
    d = root / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_bytes(b"x")
    (d / "pack.json").write_text(json.dumps(meta))


def test_your_packs_win_over_generated_ones_and_tags_count(tmp_path, monkeypatch):
    root = tmp_path / "sound-packs"
    _pack(root, "aaa-gerado", ["scream-1.ogg", "glass-break-1.ogg", "break-1.ogg"], source="shortpipeline-sounds",
          tags={"glass-break": ["vidro", "quebrando"], "break": ["quebrando"]})
    _pack(root, "meus-gritos", ["scream-1.mp3"])
    (root / ".downloads").mkdir()
    monkeypatch.setattr(sound, "USER_PACKS", root)
    assert sound.match_sound("a woman screaming", "terror").parent.name == "meus-gritos"
    assert sound.match_sound("vidro quebrando", "neutro").stem == "glass-break-1"
    assert ".downloads" not in {p.name for p, _ in sound._packs(None, user_only=True)}
