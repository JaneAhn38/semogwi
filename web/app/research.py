"""유형별 조사 항목과 검증 (고정 템플릿 작업).

AI는 항목(items)마다 값, 근거 문장(quote), 출처 id와 함께 조사 결과(outcome)·충분성(coverage)·확인한 주소(checkedUrls)를 적습니다.
서버는 출처를 실제 조회 기록(검색·페이지 읽기)과 대조해 항목의 상태를 정합니다. 모델이 "확인했다"고 써도 읽은 페이지가 없으면 확인된 것이 아닙니다.

상태 (state) — 값이 있는 경우
- verified      공식 출처 페이지를 읽어 확인
- secondary     2차 출처(기사·위키·나무위키 등) 페이지를 읽어 확인 (근거로 인정, 출처 종류만 구분)
- image         상세 이미지를 AI가 읽어 확인 (출처 이미지와 연결)
- user          사용자가 입력한 자료
- listed        검색 목록에 주소만 있음 (확인 아님)
- unverified    근거를 확인하지 못함 (일반 지식 포함)
- conflict      출처마다 값이 다름 → 사용자 검토 필요

상태 — 값이 없는 경우 (왜 비었는지 구분합니다)
- not_searched  조사하지 않음 (조사 기록이 없거나 AI가 찾아보지 않았다고 답함)
- not_found     찾아봤지만 자료가 없음 (페이지를 읽었거나 검색했는데 해당 정보가 없음)
- failed        검색 또는 페이지 읽기가 실패해 확인하지 못함
- blocked       사이트 접근 제한(자동 접근 금지·요청 대기·접근 거부)으로 확인하지 못함
- missing       예전 조사 기록: 이유가 기록되지 않은 빈 항목 (정보 확인 필요)
"""

import re
from datetime import datetime

from . import site_policy

USER_NOTES_ID = "u1"  # 사용자가 입력 화면에 직접 쓴 참고 자료

