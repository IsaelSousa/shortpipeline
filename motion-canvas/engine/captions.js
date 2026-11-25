// Legendas por palavra: grupos curtos, palavra falada em destaque, palavras importantes (números e a lista
// `emphasis`) sempre na cor de ênfase. A posição evita as áreas ocupadas por informativos e a interface das
// plataformas (topo, base e lateral direita).
import { DESIGN } from './camera.js';
import { FONT } from './overlays.js';
import { clamp, ease } from './util.js';

export const SAFE = { top: 0.12, bottom: 0.80, left: 0.07, right: 0.86 };

export function groupWords(words, maxWords = 3) {
  const groups = [];
  let cur = [];
  words.forEach((w, i) => {
    cur.push(w);
    const next = words[i + 1];
    const gap = next ? next.start - w.end : 1;
    if (cur.length >= maxWords || /[.!?,;:]$/.test(w.text) || gap > 0.35 || !next) { groups.push(cur); cur = []; }
  });
  return groups.map((g, i) => ({ words: g, start: g[0].start, end: Math.max(g[g.length - 1].end, (groups[i + 1]?.[0]?.start ?? 1e9) - 0.02) }));
}

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function drawCaptions(ctx, groups, T, style, boxes, theme) {
  const g = groups.find((x) => T >= x.start && T < Math.min(x.end, x.start + 4));
  if (!g) return null;
  const size = style.size || 92;
  const upper = style.uppercase !== false;
  ctx.font = `400 ${size}px ${FONT.display}`;
  const texts = g.words.map((w) => (upper ? w.text.toUpperCase() : w.text));
  // o contorno grosso come o espaço da fonte condensada: espaço mínimo proporcional ao tamanho
  const space = Math.max(ctx.measureText(' ').width, size * 0.3);
  const widths = texts.map((x) => ctx.measureText(x).width);
  const maxW = DESIGN.W * (SAFE.right - SAFE.left);
  // quebra em até 2 linhas
  const lines = [[]];
  let lw = 0;
  texts.forEach((_, i) => {
    if (lw + widths[i] > maxW && lines[lines.length - 1].length) { lines.push([]); lw = 0; }
    lines[lines.length - 1].push(i); lw += widths[i] + space;
  });
  const lh = size * 1.12;
  const h = lines.length * lh;
  const cx = DESIGN.W * (SAFE.left + SAFE.right) / 2;
  const candidates = [style.y ?? 0.66, 0.38, 0.74, 0.24].map((f) => f * DESIGN.H);
  const box = (y) => ({ x: DESIGN.W * SAFE.left, y: y - h / 2 - 20, w: maxW, h: h + 40 });
  let y = candidates[0];
  for (const c of candidates) {
    const b = box(c);
    if (b.y >= DESIGN.H * SAFE.top && b.y + b.h <= DESIGN.H * SAFE.bottom && !boxes.some((o) => overlap(b, o))) { y = c; break; }
  }
  const pop = 0.9 + 0.1 * ease('back', clamp((T - g.start) / 0.14));
  const emphasis = new Set((style.emphasis || []).map((w) => w.toLowerCase()));
  ctx.save();
  ctx.translate(cx, y);
  ctx.scale(pop, pop);
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  ctx.lineJoin = 'round';
  lines.forEach((idxs, li) => {
    const total = idxs.reduce((s, i) => s + widths[i], 0) + space * (idxs.length - 1);
    let x = -total / 2;
    const yy = (li - (lines.length - 1) / 2) * lh;
    for (const i of idxs) {
      const w = g.words[i];
      const active = T >= w.start && T < w.end + 0.05;
      const plain = w.text.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
      const important = emphasis.has(plain) || /\d/.test(w.text);
      ctx.save();
      ctx.translate(x + widths[i] / 2, yy);
      if (active) ctx.scale(1.08, 1.08);
      ctx.lineWidth = size * 0.16;
      ctx.strokeStyle = 'rgba(10,14,26,0.95)';
      ctx.shadowColor = 'rgba(0,0,0,0.35)';
      ctx.shadowBlur = 12;
      ctx.shadowOffsetY = 6;
      ctx.strokeText(texts[i], -widths[i] / 2, 0);
      ctx.shadowColor = 'transparent';
      ctx.fillStyle = active ? (style.highlight || theme.accent) : important ? (theme.accent2 || '#FDE047') : '#FFFFFF';
      ctx.fillText(texts[i], -widths[i] / 2, 0);
      ctx.restore();
      x += widths[i] + space;
    }
  });
  ctx.restore();
  return box(y);
}
