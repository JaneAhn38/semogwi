---
name: fill-figma
description: 세모귀 카드뉴스 마지막 단계. slides.json 경로를 받아 Figma 템플릿(Page 1)을 새 페이지로 복제하고 title·body·source 텍스트와 표지 이미지를 넣은 뒤 card-01 ~ card-05를 1080×1350 PNG로 내보낸다. write-copy가 slides.json을 만든 다음에 쓰거나, "피그마에 넣어줘", "카드뉴스 PNG 뽑아줘"라는 요청에 쓴다.
---

# fill-figma: slides.json → Figma → PNG 5장

write-copy가 만든 `slides.json`을 Figma 템플릿에 채우고 PNG로 내보내는 단계다. **문구를 고치거나 이미지를 만드는 단계가 아니다.** 검사에서 문제가 나오면 고치지 말고 멈춘 뒤 보고한다.

기준 문서: [`templates/layers.md`](../../../templates/layers.md) (레이어·slides.json 규격), [`templates/figma-config.md`](../../../templates/figma-config.md) (Figma 파일·작업 원칙)

## 입력

| 항목 | 필수 | 예시 |
| --- | --- | --- |
| slides.json 경로 | ✅ | `projects/2026-10-29_치이카와-서사-정리/slides.json` |

- 실행 예: `/fill-figma projects/2026-11-05_치이카와-서사-정리/slides.json`
- 경로를 주지 않았으면 진행하지 말고 물어본다.
- 대상 Figma 파일은 `figma-config.md`의 File Key(`b7ersPQ6u13fVoCPjuwUs9`)를 쓴다. 사용자가 다른 파일을 지정하지 않는 한 바꾸지 않는다.
- 새 페이지 이름은 `세모귀_<프로젝트 폴더 이름>`이다 (예: `세모귀_2026-10-29_치이카와-서사-정리`). `scripts/fill_figma.py`가 자동으로 만든다.

## 도구

| 용도 | 도구 |
| --- | --- |
| 로컬 검사·코드 생성 | `py scripts/fill_figma.py validate / render / verify-png` (프로젝트 루트에서 실행) |
| Figma 연결 확인 | `whoami`, `create_session` |
| 템플릿 확인·복제·텍스트 교체·검증 | `use_figma` (코드는 반드시 `render`로 만든 것을 그대로 넘김) |
| 이미지 교체 | `upload_assets` + `curl` POST |
| 시각 확인 | `get_screenshot` |
| PNG 내보내기 | `download_assets` + `curl` |

- Figma 도구가 지연 로드 상태면 `ToolSearch`의 `select:`로 한 번에 불러온다.
- `use_figma`를 처음 부르기 전에 figma-use 지침(`/figma-use` 스킬, 없으면 MCP 리소스 `skill://figma/figma-use/SKILL.md`)을 읽고, `skillNames`에 적는다 (리소스로 읽었으면 `resource:figma-use`).
- `render`가 출력한 JavaScript를 **고치지 않고** `use_figma`의 `code`로 넘긴다. 코드를 손으로 바꿔야 할 것 같으면 멈추고 보고한다.
- `render`는 slides.json 규격 오류가 있으면 코드를 만들지 않고 종료 코드 1로 끝난다. 이때는 1단계로 돌아가 오류를 보고한다.

## 절차

각 단계가 실패하면 **그 자리에서 멈추고** 아래 "오류 처리"에 따라 보고한다. 다음 단계로 넘어가지 않는다.

1. **로컬 검증**: `py scripts/fill_figma.py validate <slides.json>`
   - `[오류]`가 하나라도 있으면 중단한다. 글자 수·줄바꿈 문제는 write-copy에서 고칠 일이므로 slides.json을 직접 고치지 않는다.
   - `[경고]`는 보고에 모두 옮긴다. 다음 경고는 진행 전에 사용자에게 확인받는다.
     - 이미지 사용 허가가 `허가됨`이 아닌데 프로젝트 폴더 이름이 `_테스트`로 끝나지 않을 때
     - 이미지가 FIT에서 1.25배 넘게 확대될 때 (아래 "이미지 해상도" 참고)
   - 결과의 `대상 페이지 이름`을 기록한다.
2. **Figma 연결**: `whoami`로 연결을 확인하고, `create_session`(fileKey, 작업 설명)으로 세션을 만든다. 이후 모든 Figma 호출에 같은 `sessionId`를 넘긴다.
3. **사전 점검 (읽기 전용)**: `render preflight` → `use_figma`
   - `targetExists: true`면 **중단**한다. 이미 있는 페이지는 덮어쓰거나 지우지 않는다.
   - `problems`가 있으면 중단한다 (프레임·레이어 누락, 이름 중복, 폰트 없음, title·body 텍스트 크기 조절이 `HEIGHT`가 아님, 자리표시 제목이 1줄 높이(100)가 아님 등).
     - 텍스트 크기 조절·제목 높이 문제는 템플릿이 바뀌었다는 뜻이다. 레이아웃 검사 기준(`layers.md` 6장)을 다시 측정해야 하므로 템플릿을 고치지 말고 보고한다.
   - `page1Signature.hash`를 기록한다 (11단계에서 비교).