# ---------- 조사 항목 정의 (유형별 하나의 표) ----------
# key        항목 이름 (템플릿 필드의 item과 연결)
# label      화면 이름
# official   공식 출처를 우선 찾는 항목 (가격·일정처럼 틀리면 곤란한 정보). 필수 조건은 아닙니다 — 2차 자료도 근거로 인정
#            (세모귀는 개인 캡스톤 시연용 프로젝트라 공식 확인을 제작 조건으로 두지 않습니다. 출처 종류는 계속 기록·표시)
# importance core(핵심, 없으면 구성안을 쓰지 않음) / high(카드에 자주 쓰임) / normal
# core       핵심 그룹 이름. 같은 그룹 중 하나만 확인돼도 됩니다 (예: 성격·작품·데뷔 중 하나)
# many       여러 개가 나열되는 항목 (라인업, 친구 목록 등). 일부만 조사됐는지 충분성을 따집니다
# volatile   시간이 지나면 바뀌는 정보 (가격·일정·운영 시간). 저장된 자료를 다시 쓸 때 다시 확인할 대상
# hint       조사 안내 (특정 주제가 아니라 그 항목을 어디서 어떻게 찾는지)
PEOPLE_RULE = "그룹 이름(예: OO 방위대)은 캐릭터로 세지 않는다. 그룹 이름만 확인되면 relations에 적고 구성원을 짐작해 채우지 않는다"
SPECS = {
    "character": [
        {"key": "official_name", "label": "캐릭터 이름·공식 표기", "importance": "core", "core": "name",
         "hint": "공식 사이트·공식 캐릭터 소개에 적힌 이름. 지역판 이름이 따로 있으면 함께 적는다"},
        {"key": "series", "label": "작품·시리즈명", "importance": "core", "core": "about", "hint": "작품 공식 제목"},
        {"key": "creator", "label": "제작자", "importance": "normal", "hint": "원작자·제작사"},
        {"key": "debut", "label": "첫 등장·데뷔 정보", "importance": "core", "core": "about", "hint": "첫 등장 매체와 연도"},
        {"key": "birthday", "label": "생일 등 공식 프로필", "importance": "normal", "hint": "공식 프로필에 적힌 생일·나이·키 등"},
        {"key": "personality", "label": "성격과 특징", "importance": "core", "core": "about", "hint": "중심 캐릭터의 성격과 특징"},
        {"key": "favorite", "label": "좋아하는 것", "importance": "normal", "many": True, "hint": "공식 설정의 좋아하는 것·취미"},
        {"key": "friends", "label": "친구 캐릭터", "importance": "high", "many": True,
         "hint": "중심 캐릭터의 친구를 한 명씩 최대 4명. 가족은 넣지 않는다. '이름(관계), 이름(관계)'처럼 한 value에 쉼표로 나열한다. "
                 "이름은 한국에서 쓰는 이름으로 쓰고(외국어 자료도 같음, 확인 못 하면 원래 이름), 원래 이름은 '훈이(마사오, 유치원 친구)'처럼 괄호 안에만 적는다. "
                 "공식 캐릭터 소개나 등장인물 목록 페이지에서 확인한다. " + PEOPLE_RULE},
        {"key": "relations", "label": "관계 설명", "importance": "normal",
         "hint": "친구 모임·소속처럼 개별 캐릭터가 아닌 관계 정보 (예: 유치원 친구 모임 이름)"},
        {"key": "tmi", "label": "캐릭터별 TMI", "importance": "high", "many": True,
         "hint": "친구 캐릭터별로 확인된 짧은 사실. '이름: 내용 / 이름: 내용'처럼 한 value에 적는다. 캐릭터마다 60자 이내"},
        {"key": "official_account", "label": "공식 계정", "importance": "normal", "hint": "공식 SNS 계정 이름이나 주소"},
        {"key": "profile_extra", "label": "기타 공식 프로필", "importance": "normal", "many": True,
         "hint": "작품이 공식으로 밝힌 프로필 중 생일·좋아하는 것 외의 항목 (예: 도감 번호, 타입, 분류, 키, 소속). "
                 "'항목: 값, 항목: 값'처럼 항목 이름과 값을 함께 적는다. 출처에 없는 항목은 쓰지 않는다"},
    ],
    "goods": [
        {"key": "product_names", "label": "상품명", "official": True, "importance": "core", "core": "name", "many": True,
         "hint": "공식 판매·공지 페이지의 상품명. 여러 종이면 모두 나열한다"},
        {"key": "official_images", "label": "공식 상품 이미지 위치", "importance": "normal", "hint": "공식 상품 이미지가 있는 페이지 주소"},
        {"key": "release_date", "label": "출시일", "official": True, "importance": "high", "volatile": True, "hint": "발매일·예약 시작일. 표기 그대로"},
        {"key": "seller", "label": "판매처", "official": True, "importance": "high", "hint": "공식 판매처·매장"},
        {"key": "price", "label": "가격", "official": True, "importance": "core", "core": "about", "many": True, "volatile": True,
         "hint": "상품별 가격. 세금 포함 여부 등 표기 그대로"},
        {"key": "size", "label": "크기·규격", "official": True, "importance": "normal", "hint": "상품 크기·규격 표기 그대로"},
        {"key": "material", "label": "소재", "official": True, "importance": "normal", "hint": "소재 표기 그대로"},
        {"key": "components", "label": "구성품", "official": True, "importance": "core", "core": "about", "many": True, "hint": "세트 구성·종류 수"},
        {"key": "features", "label": "상품별 특징", "importance": "core", "core": "about", "many": True, "hint": "공식 설명에 나온 상품 특징"},
        {"key": "sale_period", "label": "판매 기간", "official": True, "importance": "high", "volatile": True, "hint": "판매·예약 기간"},
        {"key": "how_to_buy", "label": "구매 방법", "official": True, "importance": "high", "volatile": True, "hint": "온라인·매장 구매 방법"},
        {"key": "purchase_limit", "label": "구매 제한", "official": True, "importance": "normal", "volatile": True, "hint": "1인당 구매 수량 제한"},
        {"key": "shipping", "label": "판매·배송 안내", "official": True, "importance": "normal", "volatile": True, "hint": "배송 일정·방법"},
        {"key": "benefits", "label": "구매 혜택·특전", "official": True, "importance": "normal", "volatile": True, "hint": "구매 특전·증정품과 조건"},
    ],
    "collab": [
        {"key": "partners", "label": "협업 브랜드·캐릭터", "official": True, "importance": "core", "core": "name", "many": True,
         "hint": "협업한 브랜드와 캐릭터"},
        {"key": "collab_name", "label": "콜라보 명칭", "official": True, "importance": "high", "hint": "공식 행사·상품 명칭"},
        {"key": "period", "label": "진행 기간", "official": True, "importance": "core", "core": "about", "volatile": True, "hint": "시작일과 종료일"},
        {"key": "place", "label": "장소·판매처", "official": True, "importance": "high", "many": True, "volatile": True, "hint": "진행 매장·판매처"},
        {"key": "content", "label": "협업 내용", "official": True, "importance": "core", "core": "about", "hint": "무엇을 함께 하는지"},
        {"key": "menu", "label": "메뉴·상품 구성", "official": True, "importance": "core", "core": "about", "many": True, "hint": "메뉴·상품 목록"},
        {"key": "item_prices", "label": "상품별 가격", "official": True, "importance": "high", "many": True, "volatile": True, "hint": "메뉴·상품별 가격"},
        {"key": "perks", "label": "특전·이벤트", "official": True, "importance": "high", "many": True, "volatile": True, "hint": "증정품·이벤트"},
        {"key": "perk_conditions", "label": "특전 제공 조건", "official": True, "importance": "normal", "volatile": True, "hint": "특전을 받는 조건·수량"},
        {"key": "how_to_join", "label": "참여 방법", "official": True, "importance": "normal", "volatile": True, "hint": "예약·참여 방법"},
    ],
    "popup": [
        {"key": "popup_name", "label": "팝업스토어 명칭", "official": True, "importance": "core", "core": "name", "hint": "공식 명칭"},
        {"key": "period", "label": "진행 기간", "official": True, "importance": "core", "core": "period", "volatile": True, "hint": "시작일과 종료일"},
        {"key": "hours", "label": "운영 시간", "official": True, "importance": "high", "volatile": True, "hint": "요일별 운영 시간"},
        {"key": "place", "label": "장소", "official": True, "importance": "core", "core": "place", "hint": "건물·층·주소"},
        {"key": "closed_days", "label": "휴무일", "official": True, "importance": "normal", "volatile": True, "hint": "휴무일"},
        {"key": "entry", "label": "입장 방법", "official": True, "importance": "high", "volatile": True, "hint": "입장 방식(예약·대기 등)"},
        {"key": "reservation", "label": "사전 예약 여부", "official": True, "importance": "normal", "volatile": True, "hint": "사전 예약 필요 여부와 방법"},
        {"key": "goods", "label": "현장 판매 굿즈", "official": True, "importance": "high", "many": True, "hint": "현장 판매 상품 목록"},
        {"key": "goods_prices", "label": "굿즈 가격", "official": True, "importance": "normal", "many": True, "volatile": True, "hint": "상품별 가격"},
        {"key": "purchase_limit", "label": "구매 제한", "official": True, "importance": "normal", "volatile": True, "hint": "1인당 구매 수량 제한"},
        {"key": "photozone", "label": "포토존", "official": True, "importance": "normal", "hint": "포토존 구성"},
        {"key": "perks", "label": "방문 특전", "official": True, "importance": "normal", "volatile": True, "hint": "방문·구매 특전과 조건"},
        {"key": "notices", "label": "유의 사항", "official": True, "importance": "normal", "volatile": True, "hint": "방문 전 알아 둘 점"},
    ],
}


def spec_of(content_type: str, key: str) -> dict:
    return next((s for s in SPECS.get(content_type, []) if s["key"] == key), {"key": key, "label": key})


# 예전 이름(다른 모듈이 쓰는 형태)은 모두 SPECS에서 만듭니다
ITEMS = {t: [(s["key"], s["label"], bool(s.get("official"))) for s in specs] for t, specs in SPECS.items()}
ITEM_HINTS = {t: {s["key"]: s["hint"] for s in specs if s.get("hint")} for t, specs in SPECS.items()}


# 핵심 그룹 안의 안내 순서 (구성안 지시문에 '성격과 특징 또는 작품·시리즈명 …' 순서로 나옵니다)
CORE_ORDER = {"character": ["official_name", "personality", "series", "debut"], "goods": ["product_names", "price", "features", "components"],
              "collab": ["partners", "content", "period", "menu"], "popup": ["popup_name", "period", "place"]}


def _core_groups(content_type: str, specs: list[dict]) -> list[list[str]]:
    order = {k: i for i, k in enumerate(CORE_ORDER.get(content_type, []))}
    groups: dict[str, list[str]] = {}
    for spec in sorted((s for s in specs if s.get("core")), key=lambda s: order.get(s["key"], 99)):
        groups.setdefault(spec["core"], []).append(spec["key"])
    return list(groups.values())


