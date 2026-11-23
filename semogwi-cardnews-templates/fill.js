/**
 * 세모귀 카드뉴스 템플릿 채우기 헬퍼
 *
 * 템플릿 HTML 안의
 *   - 글자 자리:  <span data-slot="키">[예시]</span>
 *   - 이미지 자리: <div data-image-slot="키">...</div>
 * 를 찾아 내용을 넣습니다. 키 목록은 slots.json에 있습니다.
 *
 * 브라우저:  <script src="fill.js"></script> → window.SemogwiTemplates.fillCard(document, data)
 * 번들러/Node: const { fillCard } = require('./fill.js')
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.SemogwiTemplates = api;
})(typeof self !== 'undefined' ? self : this, function () {
  /**
   * @param {Document|Element} target  템플릿 document 또는 그 안의 요소
   * @param {{
   *   text?: Record<string, string>,      // 글자 자리 키 → 넣을 문구
   *   images?: Record<string, string>,    // 이미지 자리 키 → 이미지 URL (누끼 PNG 권장)
   *   accent?: string,                    // 포인트 컬러 (예: '#BFE6D5'), 생략하면 템플릿 기본값
   *   imageFit?: 'contain' | 'cover',     // 기본 'contain' (누끼 이미지가 잘리지 않게)
   *   keepFrame?: boolean                 // true면 이미지 넣은 뒤에도 점선 테두리·배경 유지
   * }} data
   * @returns {{ missingText: string[], missingImages: string[], unknownKeys: string[] }}
   *          채우지 못한 자리와 템플릿에 없는 키 (검수용)
   */
  function fillCard(target, data) {
    data = data || {};
    const text = data.text || {};
    const images = data.images || {};
    const doc = target.ownerDocument || target;
    const scope = target.querySelectorAll ? target : doc;

    if (data.accent) {
      const el = target.documentElement || doc.documentElement;
      el.style.setProperty('--accent', data.accent);
    }

    const seen = new Set();
    const missingText = [];
    scope.querySelectorAll('[data-slot]').forEach((el) => {
      const key = el.getAttribute('data-slot');
      seen.add(key);
      if (Object.prototype.hasOwnProperty.call(text, key) && text[key] != null) {
        el.textContent = String(text[key]);
        el.removeAttribute('data-empty');
      } else {
        missingText.push(key);
        el.setAttribute('data-empty', '');
      }
    });

    const missingImages = [];
    scope.querySelectorAll('[data-image-slot]').forEach((box) => {
      const key = box.getAttribute('data-image-slot');
      seen.add(key);
      const url = images[key];
      if (!url) { missingImages.push(key); return; }
      const img = doc.createElement('img');
      img.src = url;
      img.alt = box.getAttribute('aria-label') || key;
      img.style.objectFit = data.imageFit || 'contain';
      box.replaceChildren(img);
      if (!data.keepFrame) {
        box.style.border = 'none';
        box.style.background = 'transparent';
      }
    });

    const unknownKeys = Object.keys(text).concat(Object.keys(images)).filter((k) => !seen.has(k));
    return { missingText, missingImages, unknownKeys };
  }

  /** 템플릿 안의 모든 키 목록 (slots.json 없이 바로 확인할 때) */
  function listSlots(target) {
    const scope = target.querySelectorAll ? target : document;
    return {
      text: [...scope.querySelectorAll('[data-slot]')].map((el) => el.getAttribute('data-slot')),
      images: [...scope.querySelectorAll('[data-image-slot]')].map((el) => el.getAttribute('data-image-slot')),
    };
  }

  return { fillCard, listSlots };
});
