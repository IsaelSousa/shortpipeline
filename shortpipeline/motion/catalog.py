"""Catálogo de componentes e assets da animação: o que a IA pode usar, num resumo curto para o prompt."""

from __future__ import annotations

import json
from functools import lru_cache

from .. import config

REGISTRY = config.ASSETS_DIR / "motion" / "registry.json"
USER_REGISTRY = config.DATA_DIR / "motion-assets" / "registry.json"


@lru_cache(maxsize=1)
def registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    try:
        user = json.loads(USER_REGISTRY.read_text(encoding="utf-8"))
        known = {a["id"] for a in data["assets"]}
        data["assets"] += [a for a in user.get("assets", []) if a.get("id") not in known]
    except (OSError, ValueError):
        pass
    return data


def asset_ids() -> list[str]:
    return [a["id"] for a in registry()["assets"]]


def prompt_catalog() -> str:
    """Resumo compacto (uma linha por asset) para o prompt do storyboard: o registry inteiro gastaria tokens."""
    r = registry()
    ch = r["characters"]
    lines = ["Objetos (id [largura×altura m]: ações):"]
    for a in r["assets"]:
        w, h = a["size_m"]
        lines.append(f"- {a['id']} [{w:g}×{h:g}] {', '.join(a['tags'][:3])}: {', '.join(a['actions'])}")
    lines.append("Cenários: " + "; ".join(f"{e['id']} ({', '.join(e['params'])})" for e in r["environments"]))
    lines.append(f"Personagem: ações {', '.join(ch['actions'])}; reaction.style {', '.join(ch['reaction_styles'])}; "
                 f"expressões {', '.join(ch['expressions'])}; cabelo {', '.join(ch['hair_styles'])}; "
                 f"acessórios {', '.join(ch['accessories'])}")
    lines.append(f"Câmera: {', '.join(r['camera'])}. Informativos: {', '.join(r['overlays'])}. "
                 f"Efeitos: {', '.join(r['effects'])}. Entradas de cena: {', '.join(r['transitions'])}.")
    return "\n".join(lines)


def usage_report(video) -> dict:
    """Quantos usos de cada asset o storyboard fez (o catálogo inteiro é reaproveitado; nada é gerado)."""
    counts: dict[str, int] = {}
    for sc in video.scenes:
        for o in sc.objects:
            counts[o.asset] = counts.get(o.asset, 0) + 1
    return counts
