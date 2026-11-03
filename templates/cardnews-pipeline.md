# 세모귀 카드뉴스 파이프라인 — 실행 구조 (시연 프로그램 연결 기준)

> 최종 목표: 사용자가 **주제 / 사진 / 공식 상품 URL** 중 하나를 넣고 "카드뉴스 생성"을 누르면 PNG 5장이 만들어진다.
> 이 문서는 그 버튼이 `/cardnews` 파이프라인을 부를 때 필요한 **입력값, 실행 단계, 사용자 승인 지점, 출력 경로, 진행 상태 판정**을 정리한다.
> 실행 규칙의 기준은 `.claude/commands/cardnews.md`와 각 Skill의 SKILL.md다. 이 문서와 다르면 SKILL.md를 따른다.

---

## 1. 입력값

| 입력 방식 | 필수 값 | 선택 값 | 판단 기준 |
| --- | --- | --- | --- |
| 주제 입력 | 주제, 캐릭터(`assets/characters/` 폴더 이름), 유형, 참고 자료(공식 링크 또는 붙여 넣은 공식 게시물) | 표지 원본 이미지 + 출처·사용 허가 | 아래 두 경우가 아니면 |
| 사진 입력 | 이미지 파일 1장 이상 (`.png .jpg .jpeg .webp`) | 유형, 참고 자료, 사진을 카드 이미지로 쓸지 | 입력에 이미지 파일 경로가 있음 |
| 공식 상품 URL 입력 | `https://chiikawamarket.jp/…/products/<상품>` | 유형 | 공식 쇼핑몰(`fetch_product.py`의 `OFFICIAL_HOSTS`) 상품 주소 |

- 유형은 **캐릭터 소개 / 굿즈 소개 / 팝업스토어 일정 / 콜라보 내용** 네 가지다. 사진·URL 입력에서는 analyze-image가 제안하고 사용자가 확인한다.
- 카드에는 **`[공식]` 항목만** 쓴다. 공식 출처가 부족하면 파이프라인이 멈추고 무엇이 부족한지 알린다 (빈칸을 추정으로 채우지 않음).

## 2. 실행 단계

| 단계 | 담당 | 읽는 것 | 만드는 것 (`projects/YYYY-MM-DD_주제/`) | 자동 / 멈춤 |
| --- | --- | --- | --- | --- |
| 0-U | `scripts/fetch_product.py` (URL 입력만) | 상품 URL | `product.json`, `product-info.md`, `input/NN_*.jpg` | 자동. 종료 코드 0이 아니면 멈춤 |
| 0-A | analyze-image (사진·URL 입력만) | `input/`, `product-info.md` | `image-analysis.md` | **멈춤 ① 분석 확인** |
| 1 | research-topic | 주제 입력값 또는 `image-analysis.md`(확인됨), 참고 자료 | `brief.md`, `references/` | 자동 (공식 정보 부족 시 멈춤) |
| 2 | plan-cardnews | `brief.md`, `image-analysis.md` | `outline.md` | **멈춤 ② 구성안 승인** |
| 3-U | **사용자 (업로드 화면)** | `outline.md` (이미지 권장 안내) | `input/cards/<파일>`, `card-images.json` | **멈춤 ③ 이미지 지정** |
| 3 | `scripts/assign_images.py` (cutout-image) | `card-images.json`, `input/cards/` | `input/placed/img-NN.*`, `sources.md`(프로젝트), `cutout-check.md`, `card-images-result.json` | 자동. 종료 코드 1·2면 멈춤, 3이면 차단·실패 카드 알림 |
| 4 | write-copy | `outline.md`, `brief.md`, `cutout-check.md` | `slides.json`, `copy-check.md` | 자동 (validate 오류 시 멈춤) |
| 5 | fill-figma | `slides.json` | Figma 페이지 `세모귀_<폴더>`, `png/card-01.png ~ card-05.png` | 자동 (경고 확인 필요 시 멈춤) |

## 3. 사용자 승인 지점

**필수 (항상 멈춤)**

| 지점 | 언제 | 사용자가 보는 것 | 승인 기록 |
| --- | --- | --- | --- |
| ① 분석 확인 | 사진·URL 입력, 0-A 끝 | 확인된 요소, 공식 상품 정보, 식별 결과(확신도), 추정, 제안(주제·유형·중심 대상·키워드·카드 이미지 사용 여부) | `image-analysis.md` `상태: 확인됨` |
| ② 구성안 승인 | 모든 입력, 2단계 끝 | 카드 5장 구성표, 뺀 내용, (사진·URL) 이미지 관련성 | `outline.md` `상태: 승인됨` |
| ③ 이미지 지정 | 모든 입력, 구성안 승인 뒤 | 카드별 업로드 칸 (이미지 없음 선택 가능), 누끼 여부, 출처·저작권자·사용 권한 입력 | `card-images.json` 생성 (이미지를 하나도 안 쓰면 모든 카드 `null`) |

**조건부 (해당할 때만 멈춤)**

