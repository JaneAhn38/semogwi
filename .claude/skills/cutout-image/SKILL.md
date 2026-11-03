---
name: cutout-image
description: 세모귀 카드뉴스 이미지 준비 단계. 사용자가 card-01 ~ card-05에 직접 지정한 이미지(card-images.json)를 scripts/assign_images.py로 처리하거나(FIT 기본, 선택 시 누끼), 승인된 구성안(outline.md)에서 이미지가 필요한 카드를 찾아, 사용자가 준 원본 이미지의 출처·사용 허가를 sources.md에 기록하고 scripts/cutout.py로 배경을 제거한 투명 PNG(누끼)를 만든다. 이미 투명하거나 누끼가 필요 없는 이미지는 그대로 복사(-asis)한다. "누끼 따줘", "배경 지워줘", "표지 이미지 준비해줘", /cardnews의 이미지 단계에 쓴다.
---

# cutout-image: 원본 이미지 → 누끼 PNG + sources.md

카드에 넣을 이미지를 **준비**하는 단계다. 원본을 받아 출처를 기록하고, 배경을 지운 투명 PNG를 `cutout/` 폴더에 만든다. 결과 경로는 write-copy가 slides.json의 `image`에 그대로 쓴다. **이미지를 새로 그리거나, 웹에서 내려받거나, 원본을 고치는 단계가 아니다.**

기준 문서: [`sources.md`](../../../sources.md) (출처 기록), [`templates/layers.md`](../../../templates/layers.md) (slides.json `image` 규격), [`templates/figma-config.md`](../../../templates/figma-config.md) 6장 (표지 해상도)

## 카드별 이미지 지정 (기본 방식)

사용자가 구성안 승인 뒤 카드별 이미지를 직접 업로드·지정했으면 (`projects/<폴더>/card-images.json`이 있으면) 아래 수동 절차 대신 스크립트로 처리한다. 규격은 [`templates/card-images.md`](../../../templates/card-images.md).

```
py scripts/assign_images.py projects/<폴더>
```

| 종료 코드 | 뜻 | 처리 |
| --- | --- | --- |
| 0 | 지정된 카드 모두 처리 | `cutout-check.md`가 생김 → write-copy로 |
| 1 | card-images.json 규격 오류, 아무것도 저장 안 함 | 출력된 오류를 보고하고 다시 지정받는다 |
| 2 | 이미 처리 결과가 있음 | 덮어쓰지 않는다. 기존 결과를 쓸지 묻는다 |
| 3 | 일부 카드 차단(사용 권한 미확인)·실패 | 그 카드는 `image: ""`로 저장됨. 이미지 없이 진행할지, 권한을 확인해 다시 지정할지 사용자에게 묻는다 |

- FIT이 기본이고, `"cutout": true`인 카드만 `cutout.py`로 누끼를 만든다. 같은 이미지는 한 번만 처리해 여러 카드가 함께 쓴다.
- 업로드 원본은 `input/cards/`, 배치용 이미지는 `input/placed/`에 있어 Git에 올라가지 않는다. EXIF 회전이 있으면 원본은 그대로 두고 배치용 사본만 회전을 보정한다.
- 출처·저작권자·사용 권한은 **프로젝트 sources.md**에 기록된다 (공용 `sources.md`가 아님). `허가됨`이 아닌 이미지는 카드에 쓰지 않는다. 업로드했다는 사실만으로 허가로 보지 않는다.
- PNG·JPG·WebP만 받는다. HEIC 등은 변환해서 다시 지정하라고 안내한다.
- 아래 "입력" 이하의 수동 절차는 card-images.json 없이 원본 사진을 받아 처리할 때(사진 입력 등)에 쓴다.

## 입력

| 항목 | 필수 | 예시 |
| --- | --- | --- |
| 프로젝트 폴더 | ✅ | `projects/2026-11-05_치이카와-캐릭터-소개/` |
| 캐릭터 | ✅ | `chiikawa` (`assets/characters/` 폴더 이름) |
| 원본 이미지 | ✅ (이미지가 필요한 카드마다) | 사용자가 준 파일 경로 |
| 출처 정보 | ✅ (원본마다) | 출처 URL, 저작권자, 사용 허가 여부 |
| 처리 방식 | 선택 | `cutout`(기본) / `as-is`(누끼 없이 그대로 사용) |

