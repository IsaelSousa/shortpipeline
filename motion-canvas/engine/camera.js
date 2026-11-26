// Câmera da cena: começa em `camera.start` e cada movimento parte do estado em que a anterior terminou.
// Tipos: pan, zoom, focus (centra num alvo e aproxima), follow (acompanha um alvo), shake (tremor), roll.
import { lerp, noise1, window01 } from './util.js';

export const DESIGN = { W: 1080, H: 1920 };

/** Câmera padrão: chão a 78% da altura da tela. */
export function defaultStart() {
  return { x: 0, y: -0.28 * DESIGN.H, zoom: 1 };
}

/**
 * `resolve(id, t)` devolve a posição {x, y} de um personagem ou objeto no tempo t (para follow/focus).
 * O ponto da tela onde o alvo fica é `frame_y` (0–1, padrão 0.45).
 */
export function cameraAt(camera, t, resolve, W) {
  const start = { ...defaultStart(), ...(camera?.start || {}) };
  let st = { x: start.x, y: start.y, zoom: start.zoom };
  let shakeX = 0, shakeY = 0, roll = 0;
  const center = (target, frameY, zoom, time) => {
    const p = resolve(target, time);
    if (!p) return null;
    // o alvo aparece em frame_y da altura da tela, não necessariamente no centro
    return { x: p.x, y: p.y - (frameY - 0.5) * DESIGN.H / zoom };
  };
  for (const m of [...(camera?.moves || [])].sort((a, b) => a.start - b.start)) {
    if (t < m.start) continue;
    const dur = Math.max(0.01, (m.end ?? m.start + (m.dur ?? 1)) - m.start);
    const p = window01(t, m.start, dur, m.ease || 'inOut');
    if (m.type === 'shake') {
      const k = t - m.start;
      if (k < dur) {
        const amp = (m.intensity ?? 18) * (1 - k / dur);
        shakeX += noise1('shx' + m.start, k * 28) * amp;
        shakeY += noise1('shy' + m.start, k * 28) * amp;
      }
      continue;
    }
    if (m.type === 'roll') { roll = lerp(roll, m.angle ?? 0.05, p); continue; }
    const zoom = m.zoom ?? st.zoom;
    if (m.type === 'cut') {
      const target = center(m.target, m.frame_y ?? 0.45, zoom, m.start);
      st = { x: m.x ?? target?.x ?? st.x, y: m.y ?? target?.y ?? st.y, zoom };
      shakeX = 0;
      shakeY = 0;
      roll = 0;
      continue;
    }
    let to;
    if (m.type === 'follow' || m.type === 'focus') {
      // follow: acompanha o alvo enquanto dura e para onde ele estava no fim
      const time = m.type === 'follow' ? Math.min(t, m.start + dur) : m.start + dur;
      to = center(m.target, m.frame_y ?? 0.45, zoom, time) || st;
      const blend = m.type === 'follow' ? window01(t, m.start, Math.min(0.6, dur), 'inOut') : p;
      st = { x: lerp(st.x, to.x + (m.offset_x || 0), blend), y: lerp(st.y, to.y + (m.offset_y || 0), blend),
             zoom: lerp(st.zoom, zoom, p) };
    } else {
      to = { x: m.x ?? st.x, y: m.y ?? st.y };
      st = { x: lerp(st.x, to.x, p), y: lerp(st.y, to.y, p), zoom: lerp(st.zoom, zoom, p) };
    }
  }
  return { ...st, shakeX, shakeY, roll, base: W / DESIGN.W };
}