4. **복제 (첫 쓰기 = 편집 권한 확인)**: `render clone` → `use_figma`
   - 권한 오류면 중단하고 `whoami`의 팀·좌석(View/Full)을 함께 보고한다.
   - 결과의 `pageId`, 각 프레임 ID, `card-01`의 `main-image` ID를 기록한다.
5. **텍스트 교체 + 레이아웃 검사**: `render fill-text` → `use_figma`
   - title·body·source만 바꾸고, source가 `""`이면 그 레이어만 숨긴다.
   - `ok: false`면 중단한다. 각 프레임의 `errors`(제목 2줄, title-body 겹침, 하단 여백 침범, source-page-number 겹침, 고정 요소 변경)를 그대로 보고한다. 텍스트를 줄이거나 레이어를 옮겨서 맞추지 않는다.
6. **표지 이미지 교체** (`card-01`에 `image`가 있을 때만)
   - `upload_assets`: `count: 1`, `nodeIds: [<card-01 main-image ID>]`, `scaleMode: "FIT"`, `currentPageId: <pageId>`
   - 받은 `submitUrl`로 파일 원본 바이트를 보낸다. multipart 방식은 파일 이름이 레이어 이름으로 바뀔 수 있으므로 쓰지 않는다.
     ```
     curl -sS -f -X POST -H "Content-Type: image/png" --data-binary @<image 경로> "<submitUrl>"
     ```
     Content-Type은 validate가 알려 준 실제 형식(png → `image/png`, jpeg → `image/jpeg`, webp → `image/webp`)을 쓴다.
   - 응답의 `success: true`와 `placedOnNodeId`가 main-image ID와 같은지 확인한다.
7. **결과 검증 (읽기 전용)**: `render verify` → `use_figma`
   - `ok: false`면 중단하고 `problems`를 보고한다.
   - `exportFrames`(프레임 ID 5개)를 기록한다.
8. **스크린샷 확인**: 5개 프레임에 `get_screenshot`을 한 번에(병렬로) 호출하고, 받은 URL을 `curl`로 세션 임시 폴더에 받아 직접 본다.
   - 텍스트 겹침·잘림, 이미지 잘림, 단어 중간 줄바꿈, 고정 요소 이상을 확인한다.
   - 스크린샷은 프로젝트 폴더에 저장하지 않는다.
9. **PNG 내보내기**: 5개 프레임에 `download_assets`(`defaultFormat: "png"`, `defaultScale: 1`)를 한 번에 호출하고, `export.url`을 받는다.
   ```
   mkdir -p projects/<폴더>/png
   curl -sS -f -L -o projects/<폴더>/png/card-01.png "<export.url>"
   ```
   - 파일 이름은 프레임 이름과 같게 `card-01.png` ~ `card-05.png`로 한다. URL은 금방 만료되므로 받은 즉시 내려받는다.
10. **PNG 검증**: `py scripts/fill_figma.py verify-png projects/<폴더>/png` — 5장 모두 PNG, 1080×1350이어야 한다.
11. **원본 보존 확인 (읽기 전용)**: `render signature` → `use_figma`. `page1Signature.hash`가 3단계 값과 다르면 즉시 보고한다 (자동으로 되돌리지 않는다).
12. **보고**: 아래 "보고 형식"대로 짧게 알린다. 다음 단계나 게시는 자동으로 시작하지 않는다.

## 규칙

- [ ] **원본 `Page 1`은 절대 쓰지 않는다.** Figma 쓰기는 4·5·6단계에서 새 페이지에만 한다. Page 1은 읽기만 한다 (3·11단계 서명으로 확인).
- [ ] **기존 테스트 페이지(`세모귀_2026-10-29_테스트` 등)도 지우거나 덮어쓰지 않는다.** 대상 페이지가 이미 있으면 3단계에서 멈춘다.
- [ ] **이미 있는 페이지·PNG는 덮어쓰지 않는다.** 같은 이름의 페이지가 있거나 `png/`에 카드 PNG가 이미 있으면 멈추고 사용자에게 묻는다.
- [ ] 레이어는 템플릿의 **6개 구조 그대로** 둔다. 추가·삭제·이름 변경·이동·크기 변경을 하지 않는다.
- [ ] `page-number`, `bottom-overlay`, 배경(프레임 채우기)은 바꾸지 않는다. card-02 ~ card-05의 `main-image`도 그대로 둔다 (MVP).
- [ ] `source` 레이어는 텍스트만 바꾼다. 템플릿의 `@세모귀`는 임시 텍스트다. 빈 값이면 숨기기만 한다.
- [ ] slides.json의 문구를 고치거나, 넘친 텍스트를 자르거나, 폰트 크기를 줄이지 않는다.
- [ ] 이미지를 확대·편집·덮어쓰지 않는다. 해상도가 부족하면 경고만 하고, 새 누끼는 다른 파일 이름으로 만든다.
- [ ] `sources.md`에 출처가 없는 이미지는 쓰지 않는다. 사용 허가가 `허가됨`이 아닌 이미지는 테스트에만 쓰고 외부에 게시하지 않는다.
- [ ] 오류가 나면 다른 방법으로 바꿔 시도하지 않는다 (예: use_figma로 이미지 채우기, multipart 업로드, 다른 내보내기 도구). 원인을 보고하고 지시를 기다린다.

