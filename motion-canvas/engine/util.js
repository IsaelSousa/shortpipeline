// Funções puras usadas por toda a engine. Nada aqui depende do relógio: tudo é função do tempo da cena.

export const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
export const lerp = (a, b, t) => a + (b - a) * t;
export const invLerp = (a, b, v) => (b === a ? 1 : clamp((v - a) / (b - a)));
export const smooth = (t) => t * t * (3 - 2 * t);

export const EASE = {
  linear: (t) => t,
  in: (t) => t * t * t,
  out: (t) => 1 - (1 - t) ** 3,
  inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  back: (t) => 1 + 2.2 * (t - 1) ** 3 + 1.2 * (t - 1) ** 2,
  elastic: (t) => (t === 0 || t === 1 ? t : 2 ** (-10 * t) * Math.sin((t * 10 - 0.75) * (2 * Math.PI) / 3) + 1),
};
export const ease = (name, t) => (EASE[name] || EASE.inOut)(clamp(t));

/** Progresso eased de uma janela [start, start+dur] no tempo t. */
export const window01 = (t, start, dur, easing = 'inOut') => ease(easing, invLerp(start, start + Math.max(dur, 1e-6), t));

/** Hash de texto para semente (mesmo id → mesmos números em todo quadro). */
export function hash(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** Gerador pseudoaleatório determinístico (mulberry32). */
export function rng(seed) {
  let a = typeof seed === 'string' ? hash(seed) : seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Ruído suave 1D determinístico (para tremor de câmera e respiração). */
export function noise1(seed, x) {
  const i = Math.floor(x);
  const f = x - i;
  const r = (k) => rng(seed + k * 7919)();
  return lerp(r(i), r(i + 1), smooth(f)) * 2 - 1;
}

export function shade(hex, amount) {
  const n = parseInt(hex.replace('#', ''), 16);
  const ch = (s) => clamp(Math.round(((n >> s) & 255) * (1 + amount)), 0, 255);
  return `rgb(${ch(16)},${ch(8)},${ch(0)})`;
}

export function roundRect(ctx, x, y, w, h, r) {
  const rr = Math.min(r, Math.abs(w) / 2, Math.abs(h) / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}
