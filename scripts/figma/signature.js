// [SKILL 11단계 원본 보존 확인] 읽기 전용. 원본 Page 1의 서명을 다시 계산합니다.
// preflight에서 받은 page1Signature.hash와 같아야 원본이 바뀌지 않은 것입니다.
const tpl = findPageByName(INPUT.templatePage);
if (!tpl) throw new Error(`템플릿 페이지 '${INPUT.templatePage}'가 없습니다`);
await figma.setCurrentPageAsync(tpl);
return { page: tpl.name, page1Signature: pageSignature(tpl) };
