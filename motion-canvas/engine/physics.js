// Física simples e determinística. As posições ficam em unidades do mundo (px a zoom 1);
// `upm` (unidades por metro) converte para metros quando o vídeo mostra números.

export const G = 9.81;

/**
 * Queda livre a partir do repouso, sem resistência do ar, com um pequeno quique ao tocar o chão.
 * Devolve posição, velocidade (unidades/s) e o instante do impacto (relativo ao início da queda).
 */
export function fall(t, { y0, groundY, upm, g = G, bounce = 0.18, rotate = 0 }) {
  const gu = g * upm;
  const h = Math.max(0, groundY - y0);
  const tImpact = Math.sqrt((2 * h) / gu);
  if (t <= 0) return { y: y0, vy: 0, angle: 0, landed: false, tImpact };
  if (t < tImpact) {
    return { y: y0 + 0.5 * gu * t * t, vy: gu * t, angle: rotate * t, landed: false, tImpact };
  }
  // quique amortecido: uma parábola pequena e depois repouso
  const v1 = gu * tImpact * bounce;
  const tb = (2 * v1) / gu;
  const dt = t - tImpact;
  const y = dt < tb ? groundY - (v1 * dt - 0.5 * gu * dt * dt) : groundY;
  return { y, vy: dt < tb ? -(v1 - gu * dt) : 0, angle: rotate * tImpact, landed: true, tImpact };
}

/** Valores da queda em unidades reais, para mostrar e para registrar no JSON (premissas explícitas). */
export function fallFacts(heightM, g = G) {
  const t = Math.sqrt((2 * heightM) / g);
  const v = g * t;
  return { seconds: t, mps: v, kmh: v * 3.6 };
}

/** Pêndulo amortecido (ex.: um objeto balançando num suporte). Ângulo em radianos. */
export function pendulum(t, { amplitude = 0.12, period = 1.4, damping = 0 }) {
  return amplitude * Math.exp(-damping * t) * Math.sin((2 * Math.PI * t) / period);
}

/** Lançamento oblíquo: posição em t com velocidade inicial (unidades/s). */
export function projectile(t, { x0, y0, vx, vy, upm, g = G }) {
  return { x: x0 + vx * t, y: y0 + vy * t + 0.5 * g * upm * t * t, vy: vy + g * upm * t, vx };
}