- 이미지가 필요한 카드는 `outline.md`(`상태: 승인됨`)의 **이미지** 열에서 찾는다. 값이 `-`이거나 비어 있는 카드는 **건너뛴다**.
  - outline.md가 없거나 승인 전이면, 사용자에게 카드와 이미지 목록을 직접 받는다. 추측해서 정하지 않는다.
- 이미지는 card-01 ~ card-05 어느 카드에나 넣을 수 있다.
- 원본은 사용자가 파일로 준다. **웹·X에서 직접 내려받지 않는다.** 원본이 없으면 진행하지 말고 요청한다.
- 출처 URL은 사용자가 준 것만 쓴다. 정확한 URL이 없으면 지어내지 말고 `<출처 이름> (게시물 URL 미기록)`으로 쓴다. 모르는 항목은 `확인 필요`로 둔다. 캐릭터 공식 계정은 `assets/characters/<캐릭터>/official.md`를 참고한다.

## 출력

| 산출물 | 규격 |
| --- | --- |
| 누끼 | `assets/characters/<캐릭터>/cutout/<캐릭터>-<YYYYMMDD>-<nn>.png` — 투명 배경 RGBA PNG, 긴 변 최대 1024 |
| 그대로 사용(as-is) | `assets/characters/<캐릭터>/cutout/<캐릭터>-<YYYYMMDD>-<nn>-asis.<원본 확장자>` — 원본과 바이트가 같은 복사본 |
| 원본 보관 | `assets/characters/<캐릭터>/original/<캐릭터>-<YYYYMMDD>-<nn>.<확장자>` — 원본이 이미 `original/`에 있으면 그 파일을 그대로 쓴다 |
| sources.md | 이미지마다 **행 1개 추가** (아래 "sources.md 기록") |
| 검사 기록 | `projects/<폴더>/cutout-check.md` |

- `YYYYMMDD`는 작업한 날짜, `nn`은 같은 캐릭터·날짜 안에서 `01`부터 붙이는 두 자리 번호다. `cutout/`과 `original/`에 이미 있는 번호는 쓰지 않는다.
- 이름을 `test`로 시작하지 않는다. `.gitignore`가 `test.*`, `test-*`를 테스트 이미지로 보고 제외한다.
- 원본·누끼·as-is 파일은 같은 `<캐릭터>-<YYYYMMDD>-<nn>`을 써서 짝을 알 수 있게 한다.

### 사용자 제공 사진 (Git 제외)

원본이 **사용자 제공 사진**이면 (`projects/*/input/`에 있는 사진, 또는 사용자가 직접 찍었거나 가진 사진이라고 한 것) 세 파일 이름 모두 앞에 **`user-`**를 붙인다.

| 산출물 | 이름 |
| --- | --- |
| 원본 보관 | `original/user-<캐릭터>-<YYYYMMDD>-<nn>.<확장자>` |
| 누끼 | `cutout/user-<캐릭터>-<YYYYMMDD>-<nn>.png` |
| 그대로 사용(as-is) | `cutout/user-<캐릭터>-<YYYYMMDD>-<nn>-asis.<원본 확장자>` |

- `.gitignore`가 `assets/characters/*/original/user-*`, `assets/characters/*/cutout/user-*`를 제외하므로 저장소에 올라가지 않는다. 로컬에서는 그대로 있어서 write-copy·fill-figma가 평소처럼 쓴다.
- 파일을 만든 직후 `git check-ignore -v <경로>`로 **제외되는지 확인한다.** 제외되지 않으면(출력이 없으면) 다음 단계로 가지 말고 보고한다.
- `nn` 번호는 `user-`가 없는 파일과 함께 센다 (같은 날짜·캐릭터 안에서 겹치지 않게).
- sources.md의 원본 출처 URL 칸에는 `사용자 제공 사진`이라고 쓰고, 사용 허가는 사용자에게 확인받은 값을 쓴다.
- 반대로, 사용자 사진이 아닌 정상 콘텐츠 이미지는 이름을 `user-`로 시작하지 않는다.
- **공식 상품 URL에서 가져온 이미지**(`product.json`의 `usage.card_image`가 `미승인`)는 카드 이미지로 쓰지 않는다. 사용자가 카드 사용을 승인한 경우에만 처리하고, sources.md 원본 출처 URL 칸에 그 이미지 URL, 사용 허가에 사용자 확인 값을 적는다. 이 이미지도 `input/`에서 왔으므로 `user-` 이름 규칙을 따른다.

