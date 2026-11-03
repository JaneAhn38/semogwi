# 세모귀 (세상의 모든 귀여운 것들)

> Claude Code로 캐릭터 카드뉴스를 자동으로 만드는 프로젝트
> **주제 / 사진 / 공식 상품 URL**을 넣으면 → 공식 자료 조사 → 구성안 → (사용자 승인) → 카드별 이미지 지정 → 문구 작성 → Figma 템플릿 적용 → **PNG 5장(1080 × 1350)**

MVP 기준일: 2026-11-03

---

## 1. MVP 기능과 검증 상태

| 기능 | 구현 | 실제 통합 테스트 (Figma·PNG까지) | 근거 프로젝트 |
| --- | --- | --- | --- |
| 주제 입력 → 카드뉴스 | ✅ | ✅ (규칙 변경 전) | `projects/2026-11-03_치이카와-캐릭터-소개/` ※ |
| 공식 상품 URL 입력 | ✅ `scripts/fetch_product.py` | ✅ 분석 → PNG까지 진행 (상품 정보·이미지는 수동 수집본 사용) / ⚠️ 스크립트 최종본 재실행은 미검증 (429) | `projects/2026-11-03_코인실린더_테스트/` |
| 사진 입력 (analyze-image) | ✅ | ⚠️ 분석·확인 단계까지만 (이후 단계 미실행) | `projects/2026-11-03_이미지분석_테스트/` |
| 공식 자료 조사 (research-topic) | ✅ | ✅ | 코인 실린더 |
| 구성안 생성 (plan-cardnews) | ✅ | ✅ | 코인 실린더 |
| 사용자 승인 (분석 확인·구성안 승인·이미지 지정) | ✅ | ✅ | 코인 실린더 |
| 카드별 이미지 지정 + FIT 배치 | ✅ `scripts/assign_images.py` | ✅ (일부 카드만, 같은 이미지 재사용, 본문 카드, 빈 카드 숨김) | `projects/2026-11-03_카드이미지통합_테스트/` |
| 누끼 처리 | ✅ `scripts/cutout.py` | ✅ 표지 누끼 Figma 배치 (11-03 오전) / ⚠️ `assign_images.py`의 누끼 결과를 Figma에 넣는 경로는 단독 테스트까지 | `projects/2026-11-03_누끼_테스트/` |
| 문구 자동 작성 (write-copy) | ✅ | ✅ | 코인 실린더 |
| Figma 템플릿 적용 + PNG 5장 (fill-figma) | ✅ | ✅ (원본 Page 1 서명 유지) | 위 3개 프로젝트 |

※ 캐릭터 소개 프로젝트는 "카드에는 `[공식]`만" 규칙이 생기기 전에 만든 결과라, 지금 규칙으로는 `[2차 출처]` 내용 때문에 구성안 단계에서 멈춥니다. **현재 규칙에 맞는 대표 시연은 코인 실린더 프로젝트입니다.**

## 2. 자동화 흐름

```
입력 ─┬─ 주제 ───────────────────────────────┐
      ├─ 사진 ─────────── analyze-image ─────┤ [① 분석 확인]
      └─ 공식 상품 URL ── fetch_product.py ──┘
                ↓
   research-topic (공식 자료 → brief.md)
                ↓
   plan-cardnews (카드 5장 구성안 → outline.md)          [② 구성안 승인]
                ↓
   사용자가 카드별 이미지 업로드·지정 (card-images.json)   [③ 이미지 지정]
                ↓
   assign_images.py (FIT 기본 / 선택 시 누끼, 출처·권한 기록 → cutout-check.md)
                ↓
   write-copy (문구 → slides.json, 글자 수 검사)
                ↓
   fill-figma (Figma 복제본에 적용 → PNG 5장)
```

- 전체 순서는 `.claude/commands/cardnews.md`, 단계별 입력·출력·승인 지점은 `templates/cardnews-pipeline.md`.
- 원칙: **카드에는 공식 출처로 확인된 정보만**, 가격·일정·장소는 임의로 만들지 않음, **원본 Figma 템플릿(Page 1)은 수정하지 않음**, 사용 권한이 확인되지 않은 이미지는 카드에 쓰지 않음.

## 3. 발표용 대표 시연 프로젝트와 결과물

| 시연 | 프로젝트 폴더 | PNG 5장 | Figma 페이지 |
| --- | --- | --- | --- |
| **① URL 입력 전체 흐름 (대표)** | `projects/2026-11-03_코인실린더_테스트/` | `png/card-01.png ~ card-05.png` | `세모귀_2026-11-03_코인실린더_테스트` |
| ② 카드별 이미지 지정 | `projects/2026-11-03_카드이미지통합_테스트/` | `png/card-01.png ~ card-05.png` | `세모귀_2026-11-03_카드이미지통합_테스트` |
| ③ 주제 입력 + 표지 누끼 (참고) | `projects/2026-11-03_치이카와-캐릭터-소개/` | `png/card-01.png ~ card-05.png` | `세모귀_2026-11-03_치이카와-캐릭터-소개` |

- Figma 파일: https://www.figma.com/design/b7ersPQ6u13fVoCPjuwUs9/
- ⚠️ ①·②의 PNG는 폴더 이름이 `_테스트`로 끝나서 `.gitignore`로 **GitHub에 올라가지 않습니다.** 발표 PC의 로컬 폴더나 Figma 페이지에서 보여 주세요.
- ②의 이미지는 세모귀 팀이 테스트용으로 직접 그린 도형 이미지입니다 (권리가 확실한 자료만 사용).

