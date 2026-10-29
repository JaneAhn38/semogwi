// [SKILL 4단계 복제] 쓰기. 새 페이지를 만들고 Page 1의 card-01 ~ card-05를 같은 위치로 복제합니다.
// 첫 쓰기 작업이므로 편집 권한도 여기서 확인됩니다. 실패하면 만든 것을 지우고 오류를 냅니다.
if (findPageByName(INPUT.pageName)) throw new Error(`대상 페이지가 이미 있습니다: ${INPUT.pageName} — 덮어쓰지 않도록 중단`);
const tpl = findPageByName(INPUT.templatePage);
if (!tpl) throw new Error(`템플릿 페이지 '${INPUT.templatePage}'가 없습니다`);
await figma.setCurrentPageAsync(tpl);
const originals = INPUT.frames.map(name => findOneFrame(tpl, name));
const page1ChildrenBefore = tpl.children.length;

const created = [];
let page = null;
try {
  page = figma.createPage();
  page.name = INPUT.pageName;
  for (const f of originals) {
    const c = f.clone();
    created.push(c);
    page.appendChild(c);
    c.x = f.x;
    c.y = f.y;
  }
} catch (e) {
  for (const c of created) { try { c.remove(); } catch (_) {} }
  if (page) { try { page.remove(); } catch (_) {} }
  throw e;
}
if (tpl.children.length !== page1ChildrenBefore) throw new Error(`Page 1 자식 수가 바뀌었습니다: ${page1ChildrenBefore} → ${tpl.children.length}`);

const frames = {};
for (const c of created) {
  frames[c.name] = { id: c.id, layers: Object.fromEntries(c.children.map(k => [k.name, k.id])) };
}
return { pageId: page.id, pageName: page.name, createdNodeIds: [page.id, ...created.map(c => c.id)], frames, page1Children: tpl.children.length };