## 이미지 해상도

`main-image`는 908×780이고 FIT으로 넣는다. FIT 배율 = `min(908 / 너비, 780 / 높이)`이며, 1보다 크면 확대되어 흐려진다.

- validate가 배율을 계산해 경고하고(1배 초과 경고, 1.25배 초과는 진행 전 확인), `sources.md`의 원본 해상도를 읽어 다시 누끼를 만들면 해결되는지 알려 준다.
  - 원본의 FIT 배율도 1을 넘으면 → "원본 자체가 작음". 누끼를 다시 만들어도 해결되지 않는다.
  - 원본 배율이 1 이하이면 → 확대 없이 넣는 데 필요한 누끼 긴 변(`원본 긴 변 × 원본 FIT 배율`)과 권장 `--max-size`를 알려 준다.
- `scripts/cutout.py`의 `--max-size`는 긴 변을 **줄이기만** 하고 키우지는 않는다 (기본 512). 원본이 충분히 크면 더 큰 값으로 다시 만든다.
  ```
  py scripts/cutout.py assets/characters/chiikawa/original/<원본> assets/characters/chiikawa/cutout/<새 이름>.png --max-size 1024
  ```
  - 기존 누끼 파일을 덮어쓰지 않도록 출력 경로를 반드시 새 이름으로 지정한다. `cutout.py`는 같은 이름이 있으면 묻지 않고 덮어쓴다.
  - 출력 경로를 생략하면 **원본과 같은 `original/` 폴더**에 `<이름>-cutout.png`로 저장되므로 생략하지 않는다.
  - 1024는 세로형 이미지도 높이 780을 넘기기 위한 값이다 (예: 2000×2356 원본 → 869×1024 누끼, FIT ×0.76). 메모리가 부족하면 `cutout.py`가 안내하는 진단을 따른다.
  - 이 작업은 fill-figma가 하지 않는다. 경고를 보고하고, 사용자가 누끼를 다시 만들지 결정한다.
  - 새 누끼를 만들면 `sources.md`에 행을 추가하고 slides.json의 `image`를 새 경로로 바꾼다 (write-copy 또는 사용자 작업).
- 원본 자체가 작으면 누끼를 다시 만들어도 해결되지 않는다. 더 큰 원본을 구해야 한다.

## 오류 처리

| 상황 | 처리 |
| --- | --- |
| validate `[오류]` | 중단. 오류 목록 보고. Figma는 건드리지 않음 |
| Figma 연결 실패 / `whoami` 실패 | 중단. 연결 상태 보고 |
| 대상 페이지가 이미 있음 | 중단. 페이지 이름 보고. 지우거나 덮어쓰지 않음 |
| 템플릿 구조 문제 (preflight `problems`) | 중단. 문제 목록 보고. 템플릿을 고치지 않음 |
| 복제 중 권한 오류 | 중단. `whoami` 팀·좌석과 함께 보고 |
| `use_figma` 오류 (공통) | 중단. 오류 메시지와 `safeToRetryWithoutCanvasRead` 값 보고. 쓰기 단계였으면 새 페이지 상태를 읽기 전용으로 확인해 함께 보고 |
| fill-text `ok: false` | 중단. 프레임별 `errors` 보고. 새 페이지는 확인용으로 남겨 둠 |
| 업로드 실패 / URL 만료 | 중단. 응답 내용 보고 |
| verify `ok: false` | 중단. `problems` 보고 |
| 내보내기 실패 / PNG 검증 실패 | 중단. 실패한 프레임·파일 보고. 받은 파일은 지우지 않음 |
| Page 1 서명 불일치 | 즉시 보고. 자동 복구 시도 안 함 |

- 실패로 중간에 멈추면 새 페이지가 남을 수 있다. 자동으로 지우지 말고 페이지 이름과 상태를 보고한다. 다시 실행하려면 사용자가 그 페이지를 지우거나 이름을 바꿔야 한다.

## 보고 형식

```markdown
## fill-figma 결과: 성공 / 실패(n단계)

- slides.json: projects/<폴더>/slides.json
- Figma 페이지: 세모귀_<폴더> (pageId)
- Page 1 보존: 서명 일치 (hash)

| 프레임 | ID | title | body 줄 수 | source | 이미지 | PNG |
| --- | --- | --- | --- | --- | --- | --- |
| card-01 | 24:3 | 1줄 | 1 | 표시 | FIT ×1.52 | 1080×1350 ✅ |

- 경고: (validate·fill-text·스크린샷에서 나온 것)
- PNG 위치: projects/<폴더>/png/
```
