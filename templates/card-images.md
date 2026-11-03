# card-images.json 규격 — 카드별 이미지 지정

> 사용자가 구성안 승인 뒤 card-01 ~ card-05에 쓸 이미지를 직접 업로드하고 지정한 결과다.
> 시연 프로그램(업로드 화면)이 만들고, `scripts/assign_images.py`가 읽어 처리한다.

## 1. 위치

| 파일 | 경로 | Git |
| --- | --- | --- |
| 지정 파일 | `projects/<폴더>/card-images.json` | 포함 |
| 업로드 원본 | `projects/<폴더>/input/cards/<파일>` | **제외** (`projects/*/input/`) |
| 배치용 이미지 | `projects/<폴더>/input/placed/img-NN.<확장자>` (`assign_images.py`가 만듦) | **제외** |
| 출처 기록 | `projects/<폴더>/sources.md` (프로젝트별) | 포함 |
| 처리 결과 | `projects/<폴더>/cutout-check.md`, `card-images-result.json` | 포함 |

## 2. 형식

```json
{
  "character": "chiikawa",
  "cards": {
    "card-01": {
      "file": "input/cards/coin-front.jpg",
      "cutout": false,
      "source": "사용자 촬영 (2026-11-05)",
      "owner": "상품 디자인 ©nagano / chiikawa committee",
      "permission": "허가됨",
      "note": "팀 내부 시연용 사용 허가 확인"
    },
    "card-02": null,
    "card-03": {
      "file": "input/cards/chiikawa.png",
      "cutout": true,
      "cutout_model": "isnet-anime",
      "source": "치이카와 공식 X (게시물 URL 미기록)",
      "owner": "확인 필요",
      "permission": "허가됨"
    },
    "card-04": { "file": "input/cards/coin-front.jpg", "cutout": false, "source": "사용자 촬영 (2026-11-05)", "owner": "상품 디자인 ©nagano / chiikawa committee", "permission": "허가됨" }
  }
}
```

| 필드 | 필수 | 규칙 |
| --- | --- | --- |
| `character` | 선택 | `assets/characters/` 폴더 이름. 출처 기록의 캐릭터명 칸에 쓴다 |
| `cards` | ✅ | `card-01` ~ `card-05`만 키로 쓴다. **키가 없거나 `null`이면 이미지 없음** → `image: ""` → `main-image` 숨김 |
| `cards.*.file` | ✅ | 프로젝트 폴더 기준 `input/cards/` 아래 경로. PNG / JPG / WebP |
| `cards.*.cutout` | 선택 | `false`(기본) = FIT으로 그대로 배치, `true` = `cutout.py`로 배경 제거 후 배치 |
| `cards.*.cutout_model` | 선택 | `isnet-anime`(기본, 캐릭터 그림) / `u2net`(사진) / `u2netp` / `bria-rmbg` |
| `cards.*.source` | ✅ (권장) | 이미지 출처. 없으면 `확인 필요` |
| `cards.*.owner` | ✅ (권장) | 저작권자. 모르면 `확인 필요` |
| `cards.*.permission` | ✅ | `허가됨` / `허가 안 됨` / `확인 필요`. **없으면 `확인 필요`** |
| `cards.*.note` | 선택 | 허가 범위·확인 날짜 등 |

- **같은 이미지를 여러 카드에** 지정해도 된다. 같은 파일·같은 처리 방식은 한 번만 만들고 함께 쓴다.
- 카드마다 **서로 다른 이미지**를 지정해도 된다.

## 3. 처리 규칙 (`assign_images.py`)

| 상황 | 처리 | 카드 `image` |
| --- | --- | --- |
| 이미지 없음 (`null`·키 없음) | 건너뜀 | `""` (main-image 숨김) |
| 사용 권한이 `허가됨`이 아님 | **차단** — 배치용 이미지를 만들지 않음. 출처 기록에는 "사용 안 함"으로 남김 | `""` |
| FIT (기본) | EXIF 회전 정보가 없으면 원본 바이트 그대로 복사, 있으면 **회전을 보정한 사본** 저장 (원본은 보존) | `projects/<폴더>/input/placed/img-NN.<확장자>` |
| 누끼 (`cutout: true`) | `cutout.py --max-size 1024 --model <모델>` (EXIF 회전 반영). 결과 검사: 투명 0.05 ~ 0.95, 불투명(알파 240 이상) 0.05 이상 | `…/img-NN-cutout.png` |
| HEIC / HEIF / AVIF / GIF 등 | 실패 — "PNG, JPG, WebP로 변환해서 다시 지정" 안내 | `""` |
| 배치용 이미지가 10MB 초과 | 실패 — Figma 업로드 한도 | `""` |
| FIT 배율 > 1 | 경고 (1.25배 초과는 fill-figma가 진행 전 확인) | 그대로 |

- **업로드했다는 사실만으로 사용 권한이 있다고 보지 않는다.** `permission`은 사용자가 명시적으로 `허가됨`을 골라야 한다.
- 이미 `input/placed/`에 파일이 있거나 `cutout-check.md`가 있으면 덮어쓰지 않고 종료한다 (종료 코드 2). 이미지를 바꾸려면 이전 결과를 정리한 뒤 다시 실행한다.
- fill_figma.py validate는 프로젝트 `input/` 아래 이미지의 출처를 **프로젝트 sources.md**에서 찾고, 사용 허가가 `허가됨`이 아니면 **오류**로 멈춘다.

## 4. 종료 코드

| 코드 | 뜻 |
| --- | --- |
| 0 | 지정된 카드 모두 처리 성공 (경고는 있을 수 있음) |
| 1 | card-images.json 규격 오류 — 아무것도 저장하지 않음 |
| 2 | 이미 처리 결과가 있음 — 덮어쓰지 않음 |
| 3 | 결과는 저장했지만 일부 카드가 차단(권한 미확인)되었거나 처리에 실패함 — 사용자에게 알리고, 그 카드는 이미지 없이 진행할지 다시 지정할지 묻는다 |