CORE = {t: _core_groups(t, specs) for t, specs in SPECS.items()}  # 핵심: 그룹마다 하나 이상 확인되면 선택 항목이 비어도 구성안을 만듭니다

STATE_LABELS = {"verified": "공식 확인", "secondary": "2차 자료", "image": "상세 이미지", "user": "사용자 제공", "listed": "검색 결과(원문 미확인)",
                "unverified": "근거 없음", "conflict": "출처 충돌", "not_searched": "미조사", "not_found": "자료 없음",
                "failed": "검색·읽기 실패", "blocked": "접근 제한", "missing": "정보 확인 필요"}
EMPTY_STATES = {"not_searched", "not_found", "failed", "blocked", "missing"}  # 값이 없는 상태
OUTCOMES = ("found", "not_found", "not_searched")  # AI가 항목마다 적는 조사 결과
COVERAGES = ("complete", "partial", "unknown")  # AI가 적는 충분성: 출처에 나온 것을 모두 담았는지

PEOPLE_KEYS = ("friends",)  # card-04는 친구만 다룹니다 (2026-11-23 가족 카드 제거. 예전 자료의 family 항목은 읽지 않음)


_RELATION_ONLY = re.compile(r"^(아빠|엄마|아버지|어머니|부모님?|동생|여동생|남동생|형|누나|언니|오빠|할아버지|할머니|친구|가족|반려견|반려묘|반려동물)$")


_OPEN, _CLOSE = "(（[［", ")）]］"
# 괄호 속 설명 중 관계로 볼 말 (예: '유치원 친구', '라이벌'). 나머지(예: 일본판 이름 '마사오')는 다른 이름(aliases)으로 둡니다
_RELATION_DESC = re.compile(r"(친구|동료|라이벌|단짝|짝꿍|절친|이웃|선배|후배|동창|같은 ?반|룸메이트|파트너|짝사랑|첫사랑|선생님|담임|멤버|팀원|동생|사촌|"
                            r"진화|천적|주인|애완|반려|관계|사이|상대|콤비|가족)")


def _split_top(value: str, seps: str = ",，、") -> list[str]:
    """괄호 밖의 구분자(쉼표·'、'·' 및 ')에서만 나눕니다. 괄호 안 쉼표는 자르지 않습니다 (예: '훈이(마사오, 유치원 친구)')."""
    parts, buf, depth, i = [], "", 0, 0
    text = value or ""
    while i < len(text):
        ch = text[i]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE and depth:
            depth -= 1
        if depth == 0 and (ch in seps or text.startswith(" 및 ", i)):
            parts.append(buf)
            buf = ""
            i += 3 if ch == " " else 1
            continue
        buf += ch
        i += 1
    parts.append(buf)
    return [p.strip() for p in parts if p.strip()]


def split_person(part: str) -> dict:
    """'이름(설명)' 하나를 나눕니다. 괄호 밖 = 이름, 괄호 안 = 설명.
    설명 중 관계 말로 끝나는 부분은 relation, 나머지는 aliases(다른 이름·원어 표기)로 둡니다. 이름 칸에는 괄호를 남기지 않습니다."""
    name, notes, depth, buf = "", [], 0, ""
    for ch in part:
        if ch in _OPEN:
            if depth == 0:
                name += " "
            else:
                buf += ch
            depth += 1
        elif ch in _CLOSE and depth:
            depth -= 1
            if depth == 0:
                notes.append(buf)
                buf = ""
            else:
                buf += ch
        elif depth:
            buf += ch
        else:
            name += ch
    if buf:
        notes.append(buf)  # 닫히지 않은 괄호
    relation, aliases = "", []
    for note in notes:
        for piece in _split_top(note, ",，、/"):
            if not relation and (_RELATION_DESC.search(piece) or _RELATION_ONLY.match(piece)):
                relation = piece
            elif piece not in aliases:
                aliases.append(piece)
    return {"name": " ".join(name.split()), "relation": relation, "aliases": aliases}


def _split_people(value: str) -> list[dict]:
    people = []
    for part in _split_top(value):
        person = split_person(part)
        if person["name"] and not _RELATION_ONLY.match(person["name"]):  # 이름 없이 관계만 적힌 경우(예: '아빠')는 캐릭터로 세지 않습니다
            people.append(person)
    return people


def _tmi_by_name(items: list[dict]) -> dict[str, str]:
    item = next((i for i in items if i.get("key") == "tmi"), None)
    if not item or not item.get("value") or not _usable(item):
        return {}
    result = {}
    for part in re.split(r"\s/\s|\n", item["value"]):
        name, sep, text = part.partition(":")
        if sep and name.strip() and text.strip():
            result[name.strip()] = text.strip()
    return result


def people_of(items: list[dict] | None) -> dict[str, list[dict]]:
    """조사에서 근거로 확인된 친구 캐릭터. {"friends": [{name, relation, tmi, sourceIds}]}

    확인되지 않은 항목(근거 없음·검색 목록만·충돌)은 쓰지 않습니다. TMI는 그 캐릭터 이름으로 적힌 것만 붙입니다.
    """
    items = items or []
    tmi = _tmi_by_name(items)
    result = {}
    for key in PEOPLE_KEYS:
        item = next((i for i in items if i.get("key") == key), None)
        if not item or not item.get("value") or not _usable(item):
            result[key] = []
            continue
        people = []
        for p in _split_people(item["value"]):
            if any(_norm(p["name"]) == _norm(q["name"]) for q in people):
                continue
            found = next((tmi[n] for n in [p["name"], *p["aliases"]] if n in tmi), "")  # TMI가 다른 이름(예: 마사오)으로 적혀 있어도 붙입니다
            people.append({**p, "tmi": found[:60], "sourceIds": list(item.get("sourceIds", []))})
        result[key] = people[:4]
    return result


def resolve_name(name: str, people: list[dict]) -> str:
    """다른 이름(괄호 속 원어·일본판 이름 등)으로 적힌 캐릭터를 한국 이름으로 바꿉니다. 모르면 그대로 둡니다 (예: 마사오 → 훈이)."""
    key = _norm(name)
    for p in people:
        if key == _norm(p["name"]) or any(key == _norm(a) for a in p.get("aliases") or []):
            return p["name"]
    return name


