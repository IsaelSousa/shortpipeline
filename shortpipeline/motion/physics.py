"""Física dos vídeos animados no lado Python: os números que o vídeo afirma saem daqui, com as premissas.

A engine (motion-canvas/engine/physics.js) usa as mesmas fórmulas para o movimento; aqui elas viram fatos
registrados no JSON (kind "calculation"), para o vídeo distinguir cálculo de ilustração.
"""

from __future__ import annotations

import math

G = 9.81


def free_fall(height_m: float, g: float = G) -> dict:
    """Queda livre a partir do repouso, sem resistência do ar."""
    t = math.sqrt(2 * max(height_m, 0) / g)
    v = g * t
    return {"seconds": t, "mps": v, "kmh": v * 3.6}


def fall_facts(video) -> list[dict]:
    """Um fato calculado por queda do storyboard (altura do objeto até o chão da ação)."""
    out = []
    for sc in video.scenes:
        for o in sc.objects:
            for a in o.actions:
                if a.type != "fall":
                    continue
                h = max(0.0, o.height - (a.ground or 0))
                f = free_fall(h)
                out.append({
                    "claim": f"{o.asset} cai {h:.1f} m em {f['seconds']:.2f} s e chega a {f['kmh']:.0f} km/h",
                    "kind": "calculation", "formula": "t = √(2h/g); v = g·t",
                    "assumptions": "g = 9,81 m/s², a partir do repouso, sem resistência do ar",
                    "value": round(f["kmh"], 1), "source": f"cena {sc.id}",
                })
    return out
