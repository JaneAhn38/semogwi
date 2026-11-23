// 데이터(JSON)를 템플릿에 채워서 1080×1350 PNG로 저장하는 예시 스크립트
//
// 설치:  npm i playwright   (브라우저가 없으면: npx playwright install chromium)
// 실행:  node render-png.mjs examples/popup-sample.json out/
//
// 데이터 형식은 examples/popup-sample.json 참고:
// { accent, cards: { "<템플릿 파일 이름>": { text: {...}, images: {...} } } }

import { chromium } from 'playwright';
import { readFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const [dataPath, outDir = 'out'] = process.argv.slice(2);
if (!dataPath) {
  console.error('사용법: node render-png.mjs <데이터.json> [출력폴더]');
  process.exit(1);
}

const data = JSON.parse(await readFile(dataPath, 'utf8'));
const fillJs = await readFile(path.join(here, 'fill.js'), 'utf8');
await mkdir(outDir, { recursive: true });

// 시스템 크롬을 쓰려면: CHROME_PATH=/usr/bin/google-chrome node render-png.mjs ...
const browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {});
const page = await browser.newPage({ viewport: { width: 1080, height: 1350 }, deviceScaleFactor: Number(process.env.SCALE || 1) });

let problems = 0;
for (const [name, card] of Object.entries(data.cards)) {
  const file = path.join(here, 'templates', `${name}.html`);
  await page.goto(pathToFileURL(file).href);
  await page.addScriptTag({ content: fillJs });
  // 로컬 이미지 경로는 file:// URL로 바꿔서 넘김
  const images = Object.fromEntries(Object.entries(card.images || {}).map(([k, v]) =>
    [k, /^(https?:|data:|file:)/.test(v) ? v : pathToFileURL(path.resolve(path.dirname(dataPath), v)).href]));
  const report = await page.evaluate(({ card, images, accent }) =>
    window.SemogwiTemplates.fillCard(document, { ...card, images, accent }), { card, images, accent: data.accent });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForLoadState('networkidle');
  const out = path.join(outDir, `${name}.png`);
  await page.screenshot({ path: out });
  const warn = [...report.missingText.map((k) => `글자 '${k}'`), ...report.missingImages.map((k) => `이미지 '${k}'`)];
  if (report.unknownKeys.length) warn.push(`템플릿에 없는 키: ${report.unknownKeys.join(', ')}`);
  if (warn.length) problems++;
  console.log(`${out}${warn.length ? '  ⚠ 빈 자리: ' + warn.join(', ') : '  ✓'}`);
}
await browser.close();
if (problems) console.log(`\n${problems}장에 비어 있는 자리가 있어요. 위 목록을 확인하세요.`);
