// Elementos informativos desenhados na tela (coordenadas de design 1080×1920). Os que seguem um alvo projetam a
// posição do mundo na tela a cada quadro. Cada um registra a área ocupada para as legendas desviarem.
import { DESIGN } from './camera.js';
import { clamp, ease, lerp, roundRect, window01 } from './util.js';

export const FONT = { display: 'SPDisplay, Anton, Impact, sans-serif', body: 'SPBody, Montserrat, Arial, sans-serif' };

export function project(cam, x, y) {
  return { x: DESIGN.W / 2 + cam.shakeX / cam.base + (x - cam.x) * cam.zoom,
           y: DESIGN.H / 2 + cam.shakeY / cam.base + (y - cam.y) * cam.zoom };
}

const fmt = (v, decimals, locale) => v.toLocaleString(locale || 'pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });

function pill(ctx, x, y, text, { size = 46, bg = 'rgba(15,23,42,0.88)', fg = '#FFFFFF', accent, icon } = {}) {
  ctx.font = `800 ${size}px ${FONT.body}`;
  const tw = ctx.measureText(text).width + (icon ? size * 0.9 : 0);
  const w = tw + size * 0.9;
  const h = size * 1.55;
  ctx.fillStyle = bg;
  roundRect(ctx, x, y - h / 2, w, h, h / 2); ctx.fill();
  if (accent) { ctx.fillStyle = accent; roundRect(ctx, x, y - h / 2, size * 0.28, h, size * 0.14); ctx.fill(); }
  ctx.fillStyle = fg;
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'left';
  if (icon) { ctx.fillStyle = accent || fg; ctx.fillText(icon, x + size * 0.5, y + 2); ctx.fillStyle = fg; }
  ctx.fillText(text, x + size * 0.5 + (icon ? size * 0.9 : 0), y + 2);
  return { x, y: y - h / 2, w, h };
}

function appearAlpha(o, t) {
  const fadeIn = window01(t, o.start, 0.25, 'out');
  const fadeOut = o.end != null ? 1 - window01(t, o.end - 0.2, 0.2, 'in') : 1;
  return fadeIn * fadeOut;
}

export function drawOverlay(ctx, o, t, cam, resolve, upm, theme, boxes) {
  if (t < o.start || (o.end != null && t > o.end)) return;
  const alpha = appearAlpha(o, t);
  const pop = lerp(0.85, 1, ease('back', clamp((t - o.start) / 0.3)));
  const accent = o.color || theme.accent;
  ctx.save();
  ctx.globalAlpha = alpha;
  const target = o.target ? resolve(o.target, t) : null;
  const anchor = target ? project(cam, target.x, target.y) : { x: o.x ?? DESIGN.W / 2, y: o.y ?? DESIGN.H * 0.3 };
  const side = o.side || (anchor.x > DESIGN.W * 0.6 ? 'left' : 'right');
  const off = (target ? (target.w || 0.5 * upm) * cam.zoom * 0.6 : 0) + 40;
  const bx = clamp(side === 'right' ? anchor.x + off : anchor.x - off - 330, 60, DESIGN.W - 420);
  const by = clamp(anchor.y + (o.dy || 0), 260, DESIGN.H * 0.78);

  if (o.type === 'speed' && target) {
    const v = Math.hypot(target.vx || 0, target.vy || 0) / upm;
    const value = o.unit === 'm/s' ? v : v * 3.6;
    boxes.push(pill(ctx, bx, by, `${fmt(value, 0, theme.locale)} ${o.unit || 'km/h'}`,
                    { accent, icon: (target.vy || 0) > 0.1 ? '▼' : '►' }));
    if (o.label) {
      ctx.font = `800 34px ${FONT.body}`; ctx.fillStyle = '#FFFFFF'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.strokeStyle = 'rgba(15,23,42,0.9)'; ctx.lineWidth = 9; ctx.lineJoin = 'round';
      ctx.strokeText(o.label.toUpperCase(), bx + 10, by - 68); ctx.fillText(o.label.toUpperCase(), bx + 10, by - 68);
    }
  } else if (o.type === 'distance' && target) {
    // régua vertical do alvo até o chão, com a distância restante em metros
    const ground = project(cam, target.x, o.ground_y ?? 0);
    const top = project(cam, target.x, target.y + (target.h || 0) / 2);
    const lx = clamp(top.x + (side === 'right' ? -1 : 1) * ((target.w || upm) * cam.zoom * 0.7 + 30), 40, DESIGN.W - 40);
    ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 5; ctx.setLineDash([16, 12]);
    ctx.beginPath(); ctx.moveTo(lx, top.y); ctx.lineTo(lx, Math.min(ground.y, DESIGN.H + 50)); ctx.stroke();
    ctx.setLineDash([]);
    for (const yy of [top.y, ground.y]) { ctx.beginPath(); ctx.moveTo(lx - 18, yy); ctx.lineTo(lx + 18, yy); ctx.stroke(); }
    const meters = Math.max(0, ((o.ground_y ?? 0) - (target.y + (target.h || 0) / 2)) / upm);
    const my = clamp((top.y + Math.min(ground.y, DESIGN.H * 0.75)) / 2, 300, DESIGN.H * 0.75);
    boxes.push(pill(ctx, side === 'right' ? lx - 250 : lx + 24, my, `${fmt(meters, 1, theme.locale)} m`, { accent: theme.accent2 || accent, size: 40 }));
  } else if (o.type === 'timer') {
    const stop = o.stop_at ?? o.end ?? t;
    const secs = Math.max(0, Math.min(t, stop) - (o.since ?? o.start));
    boxes.push(pill(ctx, o.x ?? 80, o.y ?? 320, `⏱ ${fmt(secs, 1, theme.locale)} s`, { accent, size: 50 }));
  } else if (o.type === 'counter') {
    const p = window01(t, o.start, (o.dur ?? 1.2), 'out');
    const value = lerp(o.from ?? 0, o.to ?? 0, p);
    ctx.textAlign = 'center';
    ctx.font = `900 ${o.size || 120}px ${FONT.display}`;
    ctx.lineWidth = 14; ctx.strokeStyle = 'rgba(15,23,42,0.9)'; ctx.fillStyle = accent;
    const x = o.x ?? DESIGN.W / 2, y = o.y ?? DESIGN.H * 0.32;
    const text = `${o.prefix || ''}${fmt(value, o.decimals ?? 0, theme.locale)}${o.suffix || ''}`;
    ctx.save(); ctx.translate(x, y); ctx.scale(pop, pop);
    ctx.strokeText(text, 0, 0); ctx.fillText(text, 0, 0);
    if (o.label) { ctx.font = `800 40px ${FONT.body}`; ctx.fillStyle = '#FFFFFF'; ctx.lineWidth = 9; ctx.strokeText(o.label, 0, 70); ctx.fillText(o.label, 0, 70); }
    ctx.restore();
    boxes.push({ x: x - 360, y: y - 120, w: 720, h: 220 });
  } else if (o.type === 'callout') {
    ctx.font = `750 40px ${FONT.body}`;
    const lines = wrap(ctx, o.text || '', 560);
    const w = Math.max(...lines.map((l) => ctx.measureText(l).width)) + 64;
    const h = lines.length * 52 + 40;
    const x = clamp(target ? (side === 'right' ? anchor.x + off : anchor.x - off - w) : (o.x ?? DESIGN.W / 2) - w / 2,
                    60, DESIGN.W - w - 130);
    const y = target ? clamp(by - h - 60, 240, DESIGN.H * 0.7) : (o.y ?? DESIGN.H * 0.25);
    if (target) {
      ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 4;
      ctx.beginPath(); ctx.moveTo(anchor.x, anchor.y); ctx.lineTo(x + (side === 'right' ? 0 : w), y + h / 2); ctx.stroke();
      ctx.fillStyle = '#FFFFFF'; ctx.beginPath(); ctx.arc(anchor.x, anchor.y, 9, 0, Math.PI * 2); ctx.fill();
    }
    ctx.save(); ctx.translate(x + w / 2, y + h / 2); ctx.scale(pop, pop); ctx.translate(-w / 2, -h / 2);
    ctx.fillStyle = 'rgba(255,255,255,0.96)'; roundRect(ctx, 0, 0, w, h, 26); ctx.fill();
    ctx.fillStyle = accent; roundRect(ctx, 0, 0, 12, h, 6); ctx.fill();
    ctx.fillStyle = '#0F172A'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    lines.forEach((l, i) => ctx.fillText(l, 34, 22 + i * 52));
    ctx.restore();
    boxes.push({ x, y, w, h });
  } else if (o.type === 'highlight' && target) {
    const r = (o.radius || Math.max(target.w || 0, target.h || 0, 0.6 * upm) * 0.75) * cam.zoom;
    const pulse = 1 + Math.sin((t - o.start) * 6) * 0.05;
    ctx.strokeStyle = accent; ctx.lineWidth = 8;
    ctx.beginPath(); ctx.arc(anchor.x, anchor.y, r * pulse * pop, 0, Math.PI * 2); ctx.stroke();
    boxes.push({ x: anchor.x - r * 1.1, y: anchor.y - r * 1.1, w: r * 2.2, h: r * 2.2 });
  } else if (o.type === 'arrow') {
    const from = o.from?.target ? project(cam, resolve(o.from.target, t).x, resolve(o.from.target, t).y) : (o.from || anchor);
    const toT = o.to?.target ? resolve(o.to.target, t) : null;
    const to = toT ? project(cam, toT.x, toT.y) : (o.to || { x: anchor.x, y: anchor.y + 200 });
    const p = window01(t, o.start, o.dur ?? 0.5, 'out');
    const ex = lerp(from.x, to.x, p), ey = lerp(from.y, to.y, p);
    ctx.strokeStyle = accent; ctx.fillStyle = accent; ctx.lineWidth = 12; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(ex, ey); ctx.stroke();
    const ang = Math.atan2(ey - from.y, ex - from.x);
    ctx.beginPath(); ctx.moveTo(ex + Math.cos(ang) * 22, ey + Math.sin(ang) * 22);
    ctx.lineTo(ex + Math.cos(ang + 2.5) * 34, ey + Math.sin(ang + 2.5) * 34);
    ctx.lineTo(ex + Math.cos(ang - 2.5) * 34, ey + Math.sin(ang - 2.5) * 34); ctx.fill();
    if (o.label) pill(ctx, clamp(ex + 30, 60, DESIGN.W - 380), ey, o.label, { size: 36, accent });
  } else if (o.type === 'title') {
    // título de gancho no topo, com a palavra entre [colchetes] destacada
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.font = `400 ${o.size || 92}px ${FONT.display}`;
    const y = o.y ?? DESIGN.H * 0.17;
    const lines = wrap(ctx, (o.text || '').toUpperCase(), 900);
    ctx.save(); ctx.translate(DESIGN.W / 2, y); ctx.scale(pop, pop);
    lines.forEach((line, i) => {
      const yy = (i - (lines.length - 1) / 2) * (o.size || 92) * 1.08;
      drawMarked(ctx, line, 0, yy, accent);
    });
    ctx.restore();
    boxes.push({ x: 60, y: y - lines.length * 55 - 20, w: DESIGN.W - 120, h: lines.length * 110 + 40 });
  } else if (o.type === 'bars') {
    const items = o.items || [];
    const max = Math.max(...items.map((i) => i.value), 1e-9);
    // sempre centrado e largo o bastante para o rótulo e o valor; `y` escolhe a altura
    const x0 = 100, y0 = clamp(o.y ?? DESIGN.H * 0.24, DESIGN.H * 0.13, DESIGN.H * 0.62), bw = DESIGN.W - x0 * 2 - 40;
    items.forEach((it, i) => {
      const p = window01(t, o.start + i * 0.25, 0.7, 'out');
      const yy = y0 + i * 112;
      ctx.fillStyle = 'rgba(15,23,42,0.75)'; roundRect(ctx, x0, yy, bw, 88, 20); ctx.fill();
      ctx.fillStyle = it.color || accent; roundRect(ctx, x0, yy, Math.max(40, bw * (it.value / max) * p), 88, 20); ctx.fill();
      ctx.fillStyle = '#FFFFFF'; ctx.font = `800 38px ${FONT.body}`; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText(it.label, x0 + 26, yy + 46);
      ctx.textAlign = 'right';
      ctx.fillText(`${fmt(it.value * p, it.decimals ?? 0, theme.locale)}${o.unit ? ' ' + o.unit : ''}`, x0 + bw - 26, yy + 46);
    });
    boxes.push({ x: x0, y: y0, w: bw, h: items.length * 112 });
  }
  ctx.restore();
}

export function wrap(ctx, text, maxW) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? cur + ' ' + w : w;
    if (ctx.measureText(next.replace(/[[\]]/g, '')).width > maxW && cur) { lines.push(cur); cur = w; } else cur = next;
  }
  if (cur) lines.push(cur);
  return lines;
}

/** Texto com contorno em que [palavra] sai na cor de destaque. */
export function drawMarked(ctx, line, x, y, accent) {
  const parts = line.split(/(\[[^\]]+\])/).filter(Boolean);
  const plain = parts.map((p) => p.replace(/[[\]]/g, ''));
  const total = ctx.measureText(plain.join('')).width;
  let cx = x - total / 2;
  ctx.textAlign = 'left';
  ctx.lineJoin = 'round';
  parts.forEach((p, i) => {
    const txt = plain[i];
    ctx.lineWidth = 16; ctx.strokeStyle = 'rgba(15,23,42,0.95)'; ctx.strokeText(txt, cx, y);
    ctx.fillStyle = p.startsWith('[') ? accent : '#FFFFFF'; ctx.fillText(txt, cx, y);
    cx += ctx.measureText(txt).width;
  });
}