## 도구

| 용도 | 도구 |
| --- | --- |
| 배경 제거 | `py scripts/cutout.py <원본> <누끼 경로> --max-size 1024` (프로젝트 루트에서 실행) |
| 이미지 검사 | 아래 "이미지 검사 명령" (읽기 전용) |
| 출처 행 확인 | 아래 "sources.md 기록"의 확인 명령 (fill-figma validate와 같은 함수) |
| 파일 복사 | `cp -n` (덮어쓰지 않음) 후 해시 비교 |

- `scripts/cutout.py`는 **고치지 않고 그대로 쓴다.** 필요한 옵션은 명령줄로 넘긴다.
- `cutout.py`는 출력 파일이 있으면 **묻지 않고 덮어쓰고**, 출력 경로를 생략하면 원본 옆(`original/`)에 `<이름>-cutout.png`로 저장한다. 그래서 **출력 경로를 항상 지정하고, 실행 전에 그 경로가 없는지 확인한다.**
- `--max-size 1024`를 항상 넘긴다. 기본값 512로 만들면 main-image(908×780)에서 확대되어 흐려진다. `--max-size`는 줄이기만 하므로 원본이 작으면 원본 크기 그대로 나온다.
- 모델은 기본값(`isnet-anime`, 캐릭터 일러스트용)을 쓴다. 다른 모델(`u2net` 등)은 사용자가 요청했을 때만 `--model`로 바꾼다.

### 이미지 검사 명령

원본과 결과물 모두 이 명령으로 확인한다 (파일을 바꾸지 않음).

```
py -X utf8 -c "import sys,json; from PIL import Image; p=sys.argv[1]; im=Image.open(p); w,h=im.size; t=im.mode in ('RGBA','LA','PA') or 'transparency' in im.info; r=(im.convert('RGBA').getchannel('A').histogram()[0]/(w*h)) if t else 0.0; print(json.dumps({'file':p,'format':im.format,'width':w,'height':h,'mode':im.mode,'alpha':t,'transparentRatio':round(r,3),'fitScale':round(min(908/w,780/h),2)},ensure_ascii=False))" <파일>
```

| 값 | 뜻 |
| --- | --- |
| `format` | 확장자가 아니라 **파일 내용**으로 판별한 실제 형식 (예: `.png`인데 `WEBP`일 수 있음) |
| `alpha` | 알파 채널이 있는지. RGBA여도 투명한 픽셀이 없을 수 있으므로 `transparentRatio`로 판단한다 |
| `transparentRatio` | 완전히 투명한 픽셀 비율 (0 ~ 1) |
| `fitScale` | main-image(908×780)에 FIT으로 넣을 때 배율. **1보다 크면 확대되어 흐려진다** |

### 알파 분포 명령

cutout 결과물에 함께 돌린다 (파일을 바꾸지 않음).

```
py -X utf8 -c "import sys,json; from PIL import Image; p=sys.argv[1]; a=Image.open(p).convert('RGBA').getchannel('A'); h=a.histogram(); n=sum(h); print(json.dumps({'file':p,'maxAlpha':max(v for v in range(256) if h[v]),'opaqueRatio':round(sum(h[240:])/n,3),'edgeRatio':round(sum(h[1:10])/n,3)},ensure_ascii=False))" <파일>
```

| 값 | 뜻 |
| --- | --- |
| `opaqueRatio` | 알파 **240 이상**인 픽셀 비율 = 화면에서 불투명하게 보이는 캐릭터 영역 |
| `edgeRatio` | 알파 **1 ~ 9**인 픽셀 비율 = 거의 투명한 가장자리 번짐. **참고 정보**로만 기록한다 |
| `maxAlpha` | 가장 큰 알파값 |