TMI_MAX = 60
# 관계·소속만 되풀이한 문장인지 볼 때 빼는 말 (예: "방범대 멤버예요", "짱구의 친구예요")
_RELATION_WORDS = re.compile(r"(친구|가족|멤버|소속|일원|구성원|동료|단짝|관계|사이|예요|이에요|입니다|이다|이며|이고|이야|에요|의|은|는|이|가|을|를|과|와|도|로|으로|함께|같은|중|한|명)")


def tmi_problem(name: str, relation: str, tmi: str, seen: set[str] | None = None, group_words: tuple[str, ...] = ()) -> str:
    """캐릭터 TMI로 쓸 수 없는 이유. 문제가 없으면 빈 문자열.

    - 60자를 넘음
    - 이름·관계·소속 모임만 되풀이함 (예: '떡잎마을 방범대 멤버예요')
    - 다른 캐릭터와 같은 문장
    """
    text = " ".join((tmi or "").split())
    if not text:
        return "비어 있음"
    if len(text) > TMI_MAX:
        return f"{TMI_MAX}자 초과"
    key = _norm(text)
    if seen is not None and key in seen:
        return "다른 캐릭터와 같은 내용"
    rest = key
    for word in (name, relation, *group_words):
        if word:
            rest = rest.replace(_norm(word), "")
    rest = _RELATION_WORDS.sub("", rest)
    if len(rest) < 4 or (_RELATION_END.search(text) and len(key) <= 20):
        return "관계·소속만 반복"
    return ""


# 짧은 문장이 관계·소속으로 끝나면(예: '떡잎마을 방범대 멤버예요', '짱구의 여동생이에요') 관계 설명으로 봅니다
_RELATION_END = re.compile(r"(멤버|소속|일원|구성원|친구|가족|동생|여동생|남동생|형|누나|언니|오빠|엄마|아빠|부모|반려견|반려묘|반려동물)"
                           r"\s*(이에요|예요|입니다|이다|이야|야)?\s*[.!~]?$")


def people_from(research: dict | None) -> dict[str, list[dict]]:
    """조사 결과의 친구. 캐릭터별 조사(peopleResearch)에서 확인한 TMI·근거·출처가 있으면 그것을 씁니다.

    {"friends": [{name, relation, tmi, quote, sourceIds, state}]}
    """
    research = research or {}
    base = people_of(research.get("items"))
    details = {(p.get("category", "friends"), p["name"]): p for p in (research.get("peopleResearch") or {}).get("people", []) if p.get("tmi")}
    for key in PEOPLE_KEYS:
        for person in base[key]:
            found = details.get((key, person["name"]))
            if found:
                person.update(tmi=found["tmi"], quote=found.get("quote", ""), sourceIds=list(found.get("sourceIds", [])), state=found.get("state", ""))
    return base


def friend_names(items: list[dict] | None) -> list[str]:
    """근거로 확인된 친구 캐릭터 이름."""
    return [p["name"] for p in people_of(items)["friends"]]


USABLE = {"verified", "secondary", "image", "user"}  # 자료가 있는 상태 (listed는 근거 문장이 있을 때만, _usable)


def _usable(item: dict) -> bool:
    """자료가 있는지. 공식 확인 여부와 관계없이, 읽은 2차 자료와 값이 적힌 검색 결과(근거 문장 있음)도 찾은 것으로 봅니다."""
    if item["state"] == "listed":
        return bool(item.get("value")) and bool(item.get("quote"))  # 검색 결과에 값이 그대로 적혀 있을 때만
    return item["state"] in USABLE


def core_status(content_type: str, items: list[dict] | None) -> dict:
    """핵심 항목이 확인됐는지. ready가 True면 선택 항목이 부족해도 확인된 정보만으로 구성안을 씁니다."""
    by_key = {i["key"]: i for i in items or []}
    labels = {key: label for key, label, _ in ITEMS.get(content_type, [])}
    lacking = [" 또는 ".join(labels[k] for k in group) for group in CORE.get(content_type, [])
               if not any(k in by_key and _usable(by_key[k]) for k in group)]
    return {"ready": bool(items) and not lacking, "lacking": lacking}


WEAK_STATES = {"conflict", "unverified"}  # 값은 있지만 근거가 약한 상태: 출처끼리 다르거나, 인용한 출처가 조회 기록에 없음
GAP_REASONS = {"not_searched": "조사하지 않음", "not_found": "자료를 찾지 못함", "failed": "검색·페이지 읽기 실패", "blocked": "사이트 접근 제한",
               "missing": "자료를 찾지 못함", "listed": "검색 결과에 값이 없음", "unverified": "근거를 확인하지 못함", "conflict": "출처마다 값이 다름"}


def gap_report(content_type: str, items: list[dict] | None, missing: list[str] | None = None) -> dict:
    """자료 부족 안내. 진행을 막지 않고, 무엇이 왜 부족한지 보여 주는 데만 씁니다.

    결과: {"ready": 핵심 항목 확인 여부, "rows": [{key, label, importance, state, kind, reason, value}], "notes": AI가 적은 부족 사유}
    kind: not_found(찾지 못함 — 카드에 만들어 넣지 않음) / weak(값은 있지만 출처끼리 다르거나 근거를 확인하지 못함)
    공식 확인 여부로는 부족하다고 보지 않습니다 (2차 자료·값이 적힌 검색 결과도 찾은 것). 출처 종류는 조사 항목에 따로 남습니다.
    """
    rows = []
    for item in items or []:
        if item.get("importance") not in ("core", "high"):
            continue
        state = item["state"]
        if state in EMPTY_STATES or (state == "listed" and not _usable(item)):
            kind = "not_found"
        elif state in WEAK_STATES:
            kind = "weak"
        else:
            continue
        rows.append({"key": item["key"], "label": item["label"], "importance": item["importance"], "state": state, "kind": kind,
                     "reason": GAP_REASONS.get(state, STATE_LABELS.get(state, state)), "value": item.get("value", "") if kind == "weak" else ""})
    rows.sort(key=lambda r: (r["importance"] != "core", r["kind"] != "not_found"))
    return {"ready": core_status(content_type, items)["ready"], "rows": rows, "notes": [str(m)[:200] for m in (missing or [])][:10]}


def core_text(content_type: str) -> str:
    labels = {key: label for key, label, _ in ITEMS.get(content_type, [])}
    groups = [" 또는 ".join(labels[k] for k in group) for group in CORE.get(content_type, [])]
    return ("[핵심 항목] " + ", ".join(groups) + ". 핵심 항목이 근거로 확인되면 선택 항목이 없어도 status를 ok로 하고, "
            "확인하지 못한 칸은 비운다. 핵심 항목조차 확인하지 못했을 때만 insufficient로 한다.")


