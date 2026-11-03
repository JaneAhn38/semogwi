// [SKILL 5단계 텍스트 교체] 쓰기. 새 페이지에서만 title / body / source 텍스트를 바꾸고, 빈 source는 숨깁니다.
// page-number, bottom-overlay, main-image, 배경은 건드리지 않으며, 작업 전후로 같은지 확인합니다.
// 교체 후 실제 Figma 레이아웃(겹침·넘침·줄 수)을 검사해 결과를 돌려줍니다.
const page = findPageByName(INPUT.pageName);
if (!page) throw new Error(`대상 페이지가 없습니다: ${INPUT.pageName}`);
if (page.name === INPUT.templatePage) throw new Error('원본 템플릿 페이지에는 쓰지 않습니다');
await figma.setCurrentPageAsync(page);

const L = INPUT.layout;
const fixedState = fr => ({
  frame: fillTypes(fr),
  pageNumber: (() => { const n = findOneLayer(fr, 'page-number', 'TEXT'); return `${n.characters}|${n.visible}|${JSON.stringify(bounds(n))}`; })(),
  overlay: (() => { const n = findOneLayer(fr, 'bottom-overlay'); return `${fillTypes(n)}|${n.visible}|${JSON.stringify(bounds(n))}`; })(),
  mainImage: (() => { const n = findOneLayer(fr, 'main-image'); return `${fillTypes(n)}|${n.visible}|${JSON.stringify(bounds(n))}`; })(),
});

// 대상 노드 확인 + 폰트 로드 (현재 노드가 쓰는 폰트 그대로)
const targets = INPUT.slides.map(s => {
  const fr = findOneFrame(page, s.frame);
  return { s, fr, title: findOneLayer(fr, 'title', 'TEXT'), body: findOneLayer(fr, 'body', 'TEXT'), source: findOneLayer(fr, 'source', 'TEXT') };
});
// 줄 수·겹침 검사는 너비 고정 + 높이 자동(HEIGHT)일 때만 의미가 있으므로, 어느 프레임도 바꾸기 전에 확인합니다.
for (const t of targets) for (const n of [t.title, t.body]) {
  if (n.textAutoResize !== 'HEIGHT') throw new Error(`${t.s.frame}/${n.name}: 텍스트 크기 조절이 ${n.textAutoResize}입니다 (HEIGHT여야 함) — 아무것도 바꾸지 않고 중단`);
}
const fonts = new Map();
for (const t of targets) for (const n of [t.title, t.body, t.source]) {
  for (const seg of n.getStyledTextSegments(['fontName'])) fonts.set(`${seg.fontName.family}|${seg.fontName.style}`, seg.fontName);
}
await Promise.all([...fonts.values()].map(f => figma.loadFontAsync(f)));

const mutatedNodeIds = [];
const report = [];
let errorCount = 0;
for (const { s, fr, title, body, source } of targets) {
  const before = fixedState(fr);
  // 템플릿 자리표시 제목(1줄)의 높이. preflight가 실측 1줄 높이의 1.5배 이하임을 확인해 둠
  const titleOneLineHeight = Math.min(title.height, L.titleLineHeight);

  title.characters = s.title;
  body.characters = s.body;
  if (s.source) { source.characters = s.source; source.visible = true; }
  else { source.visible = false; }
  mutatedNodeIds.push(title.id, body.id, source.id);

  const after = fixedState(fr);
  const tb = bounds(title), bb = bounds(body), sb = bounds(source), pb = bounds(findOneLayer(fr, 'page-number'));
  const bodyLines = Math.max(1, Math.round(body.height / L.bodyLineHeight));
  const errors = [], warnings = [];
  for (const k of Object.keys(before)) if (before[k] !== after[k]) errors.push(`고정 요소 변경됨: ${k}`);
  if (title.height > titleOneLineHeight + 1) errors.push(`title이 2줄 이상입니다 (높이 ${tb.h} > ${Math.round(titleOneLineHeight)})`);
  if (tb.bottom + L.minGap > bb.y) errors.push(`title 아래 끝 ${tb.bottom}이 body 위 끝 ${bb.y}에 너무 가깝거나 겹칩니다 (최소 간격 ${L.minGap})`);
  if (bb.bottom > fr.height - L.bottomMargin) errors.push(`body 아래 끝 ${bb.bottom}이 하단 여백을 침범합니다 (한계 ${fr.height - L.bottomMargin})`);
  if (tb.right > fr.width || bb.right > fr.width) errors.push('텍스트가 프레임 너비를 넘습니다');
  if (source.visible && sb.right + L.sideGap > pb.x) errors.push(`source 오른쪽 끝 ${sb.right}이 page-number(${pb.x})와 겹치거나 너무 가깝습니다`);
  if (bodyLines > L.bodyMaxLines) warnings.push(`body가 ${bodyLines}줄입니다 (권장 ${L.bodyMaxLines}줄 이하)`);
  errorCount += errors.length;
  report.push({ frame: s.frame, frameId: fr.id, title: tb, body: { ...bb, lines: bodyLines }, source: { ...sb, visible: source.visible }, errors, warnings });
}
return { ok: errorCount === 0, pageId: page.id, mutatedNodeIds, fontsLoaded: [...fonts.keys()], report };
