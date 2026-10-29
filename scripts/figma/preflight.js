// [SKILL 3단계 사전 점검] 읽기 전용. 원본 템플릿 구조, 대상 페이지 중복, 폰트를 확인하고 Page 1 서명을 기록합니다.
const tpl = findPageByName(INPUT.templatePage);
if (!tpl) throw new Error(`템플릿 페이지 '${INPUT.templatePage}'가 없습니다`);
await figma.setCurrentPageAsync(tpl);

const problems = [];
const usedFonts = new Map();
const frames = {};
for (const name of INPUT.frames) {
  let fr;
  try { fr = findOneFrame(tpl, name); } catch (e) { problems.push(e.message); continue; }
  if (Math.round(fr.width) !== INPUT.frameSize.w || Math.round(fr.height) !== INPUT.frameSize.h) {
    problems.push(`${name}: 크기 ${Math.round(fr.width)}x${Math.round(fr.height)} (예상 ${INPUT.frameSize.w}x${INPUT.frameSize.h})`);
  }
  const expected = Object.keys(INPUT.layers);
  if (fr.children.length !== expected.length) problems.push(`${name}: 레이어 ${fr.children.length}개 (예상 ${expected.length}개)`);
  const layers = {};
  for (const [lname, ltype] of Object.entries(INPUT.layers)) {
    try {
      const node = findOneLayer(fr, lname, ltype);
      layers[lname] = node.id;
      if (node.type === 'TEXT' && ['title', 'body', 'source'].includes(lname)) {
        for (const seg of node.getStyledTextSegments(['fontName'])) usedFonts.set(`${seg.fontName.family}|${seg.fontName.style}`, seg.fontName);
      }
      // fill-text의 줄 수·겹침 검사는 너비 고정 + 높이 자동(HEIGHT)일 때만 의미가 있습니다.
      if (['title', 'body'].includes(lname) && node.textAutoResize !== 'HEIGHT') {
        problems.push(`${name}/${lname}: 텍스트 크기 조절이 ${node.textAutoResize}입니다 (HEIGHT여야 레이아웃 검사가 가능)`);
      }
      // 자리표시 제목이 1줄 높이가 아니면 템플릿 폰트·크기가 바뀐 것이므로 layers.md 6장을 다시 측정해야 합니다.
      if (lname === 'title' && node.height > INPUT.layout.titleLineHeight * 1.5) {
        problems.push(`${name}/title: 자리표시 제목 높이 ${Math.round(node.height)} > 1줄 기준 ${INPUT.layout.titleLineHeight} (템플릿 변경 여부 확인 필요)`);
      }
    } catch (e) { problems.push(e.message); }
  }
  frames[name] = { id: fr.id, layers };
}

const available = new Set((await figma.listAvailableFontsAsync()).map(f => `${f.fontName.family}|${f.fontName.style}`));
const missingFonts = [...usedFonts.keys()].filter(k => !available.has(k));
if (missingFonts.length) problems.push(`사용할 수 없는 폰트: ${missingFonts.join(', ')}`);

const targetExists = !!findPageByName(INPUT.pageName);
return {
  ok: problems.length === 0 && !targetExists,
  targetPage: INPUT.pageName,
  targetExists,
  problems,
  fonts: [...usedFonts.keys()],
  templateFrames: frames,
  page1Signature: pageSignature(tpl),
};