# 상세 이미지에서 흔히 쓰는 표기 (판독 프롬프트용). 일본 쇼핑몰 상세페이지 표기를 함께 적습니다
LABEL_HINTS = {
    "product_names": "商品名, 상품명", "price": "価格, 販売価格, 税込, 가격", "size": "サイズ, 寸法, 크기, 사이즈", "material": "素材, 材質, 소재",
    "components": "セット内容, 種類, 全N種, 구성, 종류", "release_date": "発売日, 発売予定, 출시일", "sale_period": "販売期間, 受付期間, 판매 기간",
    "seller": "販売元, 発売元, 판매처", "purchase_limit": "お一人様N個まで, 購入制限, 구매 제한", "shipping": "発送, お届け, 배송",
    "benefits": "特典, ノベルティ, 특전", "how_to_buy": "購入方法, 구매 방법", "features": "특징 문구, 収納できる 등 설명",
}


def keys_of(content_type: str) -> list[str]:
    return [key for key, _, _ in ITEMS.get(content_type, [])]


IMPORTANCE_LABELS = {"core": "핵심", "high": "중요"}


def checklist_text(content_type: str, report: bool = False) -> str:
    """조사 항목 안내. report=True면 항목마다 조사 결과(outcome)·충분성(coverage)·확인한 주소(checkedUrls)도 적게 합니다."""
    lines = ["[조사 항목] 아래 항목을 하나씩 찾아 items에 적는다. key는 그대로 쓴다. 핵심·중요 항목부터 찾는다."]
    for spec in SPECS[content_type]:
        tags = [t for t in (IMPORTANCE_LABELS.get(spec.get("importance")), "공식 출처 우선" if spec.get("official") else "",
                            "여러 개 나열" if spec.get("many") else "") if t]
        hint = f" — {spec['hint']}" if spec.get("hint") else ""
        lines.append(f"- {spec['key']}: {spec['label']}{' (' + ', '.join(tags) + ')' if tags else ''}{hint}")
    if report:
        lines += [
            "- outcome: 값을 찾았으면 found, 찾아봤지만 출처에 없으면 not_found, 이번에 찾아보지 않았으면 not_searched. 사실대로 적는다.",
            "- checkedUrls: 그 항목을 확인하려고 읽었거나 읽으려 한 페이지 주소를 글자 그대로 적는다 (실패한 주소 포함, 최대 5개).",
            "- coverage: '여러 개 나열' 항목은 출처에 나온 것을 모두 담았으면 complete, 일부만 확인했으면 partial, 전체 규모를 알 수 없으면 unknown. "
            "값이 하나인 항목은 unknown으로 둔다. 개수를 채우려고 짐작하지 않는다.",
            "- coverageNote: partial이나 unknown이면 이유를 30자 이내로 쓴다 (예: 목록 페이지 일부만 읽음).",
        ]
    lines += [
        "- value는 출처 표기 그대로 짧게 쓴다. 숫자·날짜·가격은 바꾸거나 계산하지 않는다.",
        "- quote에는 근거가 된 페이지 문장을 80자 이내로 그대로 옮긴다. 사용자 참고 자료가 근거면 그 문장을 옮긴다.",
        "- sourceIds에는 그 값을 실제로 읽은 sources id를 적는다. 사용자 참고 자료가 근거면 u1을 적는다.",
        "- 찾지 못한 항목도 빠뜨리지 않고 value를 빈 문자열, sourceIds를 빈 배열로 적는다. 일반 지식이나 짐작으로 채우지 않는다.",
        "- 같은 항목의 값이 출처마다 다르면 값마다 따로 items에 넣는다. 하나로 고르지 않는다.",
        "- 카드 fields에는 items에서 출처로 확인된 값만 쓴다." if not report else "- 이 단계에서는 카드를 쓰지 않는다. 조사 결과만 적는다.",
        "- 상세 이미지(근거 id img로 시작)에서 읽은 정보가 주어지면 그 근거 id를 그대로 쓴다. 페이지 내용과 값이 다르면 둘 다 items에 넣는다.",
        core_text(content_type),
    ]
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"[\s·,./~\-()]+", "", text).lower()


def research_report(research: dict | None, content_type: str = "") -> dict:
    """조사 결과 요약 (수정 전후·버전끼리 비교용). 예전 조사 기록에도 씁니다."""
    research = research or {}
    items = research.get("items") or []
    states: dict[str, int] = {}
    for item in items:
        states[item["state"]] = states.get(item["state"], 0) + 1
    by_importance: dict[str, list[int]] = {}
    for item in items:
        imp = item.get("importance") or spec_of(content_type, item["key"]).get("importance", "normal")
        found, total = by_importance.setdefault(imp, [0, 0])
        by_importance[imp] = [found + (item["state"] not in EMPTY_STATES), total + 1]
    sources = research.get("sources") or []
    people = (research.get("peopleResearch") or {}).get("people", [])
    return {
        "pipeline": research.get("pipeline", 1),
        "researchedAt": research.get("researchedAtTime") or research.get("researchedAt", ""),
        "queries": len(research.get("queries") or []),
        "pagesRead": len([f for f in research.get("fetched") or [] if 200 <= int(f.get("code") or 0) < 400]),
        "sourcesRead": len([s for s in sources if s.get("verification") == "fetched"]),
        "officialRead": len([s for s in sources if s.get("verification") == "fetched" and s.get("kind") == "official"]),
        "items": len(items), "states": states,
        "found": len([i for i in items if i["state"] not in EMPTY_STATES]),
        "byImportance": {k: f"{v[0]}/{v[1]}" for k, v in by_importance.items()},
        "review": [i["key"] for i in items if (i.get("coverage") or {}).get("review") or i["state"] in ("conflict", "listed", "unverified")],
        "core": core_status(content_type, items) if content_type and items else None,
        "peopleWithTmi": len([p for p in people if p.get("tmi")]),
        "facts": len(research.get("facts") or []),
    }


def _url_key(url: str) -> str:
    """조회 기록과 비교하기 위한 주소 (대소문자·끝의 /·조각 무시)."""
    match = re.match(r"^(https?)://([^/?#]+)([^?#]*)(\?[^#]*)?", (url or "").strip(), re.I)
    if not match:
        return ""
    host = match.group(2).lower().removeprefix("www.")
    return f"{host}{match.group(3).rstrip('/')}{match.group(4) or ''}"


ACCESS_DENIED_CODES = {401, 402, 403, 429, 451, 503}  # 사이트가 요청을 거절함 → 접근 제한


