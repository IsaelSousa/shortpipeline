import json


def test_load_creates_defaults(fresh_config):
    cfg = fresh_config.load()
    assert fresh_config.CONFIG_PATH.exists()
    assert {"general", "providers", "channels"} <= set(cfg)
    assert cfg["channels"]  # vem com canais de exemplo para editar
    for ch in cfg["channels"].values():
        assert set(fresh_config.MODEL_STAGES) <= set(ch["models"])


def test_load_fills_missing_keys(fresh_config):
    fresh_config.CONFIG_PATH.write_text(json.dumps({
        "general": {}, "providers": {},
        "channels": {"meu": {"name": "Meu canal", "video": {"scenes": 4}}},
    }))
    ch = fresh_config.load()["channels"]["meu"]
    assert ch["name"] == "Meu canal"
    assert ch["video"]["scenes"] == 4  # o valor do usuário fica
    assert ch["video"]["caption_font"]  # o que faltava vem do modelo
    assert "critica" in ch["models"]


def test_legacy_keys_are_migrated(fresh_config):
    fresh_config.CONFIG_PATH.write_text(json.dumps({
        "general": {}, "providers": {}, "tiktok": {"client_key": "x"},
        "channels": {"tech": {"name": "Tech", "creative": {"hype_meter": True, "hype_label": "HYPE"},
                              "upload": {"publish_to_tiktok": True}}},
    }))
    cfg = fresh_config.load()
    cr = cfg["channels"]["tech"]["creative"]
    assert cr["rating_meter"] is True and cr["rating_label"] == "HYPE"
    assert "hype_meter" not in cr and "hype_label" not in cr
    assert "tiktok" not in cfg
    assert "publish_to_tiktok" not in cfg["channels"]["tech"]["upload"]


def test_save_roundtrip(fresh_config):
    cfg = fresh_config.load()
    cfg["channels"]["tech"]["video"]["scenes"] = 9
    fresh_config.save(cfg)
    assert fresh_config.load()["channels"]["tech"]["video"]["scenes"] == 9


def test_new_channel_config_has_every_stage(fresh_config):
    ch = fresh_config.new_channel_config("Receitas")
    assert ch["name"] == "Receitas"
    assert set(fresh_config.MODEL_STAGES) <= set(ch["models"])


def test_new_channel_is_neutral(fresh_config):
    """Canal novo não herda nada de um nicho: nem terror, nem tecnologia."""
    ch = fresh_config.new_channel_config("Jardinagem")
    assert ch["niche"] == "" and ch["idea"]["source"] == "llm" and not ch["idea"]["rss_urls"]
    assert ch["video"]["effects"] == "none" and ch["creative"]["sound_style"] == "neutro"
    text = " ".join([*ch["prompts"].values(), *ch["creative"]["formats"]]).lower()
    for word in ("terror", "horror", "medo", "tecnologia", "tech", "gadget", "neon", "arrepiante"):
        assert word not in text, word
    assert ch["prompts"]["script"] == fresh_config.GENERIC_SCRIPT_PROMPT
    # mexer num canal novo não altera o modelo dos próximos
    ch["creative"]["formats"].append("x")
    assert "x" not in fresh_config.new_channel_config("Outro")["creative"]["formats"]


def test_existing_channels_keep_their_style_defaults(fresh_config):
    fresh_config.CONFIG_PATH.write_text(json.dumps({"general": {}, "providers": {}, "channels": {
        "meuterror": {"name": "A", "creative": {"sound_style": "terror"}},
        "minhacozinha": {"name": "B", "creative": {"sound_style": "neutro"}},
    }}))
    chans = fresh_config.load()["channels"]
    assert chans["meuterror"]["prompts"]["script"] == fresh_config.TERROR_SCRIPT_PROMPT
    assert chans["minhacozinha"]["prompts"]["script"] == fresh_config.GENERIC_SCRIPT_PROMPT
