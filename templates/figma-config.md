# 세모귀 Figma 연결 정보

> 카드뉴스 자동화(fill-figma)가 사용할 Figma 템플릿 정보를 정리한 문서입니다.
> 레이어 역할과 `slides.json` 규격의 기준 문서는 [`layers.md`](layers.md)이며, 이 문서는 그 내용을 실제 Figma 파일에 연결하는 정보만 담습니다.

---

## 1. 원본 템플릿 파일

| 항목 | 값 |
| --- | --- |
| 파일 URL | https://www.figma.com/design/b7ersPQ6u13fVoCPjuwUs9/ |
| File Key | `b7ersPQ6u13fVoCPjuwUs9` |
| 페이지 이름 | `Page 1` |
| 카드 프레임 | `card-01` ~ `card-05` (5개) |
| 카드 크기 | 1080 × 1350 px |
| `main-image` | Rectangle, 908 × 780 px |

---

## 2. 작업 원칙: 원본은 덮어쓰지 않는다

- **원본 템플릿(`Page 1`의 `card-01` ~ `card-05`)은 직접 수정하지 않습니다.** 자동화와 수동 작업 모두 복사본에서 진행합니다.
- 카드뉴스 한 편마다 **같은 파일 안에 새 페이지**를 만들고, `Page 1`의 5개 프레임을 그 페이지로 복제한 뒤 복사본의 텍스트·이미지만 교체합니다.
- 복사본 페이지에서도 프레임 이름(`card-01` 등)은 그대로 두며, fill-figma는 **작업 중인 새 페이지 안에서만** 프레임·레이어를 이름으로 찾습니다. 그래서 다른 페이지의 같은 이름과 충돌하지 않습니다.
- 레이어 구성은 템플릿의 **6개 레이어**(`title`, `body`, `main-image`, `page-number`, `source`, `bottom-overlay`)를 그대로 유지하며, 레이어를 새로 추가하거나 지우지 않습니다.
- 원본의 프레임·레이어 이름(`card-01`, `title` 등)은 자동화 스크립트가 이름으로 찾는 기준이므로 바꾸지 않습니다.
- 원본 템플릿 디자인을 바꿔야 할 때는 팀원과 먼저 상의하고, 바뀐 내용을 `layers.md`와 이 문서에 함께 반영합니다.

---

## 3. slides.json → Figma 레이어 대응

`projects/날짜_주제/slides.json`의 각 슬라이드는 `frame` 값과 같은 이름의 프레임에 들어갑니다.

| JSON 필드 | Figma 대상 | 필수 | 규칙 | 처리 |
| --- | --- | --- | --- | --- |
| `series` | - | ✅ | 항상 `"세모귀"` | 메타데이터 |
| `topic` | - | ✅ | 이번 카드뉴스 주제 | 메타데이터 |
| `character` | - | ✅ | `assets/characters/` 아래 폴더 이름 | 메타데이터 (이미지 경로 확인용) |
| `slides[n].frame` | 프레임 `card-01` ~ `card-05` | ✅ | 중복 불가, 항상 5개 | 프레임 찾기 |
| `slides[n].title` | `title` (Jua) | ✅ | 20자 이내 (공백 포함), 한 줄 유지를 위해 16자 이하 권장 | 텍스트 교체 |
| `slides[n].body` | `body` (Gowun Dodum) | ✅ | 80자 이내 (공백 포함), 42자 초과 시 `\n`으로 줄 나눔, 2줄 이하 | 텍스트 교체 |
| `slides[n].source` | `source` | 선택 | 30자 이내, `출처: `로 시작 | 텍스트 교체, `""`이면 레이어 숨김 |
| `slides[n].image` | `main-image` (Rectangle, 908 × 780) | 선택 | `cutout/` 폴더의 누끼 이미지, MVP는 `card-01`만 | 이미지 교체 (FIT) |
| (없음) | `page-number` | - | 현재 고정 | 건드리지 않음 |
| (없음) | `bottom-overlay`, 배경 | - | 고정 | 건드리지 않음 |

