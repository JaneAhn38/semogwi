// fill-figma 공통 함수. scripts/fill_figma.py render가 각 단계 코드 앞에 붙입니다.
// INPUT은 render가 slides.json으로 만든 값입니다 (직접 수정하지 않음).

function findPageByName(name) {
  const pages = figma.root.children.filter(p => p.name === name);
  if (pages.length > 1) throw new Error(`같은 이름의 페이지가 ${pages.length}개 있습니다: ${name}`);
  return pages[0] || null;
}

function findOneFrame(page, name) {
  const found = page.children.filter(n => n.type === 'FRAME' && n.name === name);
  if (found.length !== 1) throw new Error(`${page.name}: 프레임 '${name}'이 ${found.length}개입니다 (1개여야 함)`);
  return found[0];
}

function findOneLayer(frame, name, type) {
  const found = frame.children.filter(c => c.name === name);
  if (found.length !== 1) throw new Error(`${frame.name}: 레이어 '${name}'이 ${found.length}개입니다 (1개여야 함)`);
  if (type && found[0].type !== type) throw new Error(`${frame.name}/${name}: 타입이 ${found[0].type}입니다 (예상 ${type})`);
  return found[0];
}

function fillTypes(node) {
  if (!('fills' in node)) return '';
  if (node.fills === figma.mixed) return 'mixed';
  return node.fills.map(f => `${f.type}${f.scaleMode ? ':' + f.scaleMode : ''}${f.imageHash ? ':' + f.imageHash : ''}${f.visible === false ? ':hidden' : ''}`).join(',');
}

// 페이지 전체의 이름·타입·위치·크기·채우기·텍스트·표시 여부를 문자열로 만들어 해시합니다.
// 원본 Page 1이 작업 전후로 같은지 비교하는 데 씁니다.
function pageSignature(page) {
  const parts = [];
  const r = v => Math.round(v * 100) / 100;
  for (const top of page.children) {
    const nodes = [top].concat('findAll' in top ? top.findAll(() => true) : []);
    for (const n of nodes) {
      parts.push([n.id, n.type, n.name, n.visible, r(n.x), r(n.y), r(n.width), r(n.height), fillTypes(n), n.type === 'TEXT' ? n.characters : ''].join('|'));
    }
  }
  const s = parts.join('\n');
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 33) ^ s.charCodeAt(i)) >>> 0;
  return { hash: h.toString(16), nodeCount: parts.length };
}

function bounds(n) {
  return { x: Math.round(n.x), y: Math.round(n.y), w: Math.round(n.width), h: Math.round(n.height), right: Math.round(n.x + n.width), bottom: Math.round(n.y + n.height) };
}
