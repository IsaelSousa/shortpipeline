"""Rotas da API sem subir o worker (TestClient sem `with` não roda o lifespan)."""

import pytest
from fastapi.testclient import TestClient

from shortpipeline import db
from shortpipeline.server import app


@pytest.fixture
def client(fresh_config):
    return TestClient(app)


def test_index_and_static(client):
    html = client.get("/").text
    assert "/static/js/main.js" in html
    for src in [part.split('"')[0] for part in html.split('src="/static/')[1:]]:
        assert client.get(f"/static/{src}").status_code == 200, src


def test_meta_lists_stages(client):
    meta = client.get("/api/meta").json()
    assert meta["kind_stages"]["short"][0] == "ideia"
    assert "render" in meta["stage_labels"]


def test_config_roundtrip(client):
    cfg = client.get("/api/config").json()
    cfg["channels"]["tech"]["name"] = "Tecnologia de teste"
    assert client.put("/api/config", json=cfg).status_code == 200
    assert client.get("/api/config").json()["channels"]["tech"]["name"] == "Tecnologia de teste"
    assert client.put("/api/config", json={"general": {}}).status_code == 400


def test_channel_create_and_delete(client, tmp_path, monkeypatch):
    from shortpipeline import config

    monkeypatch.setattr(config, "MUSIC_DIR", tmp_path / "music")  # não cria pasta dentro do repo
    res = client.post("/api/channels", json={"name": "Receitas Rápidas"})
    assert res.status_code == 200
    cid = res.json()["id"]
    assert client.get("/api/config").json()["channels"][cid]["name"] == "Receitas Rápidas"
    assert client.post("/api/channels", json={"name": "Receitas Rápidas"}).status_code == 409
    assert client.delete(f"/api/channels/{cid}").status_code == 200
    assert cid not in client.get("/api/config").json()["channels"]


def test_job_lifecycle(client):
    res = client.post("/api/jobs", json={"channel": "terror", "topic": "um teste", "count": 1})
    assert res.status_code == 200, res.text
    (job_id,) = res.json()["created"]
    job = {"id": job_id}
    assert db.get_job(job_id)["status"] == "queued"
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    assert client.post("/api/jobs", json={"channel": "nao-existe"}).status_code == 400
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert db.get_job(job["id"]) is None


def test_job_file_rejects_path_traversal(client):
    job = db.create_job("terror", topic="arquivos")
    res = client.get(f"/api/jobs/{job['id']}/file/..%2F..%2Fconfig.json")
    assert res.status_code in (400, 403, 404)
