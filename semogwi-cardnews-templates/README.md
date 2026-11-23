# 세모귀 카드뉴스 템플릿 (20장)

> **보관용 디자인 원본입니다.** 세모귀 프로젝트의 최초 카드뉴스 디자인이며, 원본 디자인 참고와 보관을 위해 저장소에 둡니다.
> 현재 웹앱(`web/`)은 이 폴더를 읽지 않고, 같은 디자인을 옮긴 **`web/templates/*.json`** 과 캔버스 렌더러(`web/static/renderer.js`)로 카드를 만듭니다.
> 이후 웹 템플릿에서 바뀐 디자인(예: 캐릭터 소개 친구들·TMI 가로형, card-05 새 디자인)은 이 폴더에 반영되어 있지 않습니다.
> 웹앱의 폰트(`web/static/fonts/`)와 로고(`web/static/brand/semogwi-logo.svg`)는 이 폴더에서 가져왔습니다. 아래 설명은 원본 패키지의 사용법입니다.

주제 4종 × 5장, 카드 크기 1080×1350 (인스타그램 세로형).

| 주제 | 01 | 02 | 03 | 04 | 05 |
| --- | --- | --- | --- | --- | --- |
| 팝업스토어 `popup` | 표지 | 운영 정보 | 현장 한정 굿즈 | 포토존·특전 | 마무리 |
| 공식 굿즈 `goods` | 표지 | 라인업 한눈에 | 주목할 굿즈 | 구매 방법 | 마무리 |
| 콜라보 `collab` | 표지 | 어떤 콜라보? | 제품·메뉴 | 혜택·이벤트 | 마무리 |
| 캐릭터 소개 `character` | 표지 | 프로필 | 성격·특징 | 친구들·TMI | 마무리 |

## 폴더 구성

```
templates/        ← 웹앱에서 쓸 템플릿 (순수 HTML + 인라인 CSS, JS 없음)
fill.js           ← 템플릿에 글·이미지를 넣는 헬퍼
slots.json        ← 장마다 넣을 수 있는 글자/이미지 자리 목록
render-png.mjs    ← 데이터 → PNG 1080×1350 자동 저장 예시 (Playwright)
examples/         ← 예시 데이터 (팝업 5장)
fonts/            ← Jua, Gowun Dodum (woff2) + fonts.css + 라이선스
index.html        ← 20장 한눈에 보기 (브라우저로 열기)
original/         ← Claude 디자인 캔버스 원본 파일 (.dc.html, canvas.json)
```

폰트 파일 보관 방식:

- **GitHub에 보관**: `Jua-Regular.woff2`, `GowunDodum-Regular.woff2`, `fonts.css`, 라이선스 파일(`OFL-Jua.txt`, `OFL-GowunDodum.txt`)
- **로컬에만 보관 (GitHub에 포함하지 않음)**: `Jua-Regular.ttf`, `GowunDodum-Regular.ttf` (woff2와 같은 글꼴, 약 9.3MB)
- `fonts.css`는 woff2를 먼저 읽고 TTF는 woff2를 못 읽을 때만 쓰는 예비용이라, TTF가 없어도 현재 브라우저(Chrome·Edge·Safari·Firefox)에서 똑같이 표시됩니다.

`original/`의 `.dc.html`은 Claude 디자인 캔버스 전용 형식이라 그 편집기 밖에서는 그대로 열리지 않아요. 보관용으로 넣었어요. 웹앱에는 `templates/`를 쓰세요. 디자인은 같아요.

## 템플릿 구조

- 글자 자리: `<span data-slot="키">[예시 문구]</span>`
- 이미지 자리: `<div data-image-slot="키" aria-label="설명">` (점선 박스)
- 포인트 컬러: CSS 변수 `--accent` (팝업 `#BFE6D5`, 굿즈 `#FDE7A6`, 콜라보 `#C9D8F5`, 캐릭터 `#F7C6D3`)
- 오른쪽 아래 페이지 번호는 다음 장으로 가는 링크예요. 이미지로 저장하면 보이는 모양은 그대로예요.

키 이름은 `slots.json`에 장별로 정리돼 있어요. 예:

```json
"popup-02-info": ["period_start", "period_end", "open_time", "close_time", "place_detail",
                  "entry_type", "closed_days", "tip1", "tip2", "tip3", "source"]
```

자리 하나에는 괄호 안 부분만 들어가요. 예를 들어 `[가격]원`이면 `"15,000"`만 넣으면 `15,000원`이 돼요. 마찬가지로 `· [입장 팁]`처럼 앞에 붙은 기호도 템플릿에 있으니 데이터에는 빼고 넣으세요.

## 웹앱에서 채우기

```js
// 템플릿 HTML을 iframe이나 헤드리스 브라우저로 연 뒤
const report = SemogwiTemplates.fillCard(document, {
  text:   { character: '말랑곰', period_start: '12.05', period_end: '12.21', location: '성수 · 서울숲역' },
  images: { main_image: '/uploads/malanggom-cutout.png' },   // 누끼 PNG 권장
  accent: '#BFE6D5',          // 생략하면 템플릿 기본색
});
// report.missingText / missingImages: 비어 있는 자리, report.unknownKeys: 템플릿에 없는 키
```

- 이미지는 기본으로 `object-fit: contain`이라 누끼가 잘리지 않아요. 사진을 꽉 채우려면 `imageFit: 'cover'`.
- 이미지를 넣으면 점선 테두리는 사라져요. 유지하려면 `keepFrame: true`.

## PNG로 저장

```bash
npm i playwright
npx playwright install chromium      # 처음 한 번
node render-png.mjs examples/popup-sample.json out/
# 2배 크기(2160×2700)로 저장: SCALE=2 node render-png.mjs ...
```

빈 자리가 있으면 터미널에 장별로 경고가 떠요. 검수 단계에서 쓰면 좋아요.

## 주의할 점

- **글자 수**: 템플릿은 글자 넘침을 자동으로 줄이지 않아요. 표지 제목은 10자 안팎, 본문 한 줄은 25자 안팎이 안전해요(WBS 기준: 제목 20자, 본문 80자 이내). 넘치면 문구를 줄이세요.
- **이미지**: WBS 저작권 방침대로 공식 계정·홈페이지 원본만 쓰고, 마무리 장 `source` 자리에 출처를 꼭 넣으세요.
- **폰트**: Jua, Gowun Dodum 모두 SIL Open Font License 1.1이라 상업적 이용과 웹 임베드가 가능해요. 라이선스 파일(`fonts/OFL-*.txt`)은 함께 배포하세요.
- 왼쪽 위 로고는 인라인 SVG라 별도 이미지 파일이 없어요.