> `source` 레이어에 지금 적혀 있는 `@세모귀`는 브랜드 표기가 아니라, 출처가 정해지지 않아 넣어 둔 **임시 텍스트**입니다. fill-figma는 이 레이어를 그대로 두고 `slides.json`의 `source` 값으로 텍스트만 교체합니다. 브랜드 표기용 레이어는 따로 만들지 않습니다.

---

## 4. 확정 / 미확정 사항

정해진 항목은 ✅로 표시하고, 아직 정해지지 않은 항목은 정해지면 이 표를 갱신합니다.

| 항목 | 상태 | 내용 |
| --- | --- | --- |
| 복사 방식 | ✅ 확정 | 같은 파일 안에 새 페이지를 만들고 `Page 1`의 `card-01` ~ `card-05`를 복제. 프레임·레이어는 새 페이지 안에서만 이름으로 찾음 (2장 참고) |
| `source` 레이어 | ✅ 확정 | 기존 레이어 유지, 텍스트만 교체. 현재 값 `@세모귀`는 임시 텍스트 (3장 참고) |
| 레이어 구성 | ✅ 확정 | 기존 6개 레이어 유지, 추가·삭제 없음 |
| `main-image` 이미지 맞춤 방식 | ✅ 확정 | **FIT** (이미지 전체가 보이도록 맞춤, 잘리지 않음) |
| 복사본 페이지 이름 규칙 | ✅ 확정 | `세모귀_<프로젝트 폴더 이름>` (예: `세모귀_2026-10-29_테스트`). `scripts/fill_figma.py`가 폴더 이름으로 자동 생성. 같은 이름이 있으면 중단 |
| Figma 자동 편집 연동 방법 | ✅ 확정 | **Figma MCP**. 복제·텍스트 교체·검증은 `use_figma`, 이미지 교체는 `upload_assets`, 확인은 `get_screenshot` (5장 참고) |
| PNG 내보내기 방법 | ✅ 확정 | Figma MCP `download_assets` (PNG, 배율 1) → 1080 × 1350 |
| 폰트 로드 | ✅ 확인됨 | Jua Regular / Gowun Dodum Regular 모두 MCP 환경에서 로드·적용됨 (2026-10-29 테스트) |
| `main-image` 해상도 | ⚠️ 이미지마다 확인 | `cutout.py` 기본값(긴 변 512px)으로 만든 누끼는 FIT에서 확대됨 (`test.png` 435 × 512 → 1.52배). 6장 참고 |

---

## 5. 연동 테스트 결과 (2026-10-29)

테스트 데이터 `projects/2026-10-29_테스트/slides.json`으로 Figma MCP 연동을 확인했습니다. 테스트 페이지 `세모귀_2026-10-29_테스트`는 확인용으로 남겨 두며, fill-figma가 덮어쓰지 않습니다.

| 항목 | 결과 | 사용 도구 |
| --- | --- | --- |
| 편집 권한 | ✅ 새 페이지 생성 성공 | `use_figma` |
| 새 페이지 생성·5개 프레임 복제 | ✅ 같은 위치로 복제, Page 1 변경 없음 | `use_figma` |
| title·body·source 교체 | ✅ 15개 레이어 교체, 폰트 정상 | `use_figma` |
| 빈 source 숨김 | ✅ card-05 source만 숨김 | `use_figma` |
| 고정 요소 | ✅ page-number·bottom-overlay·배경 변경 없음 | `use_figma` |
| 표지 이미지 교체 | ✅ card-01 main-image에 FIT 적용, 레이어 이름 유지 | `upload_assets` + 원본 바이트 POST |
| PNG 내보내기 | ✅ 5장 모두 1080 × 1350 | `download_assets` (png, 1x) |
| 텍스트 겹침·잘림 | ✅ 없음 (수치 검사 + 스크린샷) | `use_figma`, `get_screenshot` |

**테스트에서 알게 된 점**

