import json


def test_load_creates_defaults(fresh_config):
    cfg = fresh_config.load()
    assert fresh_config.CONFIG_PATH.exists()
    assert {"general", "providers", "channels"} <= set(cfg)
    assert {"terror", "tech"} <= set(cfg["channels"])
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