def attempt_result(url: str, log: dict) -> str:
    """AI가 항목을 확인하려고 본 주소의 결과: read(읽음) / failed(실패) / blocked(접근 제한) / unknown(조회 기록 없음)."""
    if site_policy.restricted_site(url):
        return "blocked"
    key = _url_key(url)
    records = [f for f in log.get("fetches", []) if _url_key(f.get("url", "")) == key]
    if any(f.get("denied") for f in records):
        return "blocked"
    codes = [int(f.get("code") or 0) for f in records]
    if any(200 <= c < 400 for c in codes):
        return "read"
    if any(c in ACCESS_DENIED_CODES for c in codes):
        return "blocked"
    if records:
        return "failed"
    if site_policy.host_of(url) in log.get("coolingHosts", ()):
        return "blocked"  # 요청 대기 중인 사이트라 읽지 않음
    return "unknown"


def _empty_state(outcome: str | None, results: list[str], log: dict | None, new_format: bool) -> str:
    """값이 없는 항목이 왜 비었는지 정합니다. 확인할 수 있는 근거가 없으면 '자료 없음'이라고 단정하지 않습니다."""
    if log is None:
        return "missing"  # 조사 기록 없이 다시 정리하는 경우 (예전 형식)
    if not log.get("searched") and not log.get("fetches"):
        return "failed" if log.get("searchFailures") else "not_searched"  # 이번 조사에서 검색·페이지 읽기가 전혀 없었음
    if outcome == "not_searched":
        return "not_searched"
    if "read" in results:
        return "not_found"  # 관련 페이지를 실제로 읽었는데 정보가 없었음
    if "blocked" in results:
        return "blocked"
    if "failed" in results:
        return "failed"
    if outcome == "not_found":
        # 검색은 했다고 답했지만 확인한 페이지가 없음: 검색 자체가 모두 실패했으면 실패, 아니면 '자료 없음'
        return "failed" if log.get("searchFailures") and not log.get("searchesWithResults") else "not_found"
    return "not_searched" if new_format else "missing"


def _coverage(spec: dict, raw: dict | None, has_value: bool) -> dict | None:
    """충분성: 여러 개가 나열되는 항목이 일부만 조사됐는지. 개수를 강제하지 않고, 판단이 어려우면 검토 대상으로 둡니다."""
    if raw is None or "coverage" not in raw or not has_value:
        return None  # 예전 형식이거나 값이 없는 항목
    level = raw.get("coverage") if raw.get("coverage") in COVERAGES else "unknown"
    note = " ".join(str(raw.get("coverageNote") or "").split())[:160]
    if not spec.get("many") and level == "unknown":
        level = "n/a"  # 값이 하나인 항목은 충분성을 따지지 않습니다 (AI가 일부만 확인했다고 할 때만 표시)
    review = level in ("partial", "unknown")
    return {"level": level, "note": note, "review": review}


def _evidence(entry: dict, by_id: dict, at: str) -> list[dict]:
    """값 하나의 근거 기록. 페이지를 읽었는지(pageRead)와 근거 문장이 페이지에 있는지 확인했는지(quoteCheck)는 따로 둡니다."""
    records = []
    for source_id in entry["sourceIds"]:
        source = by_id[source_id]
        records.append({"sourceId": source_id, "url": source.get("url", ""), "title": source.get("title", ""), "kind": source.get("kind", ""),
                        "verification": source.get("verification", ""), "pageRead": source.get("verification") == "fetched",
                        "publishedAt": source.get("publishedAt", ""),  # 원문 게시일 (보이는 경우만). at은 조사일
                        "quote": entry["quote"], "quoteCheck": "not_checked", "at": at})
    return records


def verify_items(content_type: str, raw_items: list, sources: list[dict], log: dict | None = None,
                 previous: list[dict] | None = None) -> list[dict]:
    """AI가 적은 항목을 정리합니다. 같은 항목은 하나로 합치고, 값이 다르면 출처 충돌로 표시합니다.

    log: 이번 조사의 실제 기록 {searched, fetches, searchFailures, searchesWithResults, coolingHosts, at}. 있으면 빈 항목의 이유를 구분합니다.
    previous: 다시 정리할 때(예: 상세 이미지 병합) 빈 항목의 이유·충분성 기록을 이어 받을 예전 항목
    """
    by_id = {s["id"]: s for s in sources}
    grouped: dict[str, list[dict]] = {}
    unclear: dict[str, list[dict]] = {}
    reports: dict[str, dict] = {}  # 항목별 조사 결과 보고 (outcome·coverage·checkedUrls)
    new_format = False
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict) or raw.get("key") not in keys_of(content_type):
            continue
        if "outcome" in raw:
            new_format = True
            report = reports.setdefault(raw["key"], {"outcome": None, "checkedUrls": []})
            outcome = raw.get("outcome") if raw.get("outcome") in OUTCOMES else None
            if outcome == "found" or report["outcome"] is None:
                report["outcome"] = outcome
            report["checkedUrls"] += [str(u) for u in raw.get("checkedUrls", []) if isinstance(u, str)][:8]
            if "coverage" in raw and "coverage" not in report:
                report.update(coverage=raw.get("coverage"), coverageNote=raw.get("coverageNote", ""))
        value = " ".join(str(raw.get("value") or "").split())[:200]
        ids = [i for i in raw.get("sourceIds", []) if i in by_id]
        entry = {"value": value, "quote": " ".join(str(raw.get("quote") or "").split())[:160], "sourceIds": ids}
        if raw.get("unclear"):
            unclear.setdefault(raw["key"], []).append({**entry, "value": ""})  # 읽기 어려운 값: 추측하지 않고 확인 필요로 남깁니다
            continue
        grouped.setdefault(raw["key"], []).append(entry)

    old = {i["key"]: i for i in previous or []}
    at = (log or {}).get("at") or datetime.now().isoformat(timespec="seconds")
    items = []
    for spec in SPECS[content_type]:
        key, label, strict = spec["key"], spec["label"], bool(spec.get("official"))
        entries = [e for e in grouped.get(key, []) if e["value"]]
        merged: dict[str, dict] = {}  # 같은 값은 출처를 합칩니다 (중복 정리)
        for entry in entries:
            slot = merged.setdefault(_norm(entry["value"]), {**entry, "sourceIds": []})
            slot["sourceIds"] = list(dict.fromkeys(slot["sourceIds"] + entry["sourceIds"]))
            slot["quote"] = slot["quote"] or entry["quote"]
        values = list(merged.values())
        main = values[0] if values else {"value": "", "quote": "", "sourceIds": []}
        report = reports.get(key)
        checked = [{"url": u, "result": attempt_result(u, log or {})} for u in dict.fromkeys((report or {}).get("checkedUrls", []))]
        if main["value"]:
            state = _state(main, values, by_id, key)
        elif log is None and old.get(key, {}).get("state") in EMPTY_STATES:
            state = old[key]["state"]  # 다시 정리할 때는 예전 조사에서 정한 이유를 유지합니다
        else:
            state = _empty_state((report or {}).get("outcome"), [c["result"] for c in checked], log, new_format)
        item = {"key": key, "label": label, "strict": strict, "importance": spec.get("importance", "normal"),
                "volatile": bool(spec.get("volatile")), "value": main["value"], "quote": main["quote"],
                "sourceIds": main["sourceIds"], "alternatives": [{**v, "evidence": _evidence(v, by_id, at)} for v in values[1:]],
                "state": state, "unclear": unclear.get(key, [])[:3], "evidence": _evidence(main, by_id, at) if main["value"] else []}
        coverage = _coverage(spec, report, bool(main["value"]))
        if coverage is None and log is None and old.get(key, {}).get("coverage") and main["value"]:
            coverage = old[key]["coverage"]
        if coverage:
            item["coverage"] = coverage
        if report is not None or checked:
            item["attempts"] = {"outcome": (report or {}).get("outcome"), "checked": checked}
        elif log is None and old.get(key, {}).get("attempts"):
            item["attempts"] = old[key]["attempts"]
        items.append(item)
    return items