| 지점 | 조건 | 기록 |
| --- | --- | --- |
| 입력 부족 | 주제 입력에 필수 값이 없음 | - |
| URL 가져오기 실패 | `fetch_product.py` 종료 코드 1·2·3 | 출력 메시지 |
| 공식 정보 부족 | `[공식]` 항목만으로 5장을 못 채움 | `brief.md` "확인 필요" |
| 카드 이미지 허가 | 지정 이미지의 사용 권한이 `허가됨`이 아님 → 그 카드는 이미지 없이 진행할지 다시 지정할지 확인 | 프로젝트 `sources.md`, `cutout-check.md` |
| 이미지 처리 실패 | HEIC 등 지원하지 않는 형식, 10MB 초과, 누끼 결과 검사 실패 | `cutout-check.md` |
| 이미지 해상도 | FIT 1.25배 초과 확대 | validate 경고 |
| 덮어쓰기 방지 | 같은 이름의 Figma 페이지나 `png/`의 PNG가 이미 있음 | - |
| 원본 보존 | Page 1 서명 불일치 | fill-figma 보고 |

## 4. 출력 경로

| 출력 | 경로 | Git |
| --- | --- | --- |
| 최종 PNG 5장 | `projects/YYYY-MM-DD_주제/png/card-01.png ~ card-05.png` (1080 × 1350) | 포함 (폴더 이름이 `_테스트`로 끝나면 제외) |
| Figma 결과 페이지 | 파일 `b7ersPQ6u13fVoCPjuwUs9`의 `세모귀_YYYY-MM-DD_주제` | - |
| 중간 산출물 | 같은 폴더의 `image-analysis.md`, `brief.md`, `outline.md`, `cutout-check.md`, `slides.json`, `copy-check.md`, `product.json`, `product-info.md` | 포함 |
| 입력 사진·상품 이미지 | 같은 폴더의 `input/` | **제외** |
| 카드 업로드 이미지·배치용 이미지 | 같은 폴더의 `input/cards/`, `input/placed/` | **제외** |
| 카드 이미지 출처 기록 | 같은 폴더의 `sources.md`, `card-images.json`, `card-images-result.json` | 포함 |
| 사용자 사진에서 만든 누끼 | `assets/characters/<캐릭터>/original|cutout/user-*` | **제외** |

## 5. 진행 상태 판정 (다시 시작할 때)

각 단계는 결과를 파일로 남기므로, 프로그램은 폴더만 보고 **어디까지 진행됐고 무엇을 기다리는지** 알 수 있다.

| 폴더 상태 | 다음 동작 |
| --- | --- |
| `product.json`만 있음 (URL) / `input/`만 있음 (사진) | 0-A analyze-image |
| `image-analysis.md` `상태: 확인 대기` | **① 승인 대기** |
| `image-analysis.md` 확인됨, `brief.md` 없음 | 1 research-topic |
| `outline.md` `상태: 승인 대기` | **② 승인 대기** |
| `outline.md` 승인됨, `card-images.json` 없음 | **③ 이미지 지정 대기** |
| `card-images.json` 있음, `cutout-check.md` 없음 | 3 `assign_images.py` |
| `cutout-check.md` 있음, `slides.json` 없음 | 4 write-copy |
| `slides.json` 있음, `png/` 없음 | 5 fill-figma |
| `png/card-01 ~ 05.png` 모두 있음 | 완료 |

## 6. 버튼형 프로그램 연결 방법 (설계안, 아직 구현하지 않음)

시연 프로그램은 Claude Code를 **화면 뒤에서 호출**하고, 사람은 버튼만 누른다. 승인 지점에서 끊어 부르는 방식을 권장한다.

```
[카드뉴스 생성] ─▶ 호출 1: 입력값으로 /cardnews 시작 ──▶ ① 또는 ②에서 멈춤
                         │                                   │
                         ▼                                   ▼
                  폴더 상태(5장) 읽기              화면에 image-analysis.md / outline.md 표시
                                                             │
[승인] ─────────▶ 호출 2: 같은 폴더로 이어서 진행 ──▶ 다음 승인 지점 또는 완료
                                                             │
                                                             ▼
                                                   png/card-01~05.png 표시
```

1. **호출**: Claude Code의 비대화(print) 모드로 `/cardnews <입력값>`을 실행한다. 같은 대화를 이어 가거나, 새로 호출하면서 프로젝트 폴더를 넘기고 5장의 상태 판정으로 이어서 진행한다.
2. **승인**: 프로그램이 `image-analysis.md`·`outline.md`를 보여 주고, 사용자가 [승인]을 누르면 그 파일의 `상태:` 줄을 승인값으로 바꾸고 다음 호출을 한다. 수정 요청은 텍스트로 받아 같은 단계에 넘긴다.
3. **완료 판정**: `png/card-01.png ~ card-05.png`가 모두 있고 `verify-png`가 통과하면 완료다.

**구현 전에 확인할 것**

- [ ] 비대화 모드에서 프로젝트 명령(`/cardnews`)과 Skill이 그대로 동작하는지
- [ ] 비대화 모드에서 Figma MCP 연결(로그인)과 도구 사용 권한(`py`, `curl`, Figma 도구)을 미리 허용하는 방법
- [ ] 승인 지점에서 멈췄다는 것을 프로그램이 확실히 알 수 있도록, 멈출 때마다 상태 파일(예: `projects/<폴더>/status.json` — 단계, 대기 이유, 다음 동작)을 남길지
- [ ] `/cardnews`가 "폴더를 받아 이어서 진행"하는 입력을 정식으로 받도록 할지 (지금은 "같은 주제 폴더에 결과가 있으면 어느 단계부터 할지 묻는다")
- [ ] 한 번 실행에 걸리는 시간 (11-03 통합 테스트: 승인 대기 제외 약 6분)
