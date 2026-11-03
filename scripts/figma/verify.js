// [SKILL 7단계 결과 검증] 읽기 전용. 이미지 교체까지 끝난 새 페이지가 slides.json과 일치하는지 확인하고,
// PNG로 내보낼 프레임 ID를 돌려줍니다.
const page = findPageByName(INPUT.pageName);
if (!page) throw new Error(`대상 페이지가 없습니다: ${INPUT.pageName}`);
await figma.setCurrentPageAsync(page);

const problems = [];
const exportFrames = [];
for (const s of INPUT.slides) {
  const fr = findOneFrame(page, s.frame);
  const expected = Object.keys(INPUT.layers);
  if (fr.children.length !== expected.length) problems.push(`${s.frame}: 레이어 ${fr.children.length}개 (예상 ${expected.length}개)`);
  for (const [lname, ltype] of Object.entries(INPUT.layers)) {
    try { findOneLayer(fr, lname, ltype); } catch (e) { problems.push(e.message); }
  }
  const title = findOneLayer(fr, 'title', 'TEXT');
  const body = findOneLayer(fr, 'body', 'TEXT');
  const source = findOneLayer(fr, 'source', 'TEXT');
  const img = findOneLayer(fr, 'main-image');
  if (title.characters !== s.title) problems.push(`${s.frame}: title이 slides.json과 다릅니다`);
  if (body.characters.replace(/\r/g, '') !== s.body) problems.push(`${s.frame}: body가 slides.json과 다릅니다`);
  if (s.source) {
    if (!source.visible || source.characters !== s.source) problems.push(`${s.frame}: source가 slides.json과 다르거나 숨겨져 있습니다`);
  } else if (source.visible) problems.push(`${s.frame}: 빈 source인데 레이어가 보입니다`);
  const fills = img.fills === figma.mixed ? [] : img.fills;
  const imageFill = fills.find(f => f.type === 'IMAGE');
  if (s.hasImage) {
    if (!imageFill) problems.push(`${s.frame}: main-image에 이미지가 없습니다`);
    else if (imageFill.scaleMode !== 'FIT') problems.push(`${s.frame}: main-image 맞춤 방식이 ${imageFill.scaleMode}입니다 (FIT이어야 함)`);
    if (img.name !== 'main-image') problems.push(`${s.frame}: main-image 레이어 이름이 바뀌었습니다`);
  } else if (imageFill) problems.push(`${s.frame}: 이미지가 없어야 하는데 main-image에 이미지가 있습니다`);
  exportFrames.push({ frame: s.frame, id: fr.id, w: Math.round(fr.width), h: Math.round(fr.height) });
}
return { ok: problems.length === 0, pageId: page.id, problems, exportFrames };