def _counts_for(source: dict, key: str | None) -> bool:
    """나무위키 같은 보조 출처도 모든 항목의 참고 근거로 셉니다 (출처 종류는 auxiliary로 남음). 미러 사이트만 근거가 아닙니다."""
    return source.get("verification") != "mirror"


def _state(main: dict, values: list[dict], by_id: dict, key: str | None = None) -> str:
    if not main["value"]:
        return "missing"
    if len(values) > 1:
        return "conflict"  # 공식 값과 보조 출처 값이 달라도 여기서 사용자 검토로 갑니다
    cited = [by_id[i] for i in main["sourceIds"] if i in by_id]
    usable = [s for s in cited if _counts_for(s, key)]
    if cited and not usable:
        return "unverified"  # 보조 출처만 근거인데 그 항목에는 쓸 수 없음 (예: 나무위키의 생일·가격)
    cited = usable
    verifications = {s["verification"] for s in cited}
    read = [s for s in cited if s["verification"] == "fetched"]
    if any(s["kind"] == "official" and not s.get("auxiliary") for s in read):
        return "verified"
    if read:
        return "secondary"
    if cited and all(s.get("auxiliary") for s in cited):
        return "secondary"  # 사용자가 옮긴 나무위키 자료: 사용자 제공이어도 2차 자료 수준 (공식만 허용하는 항목에는 부족)
    if "image" in verifications:
        return "image"
    if "user_provided" in verifications:
        return "user"
    if "search_result" in verifications:
        return "listed"
    return "unverified"


# ---------- 출처 규칙 (최초 조사·추가 조사·보관함 공통) ----------
NOTES_KINDS = {"": "사용자가 입력한 참고 자료", "official": "사용자가 입력한 참고 자료 (공식 출처라고 입력 · 검증 안 됨)",
               "namuwiki": "나무위키에서 옮긴 참고 자료 (사용자 제공)", "other": "사용자가 입력한 참고 자료 (기타 출처)"}


def user_notes_source(kind: str = "", url: str = "", content_type: str | None = None) -> dict:
    """참고 자료 직접 입력의 출처(u1). 사용자가 '공식'을 골라도 공식 확인으로 만들지 않습니다 (verification은 늘 user_provided).
    나무위키를 골랐거나 주소가 나무위키·미러면 보조 출처로 표시해 정해진 항목에만 2차 자료로 씁니다."""
    kind = kind if kind in NOTES_KINDS else ""
    url = url if re.match(r"^https?://", url or "") else ""
    source = {"id": USER_NOTES_ID, "title": NOTES_KINDS[kind], "url": url, "kind": "user", "verification": "user_provided",
              "origin": "user", "officialBasis": None, "userKind": kind}
    aux = site_policy.auxiliary_tag(url, content_type) if url else None
    if kind == "namuwiki" or aux:
        source["auxiliary"] = aux or site_policy.auxiliary_tag("https://namu.wiki/", content_type)
        source["title"] = NOTES_KINDS["namuwiki"]
        source["userKind"] = "namuwiki"
    return source


def apply_source_rules(research: dict, content_type: str) -> dict:
    """예전에 저장된 자료에도 지금 출처 규칙을 적용합니다: 나무위키 출처에 보조 출처 표시를 붙이고, 미러 사이트는 읽은 근거로 보지 않으며,
    그 출처를 쓰는 항목의 상태를 다시 정합니다. 사용자가 고른 값·고친 값·출처 충돌은 그대로 둡니다. research를 고칩니다."""
    changed = set()
    for source in research.get("sources", []):
        if source.get("origin") == "user":
            continue
        url = source.get("url", "")
        tag = site_policy.auxiliary_tag(url, content_type) if url else None
        if tag and source.get("auxiliary") != tag:
            source.update(auxiliary=tag, kind="secondary", officialBasis=None)
            changed.add(source["id"])
        if url and site_policy.mirror_site(url) and source.get("verification") == "fetched":
            source["verification"] = "mirror"
            changed.add(source["id"])
    if changed:
        by_id = {s["id"]: s for s in research.get("sources", [])}
        for item in research.get("items") or []:
            if (item.get("value") and item.get("state") not in EMPTY_STATES | {"conflict", "user"}
                    and set(item.get("sourceIds", [])) & changed):
                main = {"value": item["value"], "sourceIds": item["sourceIds"]}
                item["state"] = _state(main, [main], by_id, item["key"])
    return research


def facts_from_items(items: list[dict]) -> list[dict]:
    """예전 형식의 facts(숫자 대조, 화면 표시)에 쓰도록 확인된 항목을 문장으로 만듭니다."""
    facts = []
    for item in items:
        for entry in [item] + item["alternatives"]:
            if entry["value"]:
                facts.append({"text": f"{item['label']}: {entry['value']}", "sourceIds": entry["sourceIds"],
                              "origin": "ai", "item": item["key"]})
    return facts


