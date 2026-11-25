// Efeitos visuais curtos e discretos. Os de mundo (impact, dust, speed_lines, smoke, light) ficam presos a um alvo
// ou a uma posição da cena; os de tela (wind, rain, flash) cobrem o quadro.
import { DESIGN } from './camera.js';
import { clamp, rng } from './util.js';

export function drawWorldEffect(ctx, e, t, resolve, upm) {
  const at = e.at ?? e.start;
  const k = t - at;
  const target = e.target ? resolve(e.target, t) : null;
  const x = target ? target.x : (e.x ?? 0);
  const y = target ? target.y + (e.type === 'dust' || e.type === 'impact' ? (target.h || 0) / 2 : 0) : (e.y ?? 0);
  const size = (e.size ?? 1) * upm;
  ctx.save();
  if (e.type === 'impact' && k >= 0 && k < 0.6) {
    const p = k / 0.6;
    ctx.globalAlpha = 1 - p;
    ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 0.06 * size * (1 - p) + 2;
    ctx.beginPath(); ctx.ellipse(x, y, size * (0.4 + p * 1.6), size * (0.12 + p * 0.45), 0, 0, Math.PI * 2); ctx.stroke();
    ctx.strokeStyle = '#FDE68A'; ctx.lineWidth = 0.04 * size + 2;
    for (let i = 0; i < 10; i++) {
      const a = Math.PI + (i / 9) * Math.PI;
      const r0 = size * (0.3 + p * 0.6), r1 = size * (0.5 + p * 1.2);
      ctx.beginPath(); ctx.moveTo(x + Math.cos(a) * r0, y + Math.sin(a) * r0 * 0.7); ctx.lineTo(x + Math.cos(a) * r1, y + Math.sin(a) * r1 * 0.7); ctx.stroke();
    }
  } else if (e.type === 'dust' && k >= 0 && k < 1.6) {
    const r = rng('dust' + at);
    for (let i = 0; i < 18; i++) {
      const dir = (r() - 0.5) * 2;
      const sp = 0.6 + r() * 1.4;
      const px = x + dir * size * sp * Math.min(1, k * 1.8);
      const py = y - size * (0.1 + r() * 0.5) * Math.min(1, k * 1.2);
      const rad = size * (0.12 + r() * 0.18) * (0.6 + k);
      ctx.globalAlpha = clamp(0.55 * (1 - k / 1.6));
      ctx.fillStyle = e.color || '#D6CFC4';
      ctx.beginPath(); ctx.arc(px, py, rad, 0, Math.PI * 2); ctx.fill();
    }
  } else if (e.type === 'smoke' && t >= e.start && t <= (e.end ?? e.start + 3)) {
    const r = rng('smoke' + e.start);
    for (let i = 0; i < 12; i++) {
      const life = ((t - e.start) * 0.6 + r()) % 1;
      ctx.globalAlpha = 0.35 * (1 - life);
      ctx.fillStyle = e.color || '#9CA3AF';
      ctx.beginPath(); ctx.arc(x + (r() - 0.5) * size * 0.6 + life * size * 0.3, y - life * size * 2.5, size * (0.15 + life * 0.5), 0, Math.PI * 2); ctx.fill();
    }
  } else if (e.type === 'speed_lines' && target && t >= e.start && t <= (e.end ?? e.start + 1)) {
    const speed = Math.hypot(target.vx || 0, target.vy || 0);
    const len = clamp(speed / (20 * upm)) * 3 * upm;
    const r = rng('sl' + e.start);
    ctx.strokeStyle = 'rgba(255,255,255,0.75)'; ctx.lineCap = 'round';
    for (let i = 0; i < 7; i++) {
      const ox = (r() - 0.5) * (target.w || upm) * 1.2;
      const oy = -(target.h || upm) * 0.6 - r() * len * 0.3;
      ctx.lineWidth = 3 + r() * 5;
      ctx.beginPath(); ctx.moveTo(x + ox, y + oy); ctx.lineTo(x + ox, y + oy - len * (0.5 + r() * 0.5)); ctx.stroke();
    }
  } else if (e.type === 'light' && t >= e.start && t <= (e.end ?? e.start + 2)) {
    const g = ctx.createRadialGradient(x, y, 0, x, y, size * 2);
    g.addColorStop(0, e.color || 'rgba(253,230,138,0.6)'); g.addColorStop(1, 'rgba(253,230,138,0)');
    ctx.fillStyle = g; ctx.fillRect(x - size * 2, y - size * 2, size * 4, size * 4);
  }
  ctx.restore();
}

export function drawScreenEffect(ctx, e, t) {
  const at = e.at ?? e.start;
  ctx.save();
  if (e.type === 'flash' && t >= at && t < at + 0.18) {
    ctx.globalAlpha = 0.75 * (1 - (t - at) / 0.18);
    ctx.fillStyle = e.color || '#FFFFFF';
    ctx.fillRect(0, 0, DESIGN.W, DESIGN.H);
  } else if (e.type === 'wind' && t >= e.start && t <= (e.end ?? e.start + 2)) {
    const r = rng('wind' + e.start);
    ctx.strokeStyle = 'rgba(255,255,255,0.45)'; ctx.lineCap = 'round'; ctx.lineWidth = 4;
    for (let i = 0; i < 14; i++) {
      const y = r() * DESIGN.H * 0.8;
      const x = ((r() * DESIGN.W + (t - e.start) * (900 + r() * 700)) % (DESIGN.W + 400)) - 200;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + 140 + r() * 120, y + 6); ctx.stroke();
    }
  } else if (e.type === 'rain' && t >= e.start && t <= (e.end ?? e.start + 5)) {
    const r = rng('rain');
    ctx.strokeStyle = 'rgba(200,220,255,0.5)'; ctx.lineWidth = 3;
    for (let i = 0; i < 90; i++) {
      const x = r() * DESIGN.W;
      const y = (r() * DESIGN.H + (t - e.start) * 1700) % DESIGN.H;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 8, y + 40); ctx.stroke();
    }
  }
  ctx.restore();
}

export const WORLD_EFFECTS = ['impact', 'dust', 'smoke', 'speed_lines', 'light'];
export const SCREEN_EFFECTS = ['flash', 'wind', 'rain'];
