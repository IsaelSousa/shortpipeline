import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const [specFile, frameDir] = process.argv.slice(2);
const spec = JSON.parse(await readFile(specFile, 'utf8'));
if (spec.image) {
  spec.image = 'data:image/jpeg;base64,' + (await readFile(spec.image)).toString('base64');
}

const browser = await chromium.launch(process.env.SHORTPIPELINE_CHROMIUM
  ? { executablePath: process.env.SHORTPIPELINE_CHROMIUM } : {});
try {
  const page = await browser.newPage();
  // Motion Canvas resolves image sources against the document's origin.
  await page.route('**/*', (route) => route.request().url() === 'http://shortpipeline.local/'
    ? route.fulfill({ contentType: 'text/html', body: '<!doctype html><html><body></body></html>' })
    : route.abort());
  await page.goto('http://shortpipeline.local/');
  await page.exposeFunction('saveFrame', (frame, jpeg) =>
    writeFile(join(frameDir, String(frame).padStart(6, '0') + '.jpg'), Buffer.from(jpeg, 'base64')));
  await page.addScriptTag({ path: fileURLToPath(new URL('./dist/scene.js', import.meta.url)) });
  await page.evaluate((settings) => window.renderScene(settings), spec);
} finally {
  await browser.close();
}
