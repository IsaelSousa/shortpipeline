// Objetos desenhados por código (vetor flat com volume simples). Cada asset tem medidas reais em metros;
// o estado (posição, ângulo, escala, opacidade, velocidade) é função do tempo da cena.
import { fall, pendulum } from './physics.js';
import { clamp, ease, invLerp, lerp, noise1, rng, roundRect, shade, window01 } from './util.js';

function box3d(ctx, w, h, d, color) {
  // frente + topo + lateral: o "2.5D" dos objetos
  ctx.fillStyle = shade(color, 0.12);
  ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(-w / 2 + d, -h / 2 - d * 0.6); ctx.lineTo(w / 2 + d, -h / 2 - d * 0.6); ctx.lineTo(w / 2, -h / 2); ctx.fill();
  ctx.fillStyle = shade(color, -0.2);
  ctx.beginPath(); ctx.moveTo(w / 2, -h / 2); ctx.lineTo(w / 2 + d, -h / 2 - d * 0.6); ctx.lineTo(w / 2 + d, h / 2 - d * 0.6); ctx.lineTo(w / 2, h / 2); ctx.fill();
  ctx.fillStyle = color;
  ctx.fillRect(-w / 2, -h / 2, w, h);
}

export const ASSETS = {
  air_conditioner: {
    size: [0.8, 0.55], draw(ctx, w, h, o) {
      box3d(ctx, w, h, w * 0.12, o.color || '#EEF2F6');
      ctx.fillStyle = '#9CA3AF';
      ctx.beginPath(); ctx.arc(-w * 0.12, 0, h * 0.34, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = '#6B7280'; ctx.lineWidth = w * 0.012;
      for (let i = -3; i <= 3; i++) { ctx.beginPath(); ctx.moveTo(-w * 0.12 + i * h * 0.09, -h * 0.3); ctx.lineTo(-w * 0.12 + i * h * 0.09, h * 0.3); ctx.stroke(); }
      ctx.fillStyle = '#D1D5DB';
      for (let i = 0; i < 6; i++) ctx.fillRect(w * 0.2, -h * 0.32 + i * h * 0.11, w * 0.24, h * 0.05);
      ctx.fillStyle = '#4B5563'; ctx.fillRect(-w / 2, h / 2 - h * 0.06, w, h * 0.06);
    },
  },
  bracket: {
    size: [0.9, 0.18], draw(ctx, w, h) {
      ctx.fillStyle = '#6B7280'; ctx.fillRect(-w / 2, -h / 2, w, h * 0.4);
      ctx.beginPath(); ctx.moveTo(-w / 2, -h / 2); ctx.lineTo(-w / 2, h * 2); ctx.lineTo(-w / 2 + h, -h / 2); ctx.fill();
      ctx.beginPath(); ctx.moveTo(w / 2, -h / 2); ctx.lineTo(w / 2, h * 2); ctx.lineTo(w / 2 - h, -h / 2); ctx.fill();
    },
  },
  crate: {
    size: [0.7, 0.7], draw(ctx, w, h, o) {
      box3d(ctx, w, h, w * 0.14, o.color || '#C08A55');
      ctx.strokeStyle = shade(o.color || '#C08A55', -0.3); ctx.lineWidth = w * 0.05;
      ctx.strokeRect(-w / 2 + w * 0.05, -h / 2 + h * 0.05, w * 0.9, h * 0.9);
      ctx.beginPath(); ctx.moveTo(-w * 0.42, -h * 0.42); ctx.lineTo(w * 0.42, h * 0.42); ctx.stroke();
    },
  },
  ball: {
    size: [0.24, 0.24], draw(ctx, w, h, o) {
      const c = o.color || '#EF4444';
      ctx.fillStyle = c; ctx.beginPath(); ctx.arc(0, 0, w / 2, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.35)'; ctx.beginPath(); ctx.arc(-w * 0.15, -w * 0.15, w * 0.16, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = shade(c, -0.3); ctx.lineWidth = w * 0.05; ctx.beginPath(); ctx.arc(0, 0, w / 2, 0.3, 2.6); ctx.stroke();
    },
  },
  flower_pot: {
    size: [0.35, 0.5], draw(ctx, w, h) {
      ctx.fillStyle = '#C2410C';
      ctx.beginPath(); ctx.moveTo(-w / 2, 0); ctx.lineTo(w / 2, 0); ctx.lineTo(w * 0.36, h / 2); ctx.lineTo(-w * 0.36, h / 2); ctx.fill();
      ctx.fillStyle = '#16A34A';
      for (const [dx, r] of [[-0.18, 0.2], [0.16, 0.22], [0, 0.26]]) { ctx.beginPath(); ctx.arc(dx * w, -h * 0.18 - r * w * 0.6, r * w, 0, Math.PI * 2); ctx.fill(); }
    },
  },
  phone: {
    size: [0.075, 0.155], draw(ctx, w, h, o) {
      ctx.fillStyle = '#111827'; roundRect(ctx, -w / 2, -h / 2, w, h, w * 0.18); ctx.fill();
      ctx.fillStyle = o.color || '#38BDF8'; roundRect(ctx, -w * 0.42, -h * 0.44, w * 0.84, h * 0.86, w * 0.1); ctx.fill();
    },
  },
  car: {
    size: [4.2, 1.45], draw(ctx, w, h, o) {
      const c = o.color || '#2563EB';
      ctx.fillStyle = c;
      roundRect(ctx, -w / 2, -h * 0.1, w, h * 0.45, h * 0.15); ctx.fill();
      ctx.beginPath(); ctx.moveTo(-w * 0.3, -h * 0.1); ctx.lineTo(-w * 0.18, -h / 2); ctx.lineTo(w * 0.2, -h / 2); ctx.lineTo(w * 0.34, -h * 0.1); ctx.fill();
      ctx.fillStyle = '#BFDBFE';
      ctx.beginPath(); ctx.moveTo(-w * 0.25, -h * 0.13); ctx.lineTo(-w * 0.16, -h * 0.44); ctx.lineTo(0, -h * 0.44); ctx.lineTo(0, -h * 0.13); ctx.fill();
      ctx.beginPath(); ctx.moveTo(w * 0.03, -h * 0.13); ctx.lineTo(w * 0.03, -h * 0.44); ctx.lineTo(w * 0.18, -h * 0.44); ctx.lineTo(w * 0.29, -h * 0.13); ctx.fill();
      ctx.fillStyle = '#111827';
      for (const dx of [-0.3, 0.3]) { ctx.beginPath(); ctx.arc(dx * w, h * 0.35, h * 0.2, 0, Math.PI * 2); ctx.fill(); }
      ctx.fillStyle = '#9CA3AF';
      for (const dx of [-0.3, 0.3]) { ctx.beginPath(); ctx.arc(dx * w, h * 0.35, h * 0.09, 0, Math.PI * 2); ctx.fill(); }
      ctx.fillStyle = '#FDE68A'; ctx.fillRect(w * 0.46, h * 0.02, w * 0.04, h * 0.08);
    },
  },
  rock: {
    size: [0.6, 0.45], draw(ctx, w, h) {
      ctx.fillStyle = '#9CA3AF';
      ctx.beginPath(); ctx.moveTo(-w / 2, h / 2); ctx.lineTo(-w * 0.4, -h * 0.2); ctx.lineTo(-w * 0.05, -h / 2); ctx.lineTo(w * 0.35, -h * 0.3); ctx.lineTo(w / 2, h / 2); ctx.fill();
      ctx.fillStyle = 'rgba(255,255,255,0.2)'; ctx.beginPath(); ctx.moveTo(-w * 0.4, -h * 0.2); ctx.lineTo(-w * 0.05, -h / 2); ctx.lineTo(0, 0); ctx.fill();
    },
  },
  coin: {
    size: [0.03, 0.03], draw(ctx, w) {
      ctx.fillStyle = '#F59E0B'; ctx.beginPath(); ctx.arc(0, 0, w / 2, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#FCD34D'; ctx.beginPath(); ctx.arc(0, 0, w * 0.36, 0, Math.PI * 2); ctx.fill();
    },
  },
};

/** Estado do objeto no tempo t. `upm`: unidades do mundo por metro. */
export function objectState(o, t, upm) {
  const asset = ASSETS[o.asset] || ASSETS.crate;
  const [wm, hm] = o.size || asset.size;
  const w = wm * upm * (o.scale || 1);
  const h = hm * upm * (o.scale || 1);
  const s = { x: o.x, y: o.y, angle: o.angle || 0, scale: 1, opacity: o.visible === false ? 0 : 1, vx: 0, vy: 0,
              w, h, landedAt: null, broken: false };
  for (const a of [...(o.actions || [])].sort((p, q) => p.start - q.start)) {
    if (t < a.start) {
      if (a.type === 'appear') s.opacity = 0;
      continue;
    }
    const k = t - a.start;
    const dur = Math.max(0.01, (a.end ?? a.start + (a.dur ?? 0.5)) - a.start);
    if (a.type === 'appear') {
      const p = window01(k, 0, dur, 'back');
      s.opacity = clamp(k / (dur * 0.6));
      if ((a.style || 'pop') === 'pop') s.scale = lerp(0.3, 1, p);
      if (a.style === 'drop') s.y = lerp(o.y - 1.5 * upm, o.y, ease('out', k / dur));
    } else if (a.type === 'vanish') {
      s.opacity = 1 - clamp(k / dur);
    } else if (a.type === 'fall') {
      const ground = (a.ground_y ?? 0) - h / 2;
      const f = fall(k * (a.time_scale || 1), { y0: s.y, groundY: ground, upm, g: a.g, bounce: a.bounce ?? 0.15,
                                                rotate: a.spin ?? 0.6 });
      s.y = f.y; s.vy = f.vy * (a.time_scale || 1); s.angle += f.angle;
      if (f.landed) { s.landedAt = a.start + f.tImpact / (a.time_scale || 1); s.broken = a.breaks !== false; }
      s.tImpact = a.start + f.tImpact / (a.time_scale || 1);
    } else if (a.type === 'move') {
      const p = window01(k, 0, dur, a.ease || 'inOut');
      const nx = lerp(s.x, a.to_x ?? s.x, p);
      const ny = lerp(s.y, a.to_y ?? s.y, p);
      if (k < dur) { s.vx = ((a.to_x ?? s.x) - s.x) / dur; s.vy = ((a.to_y ?? s.y) - s.y) / dur; }
      s.x = nx; s.y = ny;
    } else if (a.type === 'rotate') {
      s.angle += (a.turns ?? 1) * Math.PI * 2 * ease(a.ease || 'inOut', k / dur);
    } else if (a.type === 'wobble') {
      if (k < dur || a.hold) s.angle += pendulum(k, { amplitude: a.amplitude ?? 0.08, period: a.period ?? 0.9 });
    } else if (a.type === 'shake') {
      if (k < dur) {
        const i = (a.intensity ?? 0.04) * upm * (1 - k / dur);
        s.x += noise1(o.id + 'sx', k * 30) * i; s.y += noise1(o.id + 'sy', k * 30) * i * 0.5;
      }
    }
  }
  return s;
}

export function drawObject(ctx, o, t, upm) {
  const s = objectState(o, t, upm);
  if (s.opacity <= 0) return s;
  const asset = ASSETS[o.asset] || ASSETS.crate;
  // sombra no chão: cresce e escurece conforme o objeto se aproxima (a pista de altura mais legível)
  if (o.shadow !== false && o.asset !== 'bracket') {
    const height = Math.max(0, -(s.y + s.h / 2));
    const near = 1 - clamp(height / (12 * upm));
    ctx.save();
    ctx.globalAlpha = s.opacity * (0.08 + 0.22 * near);
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.ellipse(s.x, 4, s.w * (0.35 + 0.35 * near), s.w * 0.08 * (0.6 + near), 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }
  ctx.save();
  ctx.globalAlpha = s.opacity;
  if (o.pivot === 'top') {
    ctx.translate(s.x, s.y - s.h / 2); ctx.rotate(s.angle); ctx.translate(0, s.h / 2);
  } else {
    ctx.translate(s.x, s.y); ctx.rotate(s.angle);
  }
  ctx.scale(s.scale, s.scale);
  asset.draw(ctx, s.w, s.h, o);
  if (s.broken) {
    // amassado e rachaduras depois do impacto
    ctx.strokeStyle = 'rgba(17,24,39,0.7)'; ctx.lineWidth = s.w * 0.015;
    const r = rng(o.id + 'crack');
    for (let i = 0; i < 4; i++) {
      ctx.beginPath(); let x = (r() - 0.5) * s.w * 0.6, y = -s.h / 2;
      ctx.moveTo(x, y);
      for (let j = 0; j < 4; j++) { x += (r() - 0.5) * s.w * 0.2; y += s.h * 0.22; ctx.lineTo(x, y); }
      ctx.stroke();
    }
  }
  ctx.restore();
  if (s.broken && s.landedAt != null) {
    // peças soltas que saltam no impacto
    const k = t - s.landedAt;
    const r = rng(o.id + 'debris');
    ctx.fillStyle = shade(o.color || '#D1D5DB', -0.1);
    for (let i = 0; i < 9; i++) {
      const vx = (r() - 0.5) * 6 * upm, vy = -(2 + r() * 3) * upm;
      const tt = Math.min(k, (2 * -vy) / (9.81 * upm));
      const x = s.x + vx * tt, y = Math.min(0, s.y + s.h / 2 + vy * tt + 4.9 * upm * tt * tt) - 0.04 * upm;
      ctx.save(); ctx.translate(x, y); ctx.rotate(r() * 6 + tt * 8);
      ctx.fillRect(-0.04 * upm, -0.025 * upm, 0.08 * upm, 0.05 * upm); ctx.restore();
    }
  }
  return s;
}

export { invLerp };
