// Renderiza um trecho do JSON de animação no Chromium headless e envia os quadros direto ao ffmpeg.
//   node animate.mjs <spec.json> <saida.mp4> [--from S] [--to S] [--width W] [--height H] [--fps N] [--crf N]
//   node animate.mjs <spec.json> <quadro.jpg> --still S
// Os quadros são função pura do tempo: o mesmo trecho sai idêntico em qualquer execução.
import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const [specFile, out, ...rest] = process.argv.slice(2);
const opt = {};
for (let i = 0; i < rest.length; i += 2) opt[rest[i].replace(/^--/, '')] = rest[i + 1];
const spec = JSON.parse(await readFile(specFile, 'utf8'));
const fps = Number(opt.fps || spec.fps || 30);
const width = Number(opt.width || spec.width || 1080);
const height = Number(opt.height || spec.height || 1920);

// fontes viram data URLs (a página não acessa o disco)
const MIME = { '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2', '.woff': 'font/woff' };
for (const [name, path] of Object.entries(spec.fonts || {})) {
  if (!path.startsWith('data:')) {
    spec.fonts[name] = `data:${MIME[extname(path)] || 'font/ttf'};base64,` + (await readFile(path)).toString('base64');
  }
}

const browser = await chromium.launch({
  executablePath: process.env.SHORTPIPELINE_CHROMIUM || undefined,
  args: spec.scenes.some((scene) => scene.layer_3d?.objects.length)
    ? ['--use-gl=angle', '--use-angle=swiftshader']
    : [],
});
let ffmpeg;
try {
  const page = await browser.newPage();
  await page.route('**/*', (route) => route.request().url() === 'http://shortpipeline.local/'
    ? route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><body style="margin:0"></body></html>' })
    : route.abort());
  await page.goto('http://shortpipeline.local/');
  await page.addScriptTag({ path: fileURLToPath(new URL('./dist/engine.js', import.meta.url)) });
  const info = await page.evaluate(([s, w, h]) => window.SPEngine.init(s, { width: w, height: h }), [spec, width, height]);

  if (opt.still !== undefined) {
    const { jpeg } = await page.evaluate((t) => window.SPEngine.frameJPEG(t, 0.95), Number(opt.still));
    await writeFile(out, Buffer.from(jpeg, 'base64'));
  } else {
    // --f0/--f1: quadros exatos (cenas renderizadas separadas somam exatamente os quadros do vídeo)
    const f0 = opt.f0 !== undefined ? Number(opt.f0) : Math.round(Number(opt.from || 0) * fps);
    const f1 = opt.f1 !== undefined ? Number(opt.f1) : Math.round(Math.min(Number(opt.to || info.duration), info.duration) * fps);
    const from = f0 / fps;
    const to = f1 / fps;
    const frames = Math.max(1, f1 - f0);
    ffmpeg = spawn(process.env.FFMPEG || 'ffmpeg', [
      '-y', '-hide_banner', '-v', 'error', '-f', 'image2pipe', '-c:v', 'mjpeg', '-framerate', String(fps), '-i', '-',
      '-c:v', 'libx264', '-preset', opt.preset || 'veryfast', '-crf', String(opt.crf || 18),
      '-pix_fmt', 'yuv420p', '-r', String(fps), '-an', out,
    ], { stdio: ['pipe', 'inherit', 'inherit'] });
    const done = new Promise((resolve, reject) => ffmpeg.on('close', (code) => (code ? reject(new Error(`ffmpeg saiu com ${code}`)) : resolve())));
    const quality = Number(opt.quality || 0.9);
    for (let i = 0; i < frames; i++) {
      const t = from + i / fps;
      const { jpeg } = await page.evaluate(([tt, q]) => window.SPEngine.frameJPEG(tt, q), [t, quality]);
      if (!ffmpeg.stdin.write(Buffer.from(jpeg, 'base64'))) await new Promise((r) => ffmpeg.stdin.once('drain', r));
    }
    ffmpeg.stdin.end();
    await done;
    process.stdout.write(JSON.stringify({ frames, from, to }) + '\n');
  }
} finally {
  await browser.close();
}