- `isnet-anime`은 캐릭터 영역의 알파가 255가 아니라 **254 근처**로 나오는 경우가 많다. 알파 255가 없거나 아주 적다는 이유만으로 실패 처리하지 않는다. 불투명 여부는 `opaqueRatio`로 판단한다.

## 절차

각 단계가 실패하면 **그 자리에서 멈추고** 아래 "오류 처리"에 따라 보고한다. 이미지가 여러 장이면 1~6단계를 이미지마다 반복한다.

1. **대상 카드 정리**: outline.md(또는 사용자 입력)에서 이미지가 필요한 카드만 고른다. 이미지가 없는 카드는 목록에 "건너뜀"으로 남긴다.
2. **출처·사용 허가 확인 (처리 전)**: 원본마다 출처 URL, 저작권자, 사용 허가 여부를 받는다.
   - `허가 안 됨`이면 **중단**한다.
   - `허가됨`이 아닌데(`확인 필요` 등) 프로젝트 폴더 이름이 `_테스트`로 끝나지 않으면 **멈추고 확인받는다**.
3. **원본 확인 (읽기 전용)**: 원본 파일이 있는지, 이미지 검사 명령으로 형식·크기·투명도를 본다.
   - `cutout.py`가 받는 형식은 `.png .jpg .jpeg .webp .bmp`다. 그 밖의 형식이면 중단한다. 확장자와 실제 형식이 다르면 보고에 적는다.
   - 원본이 `original/` 밖에 있으면 `cp -n`으로 `original/<캐릭터>-<YYYYMMDD>-<nn>.<확장자>`에 복사하고 해시가 같은지 확인한다. 사용자가 준 원래 파일은 옮기거나 지우지 않는다.
4. **처리 방식 결정**:
   - `transparentRatio`가 **0.05 이상**이면 이미 배경이 지워진 이미지로 보고 **재처리하지 않는다** → as-is.
   - 사용자가 `as-is`를 지정했거나, 배경까지 보여야 하는 이미지(굿즈 사진, 팝업 포스터 등)라고 했으면 → as-is.
   - 그 밖에는 → cutout. 배경을 지울지 애매하면 사용자에게 묻는다.
5. **결과물 만들기 (덮어쓰기 방지)**: 출력 경로를 정하고 **그 경로에 파일이 없는지 먼저 확인한다.** 있으면 다음 번호를 쓴다.
   - **중복 검사**: sources.md에서 같은 원본 경로의 행을 찾아 비고에 적힌 처리 설정(모델, `--max-size`, as-is 여부)을 본다.
     - 원본과 설정이 **모두 같은** 결과물이 있으면 새로 만들지 말고 그 경로를 알려 준다.
     - 원본이 같아도 모델이나 `--max-size`가 **다르면** 새 번호로 새 누끼를 만든다. 기존 결과물은 그대로 둔다.
     - 비고에 설정이 적혀 있지 않은 행은 비교할 수 없으므로, 새로 만들지 사용자에게 묻는다.
   - cutout:
     ```
     py scripts/cutout.py assets/characters/<캐릭터>/original/<원본> assets/characters/<캐릭터>/cutout/<캐릭터>-<YYYYMMDD>-<nn>.png --max-size 1024
     ```
   - as-is (원본을 고치지 않고 복사만):
     ```
     cp -n <원본> assets/characters/<캐릭터>/cutout/<캐릭터>-<YYYYMMDD>-<nn>-asis.<확장자>
     ```
     복사 뒤 원본과 해시가 같은지 확인한다.
