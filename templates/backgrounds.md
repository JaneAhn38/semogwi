# backgrounds.json 규격 — 카드 배경 교체

> card-02 ~ card-05의 배경을 승인된 이미지로 바꿀 때 쓴다. 이 파일이 없는 프로젝트는 지금까지와 똑같이 템플릿 그라데이션을 쓴다.
> `slides.json` 규격은 바뀌지 않는다. `scripts/fill_figma.py validate`가 이 파일을 검사하고, fill-figma가 승인된 배경만 복제본 프레임에 넣는다.

## 1. 위치

| 파일 | 경로 | Git |
| --- | --- | --- |
| 지정 파일 | `projects/<폴더>/backgrounds.json` | 포함 |
| 배경 이미지 | `projects/<폴더>/input/backgrounds/<파일>` | **제외** (`projects/*/input/`) |
| 출처 기록 | `projects/<폴더>/sources.md` | 포함 |

## 2. 형식

```json
{
  "cards": {
    "card-02": {
      "file": "input/backgrounds/card-02-v1.png",
      "status": "승인됨",
      "origin": "temp",
      "sha256": "<파일의 SHA-256 16진수 소문자>",
      "note": "선택 메모"
    },
    "card-03": null
  }
}
```

| 필드 | 필수 | 규칙 |
| --- | --- | --- |
| `cards` | ✅ | 키는 `card-02` ~ `card-05`만. **`card-01`은 고정 표지라 지정하면 오류.** 키가 없거나 `null`이면 템플릿 그라데이션 유지 |
| `file` | ✅ | 프로젝트 폴더 기준 `input/backgrounds/` 아래 상대 경로. PNG / JPG / WebP, **정확히 1080 × 1350**, 10MB 이하 |
| `status` | ✅ | `승인 대기` / `승인됨` / `거절됨`. **`승인됨`만 통과** (나머지는 오류. 쓰지 않을 카드는 `null`) |
| `origin` | ✅ | `temp`(임시 이미지) / `ai`(AI 생성). `temp`는 폴더가 `_테스트`로 끝나지 않으면 "게시 금지" 경고 |
| `sha256` | ✅ | 승인 시점의 파일 해시. 다르면 오류 (승인 뒤 파일이 바뀌는 것을 막음) |
| `note` | 선택 | 메모 |

해시 계산:

```
py -c "import hashlib,sys;print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" <파일>
```

`sources.md`에는 카드 이미지와 같은 표 형식으로 행을 추가한다 (배치용 파일 경로 칸은 `-`). 사용 허가가 `허가됨`이 아니면 오류다.

```
| - | `projects/<폴더>/input/backgrounds/card-02-v1.png` | - | 세모귀 팀 자체 제작 (임시) | 세모귀 팀 | 허가됨 | 2026-11-06 추가 |
```

## 3. 이미지 조건

- **글자·로고·캐릭터를 넣지 않는다.** 제목·본문·출처는 텍스트 레이어로만 넣고, 캐릭터는 `main-image`로만 넣는다.
- y 900 아래(`bottom-overlay`, 제목, 본문)는 단순하게 둔다. 복잡하면 흰 글자를 읽기 어렵다.
- 위쪽 y 40 ~ 75의 `source`·`page-number` 흰 글자가 보이도록 위쪽 띠를 너무 밝게 하지 않는다.
- 한 세트의 배경은 색상·분위기를 통일하고, 장식만 조금씩 바꾼다.
- 파일은 덮어쓰지 않고 `card-02-v2.png`처럼 새 버전으로 저장한다.

## 4. Figma 적용 방식

- 새 레이어를 만들지 않고 **복제본 프레임의 채우기**를 이미지(`FILL`)로 교체한다. 6개 레이어 구조와 쌓임 순서는 그대로다.
- 원본 `Page 1`과 `card-01`의 프레임 채우기는 바꾸지 않는다.
- `upload_assets`는 호출 한 번에 `scaleMode`가 하나이므로, 배경(FILL)과 `main-image`(FIT)는 **따로 호출**한다. 절차는 `.claude/skills/fill-figma/SKILL.md` 6단계.