- 이미지 업로드는 원본 바이트(`Content-Type: image/png`)로 보냅니다. multipart 방식은 파일 이름이 레이어 이름이 될 수 있어 `main-image` 이름이 바뀔 위험이 있습니다.
- 한글 본문은 Figma가 **글자 단위**로 줄을 바꿔, 47자 본문이 "시작됐 / 어요."처럼 단어 중간에서 끊겼습니다 → `layers.md` 6장 규칙.
- 제목 14자가 너비 960 중 약 800px를 차지했습니다. 17자 이상은 2줄이 되어 body와 겹칠 가능성이 큽니다 → `layers.md` 6장 규칙.
- 투명 배경 누끼를 FIT으로 넣으면 원래 회색 자리표시가 사라지고 배경 그라데이션이 비칩니다.
- card-02 ~ card-05의 `main-image`는 회색 자리표시가 그대로 내보내집니다. 게시용에서 어떻게 처리할지(숨김 / 이미지 추가)는 아직 정하지 않았습니다.
- `assets/characters/chiikawa/original/test.png`는 확장자만 `.png`이고 실제 형식은 **WebP**(2000 × 2356)입니다. `fill_figma.py`는 확장자가 아니라 파일 내용으로 형식을 판별합니다.

---

## 6. 표지 이미지 해상도 기준

- `main-image`는 908 × 780, FIT입니다. 배율 = `min(908 / 너비, 780 / 높이)`. 1을 넘으면 확대되어 흐려집니다.
- `py scripts/fill_figma.py validate`가 배율을 계산해 경고하고, `sources.md`의 원본 경로로 원본 해상도를 읽어 다시 누끼를 만들면 해결되는지 알려 줍니다.
  - 원본의 FIT 배율도 1을 넘으면 "원본 자체가 작음"으로 안내합니다.
  - 아니면 확대 없이 넣는 데 필요한 누끼 긴 변(`원본 긴 변 × 원본 FIT 배율`)과 권장 `--max-size`(최소 1024, 원본 긴 변 이하)를 알려 줍니다.
  - 예: `test.png` 원본 2000 × 2356 → 필요한 긴 변 780, `--max-size 1024`로 만들면 869 × 1024, FIT ×0.76 (확대 없음).
- `scripts/cutout.py`의 `--max-size`는 긴 변을 **줄이기만** 합니다(기본 512). 원본이 크면 값을 키워 다시 만듭니다.

  ```
  py scripts/cutout.py assets/characters/chiikawa/original/<원본> assets/characters/chiikawa/cutout/<새 이름>.png --max-size 1024
  ```

  - 기존 누끼를 덮어쓰지 않도록 출력 경로는 새 이름으로 지정합니다. `cutout.py`는 같은 이름이 있으면 묻지 않고 덮어쓰고, 출력 경로를 생략하면 원본과 같은 `original/` 폴더에 저장합니다.
  - 새 누끼는 `sources.md`에 행을 추가한 뒤 slides.json `image`에 씁니다.
  - 원본 자체가 작으면 다시 만들어도 해결되지 않습니다. 원본 이미지를 임의로 확대하지 않습니다.

---

## 7. 테스트 파일 Git 관리

- 사용 허가가 확인되지 않은 테스트 이미지(`assets/characters/*/original|cutout/test.*`, `test-*`)와 테스트 프로젝트 PNG(`projects/*_테스트/png/`)는 `.gitignore`로 제외합니다.
- 정상 콘텐츠 이미지는 이름을 `test`로 시작하지 않게 짓고, 실제 프로젝트 폴더 이름은 `_테스트`로 끝나지 않게 합니다. 그래야 제외 규칙에 걸리지 않습니다.
- 테스트 프로젝트의 `slides.json`은 이미지가 아니므로 제외하지 않습니다 (레이아웃 검사 기준 데이터로 커밋).
- 2026-10-29 확인: Git 기록 전체에 이미지 파일(png/jpg/webp/gif)이 커밋된 적이 없어 추적 해제(`git rm --cached`)할 파일은 없습니다. `git check-ignore -v <경로>`로 규칙이 적용되는지 확인할 수 있습니다.
  - 제외됨: `cutout/test.png`, `original/test.png`, `original/test-02.jpg`, `projects/2026-10-29_테스트/png/*.png`
  - 제외되지 않음: `cutout/chiikawa-01.png`, `original/latest.png`, `projects/2026-11-05_치이카와-서사-정리/png/card-01.png`
