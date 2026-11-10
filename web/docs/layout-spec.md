# Layout Spec — 카드 레이아웃 규격

카드 한 장을 좌표와 디자인 토큰으로 설명하는 JSON이다. 서버가 `app/layout.py`로 검사하고, 브라우저가 `static/renderer.js`로 그린다. 미리보기와 PNG는 같은 그림이다.

실제 AI도 **이 규격을 출력**한다. AI가 HTML이나 코드를 쓰지 않으므로, 검사를 통과하지 못한 결과는 화면에 나가지 않는다.

```json
{
  "version": 1,
  "frame": "card-02",
  "layoutName": "image-left",
  "themeId": "mint-soda",
  "elements": [
    { "type": "shape", "kind": "circle", "box": { "x": -60, "y": -40, "w": 220, "h": 220 }, "color": "accent", "opacity": 0.5, "rotate": 0 },
    { "type": "image", "assetId": null, "box": { "x": 60, "y": 170, "w": 500, "h": 960 }, "fit": "contain", "radius": 40 },
    { "type": "text", "role": "title", "text": "제목", "box": { "x": 590, "y": 230, "w": 430, "h": 300 }, "font": "display", "size": 66, "color": "ink", "align": "left", "maxLines": 3 },
    { "type": "text", "role": "body", "text": "본문", "box": { "x": 590, "y": 560, "w": 430, "h": 540 }, "font": "body", "size": 38, "color": "inkSoft", "align": "left", "maxLines": 9 },
    { "type": "text", "role": "page", "text": "02/05", "box": { "x": 850, "y": 56, "w": 160, "h": 44 }, "font": "body", "size": 28, "color": "inkSoft", "align": "right", "maxLines": 1 }
  ]
}
```

- 캔버스는 1080 × 1350으로 고정이다. `elements`는 적힌 순서대로 그린다.
- 정의되지 않은 필드나 요소 종류가 있으면 거부한다.

## 통일되는 것과 달라지는 것

| 통일 (AI가 바꿀 수 없음) | 달라짐 (AI가 정함) |
| --- | --- |
| 색: 테마 토큰만 사용 (`ink`, `inkSoft`, `accent` 등). 임의의 색상값 불가 | 요소의 위치와 크기 |
| 글꼴: `display`, `body` 두 가지 | 글자 크기 (20 ~ 120), 가로·세로 정렬 (`align`, `valign`), 줄 수 |
| 카드 크기, 세트 전체의 테마 | 장식의 종류·위치·회전 |

## 검사 규칙 (`validate_layout`)

| 규칙 | 이유 |
| --- | --- |
| `title`, `body`, `page` 정확히 1개, `source` 최대 1개 | 필수 정보 누락 방지 |
| 텍스트는 가장자리에서 40px 이상 안쪽 | 잘림 방지 |
| 텍스트·이미지끼리 겹치지 않음 | 가독성 |
| 글자색은 `ink`, `inkSoft`만 | 배경 대비 확보 |
| 이미지 `fit`은 `contain`만 | 이미지를 자르거나 변형하지 않음 |
| `assetId`는 이 작업에 올라온 이미지만, `variant`는 `original` 또는 `cutout` | 임의의 이미지 사용 방지 |
| 사용자가 그 카드에 고른 이미지와 같아야 함 (`jobs.py`) | 고르지 않은 이미지 삽입 방지 |
| 제목·본문·출처가 승인된 구성안과 글자까지 같아야 함 (`jobs.py`) | 승인된 문구 변경 방지 |

렌더러는 글자가 넘치면 원래 크기의 60%까지 줄이고, 그래도 넘치면 자르지 않고 경고를 표시한다.

## 실제 AI의 명세 (version 2)

실제 AI 모드에서는 `app/ai_provider.py`가 이 규격으로 디자인을 받고, `app/design.py`가 검증한다.

- 세트 테마 `job.designTheme`: `source: "ai"`, `label`, `rationale`, `palette`(`bgFrom`, `bgTo`, `ink`, `inkSoft`, `accent`, `accent2`, `accent3`, `panel` 색상값), `fonts`(`display`, `body`). 글꼴은 허용 목록에서만 고른다.
- 카드별 `background`: `start`, `end`(색 토큰), `angle`.
- AI는 텍스트 요소에 위치와 크기만 적는다. **`text`는 서버가 승인된 구성안에서 넣는다.** AI가 다른 문구를 보내도 무시된다.
- 이미지는 `imageRef`(`img1` 등)로 고르고, 서버가 `assetId`, `variant`로 바꾼다.
- 그리는 순서는 장식, 이미지, 글자로 서버가 정한다. 장식이 글자를 가리지 않는다.
- `layoutName`에는 AI가 지은 짧은 이름이 들어간다 (예: `친구: 중앙 정렬과 패널`).

검증과 자동 수정 기준은 `README.md`의 "디자인 검증"을 따른다. 데모 모드는 `app/provider.py`의 고정 레이아웃(version 1)을 그대로 쓴다.

| 필드 | 내용 |
| --- | --- |
| `job.designRequests[frame]` | 카드별 수정 요청과 상태 (`진행 중`, `반영됨`, `실패`) |
| `job.cardImages[frame]` | 카드에 쓴 `{assetId, variant}` 또는 `null` |
| `preview.cards[n].previous` | 수정 전 결과. 전후 비교와 되돌리기에 사용 |
| `job.research` | 검색어, 조회한 페이지, 출처별 검증 결과, 사실 목록 |
| `job.aiCalls` | 호출별 소요 시간, 도구 사용 횟수, 정가 기준 추정 비용 |