6. **결과 확인**: 결과물에 이미지 검사 명령과 (cutout이면) 알파 분포 명령을 돌린다.
   - cutout 결과는 `format: PNG`, `mode: RGBA`, 긴 변이 `min(원본 긴 변, 1024)`여야 한다.
   - `transparentRatio`가 **0.05 미만**이면 배경이 거의 안 지워진 것이고, **0.95 초과**면 캐릭터까지 지워진 것이다. 둘 다 실패로 보고한다. 결과 파일은 지우지 않는다.
   - `opaqueRatio`가 **0.05 미만**이면 캐릭터까지 반투명해진 것이므로 실패로 보고한다. 알파 255가 없는 것은 실패가 아니다 (isnet-anime은 254 근처로 나옴).
   - `edgeRatio`(가장자리 알파 1 ~ 9)는 **참고 정보**로 cutout-check.md와 보고에 적는다. 이 값만으로 실패 처리하지 않는다. 결과물을 직접 볼 때 어두운 배경에서 옅은 번짐으로 보이는지 함께 확인한다.
   - `fitScale`이 1보다 크면 경고한다. 원본도 작아서 생긴 문제면 "더 큰 원본 필요"라고 알린다. 이미지를 임의로 확대하지 않는다.
   - **결과물을 직접 열어 본다** (Read 도구로 이미지 확인). 캐릭터 일부가 잘려 나갔거나 가장자리에 배경이 남았으면 보고에 적는다.
7. **sources.md 기록**: 이미지마다 행을 하나 추가하고, 확인 명령으로 제대로 읽히는지 본다 (아래 "sources.md 기록").
8. **검사 기록**: `projects/<폴더>/cutout-check.md`에 아래 "cutout-check.md 형식"대로 쓴다.
9. **보고**: 아래 "보고 형식"대로 짧게 알린다. 다음 단계(write-copy)는 자동으로 시작하지 않는다.

## sources.md 기록

`sources.md`의 "이미지 목록" 표에 **행을 추가만** 한다. 다른 사람이 쓴 행이나 다른 이미지의 행은 고치지 않는다.

```
| 치이카와 | `assets/characters/chiikawa/original/chiikawa-20261105-01.png` | `assets/characters/chiikawa/cutout/chiikawa-20261105-01.png` | https://x.com/ngnchiikawa/status/... | 나가노 | 허가됨 | 2026-11-05 추가. isnet-anime, --max-size 1024 → 869×1024 |
```

- 열 순서: 캐릭터명 | 원본 파일 경로 | 누끼 제거 파일 경로 | 원본 출처 URL | 저작권자 | 사용 허가 여부 | 비고. 경로는 백틱으로 감싼다.
- 사용 허가 여부는 `허가됨` / `허가 안 됨` / `확인 필요` 중 하나를 **정확히** 쓴다. fill-figma는 `허가됨`일 때만 경고 없이 쓴다.
- as-is는 누끼 경로 칸에 `-asis` 파일 경로를 쓰고, 비고에 `누끼 안 함 (이미 투명 / 배경 유지)`처럼 이유를 적는다.
- 비고에는 작업 날짜, 처리 방식(모델·`--max-size` 또는 as-is), 결과 크기를 적는다.
- 확인 명령 (fill-figma validate가 쓰는 함수):
  ```
  py -X utf8 -c "import sys; sys.path.insert(0,'scripts'); from fill_figma import find_source_row; print(find_source_row(sys.argv[1]))" <누끼 경로>
  ```
  `None`이 나오거나 사용 허가 값이 다르면 행 형식을 고친다.

## cutout-check.md 형식

```markdown
# 누끼 검사 — <프로젝트 폴더 이름>

- 작업일: YYYY-MM-DD
- 캐릭터: chiikawa

| 카드 | 원본 | 처리 | 결과 파일 (slides.json `image`) | 크기 | 투명 비율 | 불투명 비율 | 가장자리(알파 1~9, 참고) | FIT 배율 | 사용 허가 | 결과 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| card-01 | original/chiikawa-20261105-01.png (WEBP 2000×2356) | cutout | `assets/characters/chiikawa/cutout/chiikawa-20261105-01.png` | 869×1024 | 0.60 | 0.31 | 0.043 | ×0.76 | 허가됨 | 통과 |
| card-02 | - | 건너뜀 (이미지 없음) | `""` | - | - | - | - | - | - | - |
```

- as-is 결과는 불투명 비율·가장자리 칸에 `-`를 쓴다.

- "결과 파일" 칸의 경로를 write-copy가 slides.json `image`에 그대로 쓴다. 이미지가 없는 카드는 `""`다.

## 규칙

