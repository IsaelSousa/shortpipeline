"""O Analytics guia a escolha do tema: a análise vira temas com nota, e a etapa de pauta recebe isso."""

import asyncio
import json

from shortpipeline import config, db, learn
from shortpipeline.pipeline import core, writing

VIDEOS = [
    {"titulo": "Como funciona a bateria de sódio", "familia": "como funciona", "views": 600, "pct_assistido": 95.0, "inscritos": 4},
    {"titulo": "Por dentro de um cabo USB-C", "familia": "como funciona", "views": 540, "pct_assistido": 120.0},
    {"titulo": "Os 5 melhores apps da semana", "familia": "lista", "views": 30, "pct_assistido": 40.0},
]
ANALYSIS = {
    "themes": [{"theme": "listas de apps", "score": 0.2, "evidence": "30 views"},
               {"theme": "como um aparelho comum funciona por dentro", "score": 0.9, "evidence": "600 views"},
               {"theme": "", "score": 1}],
    "next_topics": ["Por que o carregador esquenta"],
    "insights": "- abra com o resultado", "format_scores": {}, "summary": "explicações rendem",
}


def test_run_saves_themes_and_numbers(channel, monkeypatch):
    monkeypatch.setattr(learn, "_collect_sync", lambda cid, days: VIDEOS)

    async def ask(cfg, ch, prompt):
        assert "TEMAS E ASSUNTOS" in prompt
        return json.dumps(ANALYSIS)

    monkeypatch.setattr(learn, "_ask", ask)
    data = asyncio.run(learn.run(channel))
    assert [t["theme"] for t in data["themes"]] == ["como um aparelho comum funciona por dentro", "listas de apps"]
    assert data["next_topics"] == ANALYSIS["next_topics"]
    assert data["performance"][0] == {"titulo": "Como funciona a bateria de sódio", "familia": "como funciona", "views": 600,
                                      "pct_assistido": 95.0, "inscritos": 4}

    ch = config.load()["channels"][channel]
    brief = learn.topic_brief(channel, ch)
    assert brief.index("como um aparelho comum") < brief.index("listas de apps (0.20)")
    assert "Como funciona a bateria de sódio [como funciona]: 600 views" in brief
    assert "carregador esquenta" in brief
    ch["creative"]["learn_topics"] = False
    assert learn.topic_brief(channel, ch) == ""


def test_idea_stage_uses_analytics_first(channel, monkeypatch):
    learn._save(channel, {"themes": [{"theme": "aparelhos por dentro", "score": 0.9, "evidence": ""}],
                           "performance": VIDEOS, "insights": ""})
    prompts = []
    candidate = {"topic": "O que acontece dentro do micro-ondas", "family": "como funciona", "angle": "a",
                 "opening": "o", "payoff": "p"}

    async def text(self, stage_key, prompt):
        prompts.append(prompt)
        if "candidates" in prompt and "selected_id" not in prompt:
            return json.dumps({"candidates": [candidate]})
        return json.dumps({"selected_id": 1, "reason": "tema que mais rende"})

    monkeypatch.setattr(core.Ctx, "text", text)
    job = db.create_job(channel)
    c = core.Ctx(job, config.load())
    asyncio.run(writing.stage_ideia(c))
    generate, review = prompts
    for p in (generate, review):
        assert "O QUE OS NÚMEROS DO CANAL MOSTRAM" in p and "aparelhos por dentro (0.90)" in p
    assert "Pelo menos 4 das 6" in generate
    assert "Escolha principalmente pelos números" in review
    assert c.job["topic"] == candidate["topic"]
    learn.path(channel).unlink()