각 프로젝트 폴더에서 단계별 산출물을 순서대로 보여 줄 수 있습니다.

| 파일 | 단계 |
| --- | --- |
| `image-analysis.md` | 상품·사진 분석 (`[공식]` / `[이미지]` / `[추정]` 구분) |
| `brief.md`, `references/` | 공식 자료 조사 |
| `outline.md` | 카드 5장 구성안 (승인 기록) |
| `card-images.json`, `cutout-check.md`, `sources.md` | 카드별 이미지 지정·처리·출처 |
| `slides.json`, `copy-check.md` | 카드 문구와 글자 수 검사 |
| `png/` | 최종 카드뉴스 |

## 4. 시연 순서와 명령어

Claude Code를 프로젝트 루트(`semogwi`)에서 연 상태에서 진행합니다.

1. **입력**: `/cardnews https://chiikawamarket.jp/ko/products/<상품>` (또는 주제·사진 경로)
2. **① 분석 확인**: `image-analysis.md` 확인 → "확인"
3. **② 구성안 승인**: `outline.md`의 5장 구성 확인 → "승인"
4. **③ 이미지 지정**: `projects/<폴더>/input/cards/`에 이미지를 넣고 `card-images.json` 작성 (규격: `templates/card-images.md`). 이미지를 안 쓰면 모든 카드 `null`
5. 나머지(문구 → Figma → PNG)는 자동으로 진행 → `projects/<폴더>/png/`

단계별로 직접 실행할 때 쓰는 스크립트:

```
py scripts/fetch_product.py <공식 상품 URL> projects/<폴더>     # 상품 정보·이미지 가져오기
py scripts/assign_images.py projects/<폴더>                     # 카드별 이미지 처리
py scripts/fill_figma.py validate projects/<폴더>/slides.json    # 문구·이미지 규격 검사
py scripts/fill_figma.py verify-png projects/<폴더>/png          # PNG 5장 1080×1350 검사
py scripts/cutout.py <원본> <출력.png> --max-size 1024           # 누끼 (단독)
```

필요 환경: Python 3, Pillow, rembg(누끼), Figma MCP 연결(치이카와 팀 Full 좌석).

## 5. 제한 사항

- **시연 버튼(UI)은 없습니다.** 지금은 Claude Code에서 `/cardnews`를 실행하고 승인 지점마다 대화로 답합니다. 연결 설계는 `templates/cardnews-pipeline.md` 6장.
- **공식 출처 확보**: 원작자 X 계정은 로그인 없이 열리지 않아 공식 게시물을 붙여 넣어야 합니다. `[공식]` 항목만으로 5장을 못 채우면 파이프라인이 멈춥니다.
- **치이카와 마켓 요청 제한(HTTP 429)**: 같은 상품을 짧은 시간에 여러 번 가져오면 막힙니다. 시연 전에 미리 가져온 결과를 쓰는 것이 안전합니다.
- **이미지 권리**: 공식 쇼핑몰 이미지는 이용규약상 사적 이용을 넘는 복제·공표가 금지되어 분석용으로만 씁니다. 카드 이미지는 사용 권한이 확인된 사용자 지정 이미지만 들어갑니다.
- **사용자 이미지는 Git에 올라가지 않습니다** (`projects/*/input/`, `user-*`). 다른 컴퓨터에서는 같은 프로젝트를 다시 실행할 수 없습니다.
- 콘텐츠 유형은 캐릭터 소개 / 굿즈 소개 / 팝업스토어 일정 / 콜라보 내용 4가지, 템플릿은 1종(Page 1), 카드는 5장 고정입니다.
- HEIC 사진은 지원하지 않습니다 (PNG·JPG·WebP만).
- Page 1 보존 확인(서명)은 채우기 **종류**만 비교하고 색상값은 비교하지 않습니다.

## 6. 향후 개선 과제 (MVP 범위 밖)

- 버튼형 실행 프로그램 (상태 파일·비대화 실행 연결)
- 본문 카드용 레이아웃(text-only 등)과 새 템플릿
- 상품 사진용 누끼 모델 선택 안내, 이미지 위치·크기 조정
- 이미지 다시 지정하기 (지금은 이전 결과를 정리해야 다시 처리 가능)
- Page 1 서명에 색상값 포함
- 공식 출처 자동 수집 범위 확대, 같은 상품 결과 재사용(캐시)
- HEIC 변환 지원

## 7. 폴더 구조

```
.claude/commands/cardnews.md     전체 파이프라인 (/cardnews)
.claude/skills/                  analyze-image, research-topic, plan-cardnews, cutout-image, write-copy, fill-figma
scripts/                         fetch_product.py, assign_images.py, cutout.py, fill_figma.py, figma/*.js
templates/                       layers.md(규격), figma-config.md(Figma 연결·테스트 기록), card-images.md, cardnews-pipeline.md
assets/characters/<캐릭터>/      공식 출처(official.md), 원본·누끼 이미지
sources.md                       공용 이미지 출처 기록
projects/YYYY-MM-DD_주제/        카드뉴스 한 편의 작업 폴더
archive/                         이전 프로젝트 보관
```