- [ ] **`scripts/cutout.py`를 고치지 않는다.** 옵션은 명령줄로만 넘긴다.
- [ ] **기존 파일을 덮어쓰지 않는다.** 출력 경로가 이미 있으면 새 번호를 쓴다. 출력 경로를 생략하지 않는다.
- [ ] **원본을 고치거나 옮기거나 지우지 않는다.** 복사는 `cp -n`으로 하고 해시를 확인한다.
- [ ] 이미지가 없는 카드는 건너뛴다. 빈 자리를 채우려고 이미지를 고르거나 만들지 않는다.
- [ ] 이미 투명한 이미지(`transparentRatio` ≥ 0.05)와 누끼가 필요 없는 이미지는 `cutout.py`로 다시 처리하지 않고 as-is로 복사한다.
- [ ] 이미지를 확대·보정·잘라내기 하지 않는다. 해상도가 부족하면 경고만 한다.
- [ ] 웹·X에서 이미지를 직접 내려받지 않는다. 출처 URL을 지어내지 않는다.
- [ ] 사용 허가가 `허가됨`이 아닌 이미지는 테스트(`_테스트` 폴더)에만 쓰고 게시하지 않는다. `허가 안 됨`은 쓰지 않는다.
- [ ] sources.md에는 행을 추가만 한다. 다른 행은 고치지 않는다.
- [ ] slides.json, outline.md, 다른 Skill, Figma 템플릿은 고치지 않는다.
- [ ] 오류가 나면 다른 방법으로 바꿔 시도하지 않는다 (예: 다른 모델로 자동 전환, 이미지 축소 후 재시도). 원인을 보고하고 지시를 기다린다.
- [ ] 사용자 제공 사진에서 나온 파일은 이름 앞에 `user-`를 붙이고, `git check-ignore`로 제외되는지 확인한다.
- [ ] Git commit·push는 하지 않는다. 사용 허가가 확인되지 않은 이미지가 저장소에 올라가지 않도록, 커밋은 사용자가 결정한다.

## 오류 처리

| 상황 | 처리 |
| --- | --- |
| 원본이 없음 / 출처 정보 없음 | 중단. 필요한 것을 요청 |
| 사용 허가 `허가 안 됨` | 중단. 이 이미지는 쓰지 않음 |
| 사용 허가 `확인 필요` + 테스트 폴더 아님 | 중단. 진행 여부를 사용자에게 확인 |
| 지원하지 않는 형식 | 중단. 형식 보고 |
| 출력 경로가 이미 있음 | 새 번호로 바꿔 진행. 기존 파일은 그대로 |
| rembg / Pillow 없음 | 중단. `cutout.py`가 안내하는 설치 명령을 그대로 보고 |
| 메모리 부족 | 중단. `cutout.py`의 진단 내용을 보고. 모델·크기를 바꿔 다시 할지는 사용자가 결정 |
| 결과 검사 실패 (PNG·RGBA 아님, 투명 비율 이상, 불투명 비율 0.05 미만, 크기 이상) | 중단. 검사 값 보고. 결과 파일은 지우지 않음. 알파 255가 없거나 가장자리 비율이 높은 것만으로는 실패가 아님 |
| `fitScale` > 1 | 경고만 하고 진행. 원본이 충분히 크면 원인을 보고, 원본도 작으면 더 큰 원본 요청 |
| sources.md 행이 읽히지 않음 | 방금 추가한 행의 형식만 고치고 다시 확인 |

## 보고 형식

```markdown
## cutout-image 결과: 성공 / 실패(n단계)

- 프로젝트: projects/<폴더>/
- 검사 기록: projects/<폴더>/cutout-check.md

| 카드 | 처리 | slides.json `image` | 크기 | 투명 비율 | FIT 배율 | 사용 허가 |
| --- | --- | --- | --- | --- | --- | --- |
| card-01 | cutout | assets/characters/chiikawa/cutout/chiikawa-20261105-01.png | 869×1024 | 0.61 | ×0.76 | 허가됨 |
| card-02 | 건너뜀 | "" | - | - | - | - |

- sources.md: n행 추가
- 경고: (해상도, 사용 허가 등)
- 참고: 가장자리 알파 1~9 비율, 육안 확인 결과 (번짐·흰 테두리 등)
- 다음 단계: write-copy가 위 `image` 값을 slides.json에 씀
```
