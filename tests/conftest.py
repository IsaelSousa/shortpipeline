"""Os testes rodam numa pasta de dados temporária, sem chaves de API e sem CLIs de IA."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# precisa vir antes de qualquer import do shortpipeline: config.DATA_DIR é lido na importação
DATA = Path(tempfile.mkdtemp(prefix="shortpipeline-test-"))
os.environ["SHORTPIPELINE_DATA"] = str(DATA)
for var in [v for v in os.environ if v.endswith("_API_KEY")]:
    os.environ.pop(var)

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                  reason="ffmpeg/ffprobe não instalados")


@pytest.fixture
def fresh_config():
    """Apaga o config.json para cada teste começar dos padrões."""
    from shortpipeline import config

    config.CONFIG_PATH.unlink(missing_ok=True)
    yield config
    config.CONFIG_PATH.unlink(missing_ok=True)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(DATA, ignore_errors=True)


@pytest.fixture
def channel(fresh_config):
    """Um canal de exemplo criado na hora (receitas), para os testes não dependerem de nenhum nicho."""
    cfg = fresh_config.load()
    ch = fresh_config.new_channel_config("Receitas Rápidas")
    ch["niche"] = "receitas rápidas para o dia a dia"
    cfg["channels"]["receitas"] = ch
    fresh_config.save(cfg)
    return "receitas"
