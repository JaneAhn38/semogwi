---
description: 세모귀 카드뉴스 전체 실행. 주제·캐릭터·유형·참고 자료를 받아 brief → 구성안(승인) → 누끼 → 문구 → 피그마 채우기 → PNG 5장까지 순서대로 진행한다.
argument-hint: [주제] [캐릭터] [유형] [참고 자료 링크...]
---

# /cardnews

입력: $ARGUMENTS

세모귀 카드뉴스 1세트(5장)를 아래 순서로 만든다. 각 단계는 해당 Skill의 SKILL.md를 따른다. 단계마다 결과 파일을 `projects/YYYY-MM-DD_주제/`에 저장하고, 다음 단계는 그 파일을 읽어서 진행한다.

```
research-topic → plan-cardnews(승인) → cutout-image → write-copy → fill-figma
   brief.md        outline.md          cutout-check.md   slides.json    png/card-01~05.png
```

## 0. 입력 확인
- 주제, 캐릭터(`assets/characters/` 폴더 이름), 유형(캐릭터 소개 / 굿즈 소개 / 팝업스토어 일정), 참고 자료가 모두 있는지 확인한다. 없으면 물어보고 시작하지 않는다.
- 표지 원본 이미지와 그 출처(URL·저작권자·사용 허가)는 지금 받아도 되고, 3단계에서 받아도 된다.
- 시작 시각을 기록한다.
- 같은 주제 폴더에 이미 결과 파일이 있으면, 어느 단계부터 다시 할지 사용자에게 묻는다.

## 1. research-topic → brief.md
## 2. plan-cardnews → outline.md
- 구성안 표를 보여 주고 **멈춘다. 사용자가 승인하기 전에는 3단계로 넘어가지 않는다.**
- 수정 요청이 오면 해당 카드만 고쳐서 다시 보여 준다.

## 3. cutout-image → 누끼 PNG + cutout-check.md
- 승인된 outline.md의 **이미지** 열에서 이미지가 필요한 카드만 처리한다. 값이 `-`인 카드는 건너뛴다.
- **fill-figma MVP 제약으로 이미지는 card-01만** 처리한다. 다른 카드에 이미지가 계획되어 있으면 "보류"로 알리고, 그 카드의 `image`는 `""`가 된다.
- 원본 이미지나 출처 정보가 없으면 멈추고 요청한다. 사용자가 이미지 없이 진행하겠다고 하면 card-01도 건너뛴다(`image`는 `""`).
- 같은 원본·같은 설정으로 만든 누끼가 `sources.md`에 이미 있으면 새로 만들지 않고 그 경로를 쓴다.
- 출처가 `sources.md`에 기록되지 않은 이미지는 쓰지 않는다. 사용 허가가 `허가됨`이 아니면 cutout-image의 규칙대로 멈추고 확인받는다.
- 결과: `assets/characters/<캐릭터>/cutout/`의 누끼 파일, `sources.md` 행 추가, `projects/YYYY-MM-DD_주제/cutout-check.md`

## 4. write-copy → slides.json
- `image` 값은 `cutout-check.md`의 **"결과 파일 (slides.json `image`)" 칸을 그대로** 쓴다. 이 경로는 3단계에서 `sources.md`에 기록되었으므로 write-copy의 "sources.md에 기록된 이미지만" 규칙을 만족한다. 경로를 지어내지 않는다.
- 이미지가 없는 카드, 건너뛰거나 보류한 카드, card-02 ~ card-05는 `image`를 `""`로 둔다.
- `cutout-check.md`가 없거나 card-01 결과가 실패이면 card-01 `image`도 `""`로 두고 "누끼 이미지 필요(cutout-image)"라고 알린다.
- 글자 수 검사와 `py scripts/fill_figma.py validate`가 전부 통과해야 다음 단계로 간다.

## 5. fill-figma → 카드 PNG 5장
- 원본 템플릿은 건드리지 않고 복제본에서 작업한다.
- `image`가 있는 card-01은 표지 이미지를 FIT으로 넣고, `image`가 `""`인 카드는 `main-image`를 숨긴다.
- PNG는 `projects/YYYY-MM-DD_주제/png/`에 저장한다.

## 6. 최종 검수 안내
- 만든 PNG 5장의 경로와 카드별 제목을 표로 보여 준다.
- 시작부터 끝까지 걸린 시간(구성안 승인을 기다린 시간 포함)을 알린다.
- 사용자가 수정을 요청하면 해당 카드만 다시 만든다. 문구 수정은 4단계(write-copy)부터, 이미지 교체는 3단계(cutout-image)부터 한다.
- 다시 만들 때 같은 이름의 Figma 페이지나 `png/`의 PNG가 이미 있으면 fill-figma가 멈춘다. 지우거나 덮어쓰지 말고 사용자에게 어떻게 할지 묻는다.

## 규칙
- 아직 없는 Skill이 있으면 그 단계에서 멈추고, 어떤 Skill이 없는지 알린다. 다른 방법으로 대신하지 않는다.
- 참고 자료에 없는 내용을 만들지 않는다.