# ---------- 캐릭터 프로필 줄 (character-02의 profile_rows) ----------
# 프로필 줄은 항목 이름을 정해 두지 않으므로, 조사 항목 중 근거가 있는 값에서만 고르고(서버 보충) 줄마다 조사 값과 대조합니다.
PROFILE_LABELS = {"birthday": "생일", "favorite": "좋아하는 것", "creator": "작가"}  # 고정 이름이 있는 후보 (나머지는 profile_extra의 '항목: 값')


def profile_candidates(items: list[dict] | None, label_max: int = 6, value_max: int = 16) -> list[dict]:
    """근거가 확인된 조사 값으로 만든 프로필 줄 후보 {label, value, sourceIds}. 칸보다 길면 자르지 않고 뺍니다 (지어내지 않음)."""
    by_key = {i["key"]: i for i in items or []}
    rows = []
    for key in ("profile_extra", "birthday", "favorite", "creator"):
        item = by_key.get(key)
        if not item or not item.get("value") or not _usable(item):
            continue
        if key == "profile_extra":
            pairs = [p.split(":", 1) for p in re.split(r"\s*[,，/]\s*", item["value"]) if ":" in p]
            entries = [(label.strip(), value.strip()) for label, value in pairs]
        else:
            entries = [(PROFILE_LABELS[key], item["value"].strip())]
        for label, value in entries:
            if label and value and len(label) <= label_max and len(value) <= value_max:
                rows.append({"label": label, "value": value, "sourceIds": list(item.get("sourceIds", []))})
    return rows


def profile_row_state(row: dict, items: list[dict] | None, keys: list[str]) -> str:
    """프로필 줄 하나의 근거 상태: 그 값이 들어 있는 조사 항목의 상태. 어느 조사 값에도 없으면 unverified (근거 없음)."""
    value = _norm(row.get("value", ""))
    if not value:
        return "missing"
    for item in items or []:
        if item["key"] not in keys:
            continue
        values = [item.get("value", "")] + [a.get("value", "") for a in item.get("alternatives", [])]
        if any(v and value in _norm(v) for v in values):
            return item["state"]
    return "unverified"


FIELD_STATE_LABELS = {"verified": "공식 확인", "secondary": "2차 자료", "listed": "검색 결과(원문 미확인)", "user": "사용자 제공",
                      "user_written": "사용자 작성", "image": "상세 이미지", "conflict": "출처 충돌", "unverified": "근거 확인 못 함",
                      "absent": "조사에서 찾지 못함"}


def value_strings(value) -> list[str]:
    """칸 값의 글자들 (글 칸, 글 목록, 항목 묶음, 정보 줄)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in value_strings(v)]
    if isinstance(value, dict):
        return [s for v in value.values() for s in value_strings(v)]
    return []


_NUMBER_RE = re.compile(r"\d+")  # 숫자 묶음 (쉼표는 먼저 지움: 9,900 → 9900, 12.1 → 12 · 1)


def supported(value, material_norm: str) -> bool:
    """칸 값이 자료(조사 사실·조사 항목 값·근거 문장·사용자 자료)에 나오는지.

    AI가 표기를 바꿔 쓰는 경우(¥440 ↔ 440엔, 12월 1일 ↔ 12.1)를 맞는 값으로 보려고, 값 전체 외에도
    값의 숫자가 모두 자료에 있거나(숫자가 있는 값), 세 글자 이상인 낱말이 자료에 나오면 근거가 있다고 봅니다.
    """
    numbers_in_material = set(_NUMBER_RE.findall(material_norm.replace(",", "")))
    for text in value_strings(value):
        whole = _norm(text)
        if len(whole) >= 2 and whole in material_norm:
            return True
        numbers = _NUMBER_RE.findall(text.replace(",", ""))
        if numbers and all(n in numbers_in_material for n in numbers):
            return True
        if any(len(_norm(word)) >= 3 and _norm(word) in material_norm for word in re.split(r"\s+", text) if not _NUMBER_RE.search(word)):
            return True
    return False


def field_states(cards: list[dict], templates_of, items: list[dict] | None, card_state, material: str | None = None) -> dict:
    """카드 필드마다 어떤 근거에서 왔는지 표시합니다. {frame: {field: state}}

    templates_of(frame) → 템플릿, card_state(card) → 카드 출처 상태(verified/user_provided/listed/...)
    material: 대조할 자료 글. 조사 항목에 값이 없는 칸은 카드의 다른 출처 상태를 따라가지 않고, 자료에 그 값이 있는지 직접 봅니다.
    없으면 'absent'(조사에서 찾지 못함). 사용자가 직접 고친 칸(card.userFields)은 'user_written'(사용자 작성)입니다.
    """
    material_norm = _norm(material) if material is not None else None
    by_key = {i["key"]: i for i in items or []}
    fallback = {"verified": "verified", "user_provided": "user", "listed": "listed", "image": "image"}
    result = {}
    for card in cards:
        tpl = templates_of(card["frame"])
        card_level = fallback.get(card_state(card), "unverified")
        states = {}
        for field in tpl["fields"]:
            if field.get("verifyItems"):
                # 프로필 줄: 줄마다 'profile_rows.0'처럼 따로 상태를 둡니다
                for n, row in enumerate(card["fields"].get(field["key"]) or []):
                    states[f"{field['key']}.{n}"] = profile_row_state(row, items, field["verifyItems"])
                continue
            key = field.get("item")
            if not key or field["type"] == "flag":
                continue
            value = card["fields"].get(field["key"])
            item_state = by_key[key]["state"] if key in by_key else "missing"
            if not value:
                states[field["key"]] = "missing"
            elif field["key"] in (card.get("userFields") or []):
                states[field["key"]] = "user_written"  # 사용자가 직접 쓴 문구 (조사한 사실과 구분)
            elif item_state in ("verified", "secondary", "conflict", "image"):
                states[field["key"]] = item_state  # 페이지에서 확인한 항목, 또는 출처끼리 다른 항목
            elif card_level == "user":
                states[field["key"]] = "user"  # 사용자 자료로 쓴 카드
            elif item_state not in EMPTY_STATES:
                states[field["key"]] = item_state  # listed / unverified / user
            elif material_norm is not None and not supported(value, material_norm):
                states[field["key"]] = "absent"  # 조사 항목에도 자료에도 없는 값 (다른 칸의 출처 상태를 따르지 않음)
            else:
                states[field["key"]] = card_level  # 조사 항목은 비었지만 조사 사실·사용자 자료에 나오는 값
        result[card["frame"]] = states
    return result
