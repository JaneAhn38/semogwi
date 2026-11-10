"""유형별 조사 항목과 검증 (고정 템플릿 작업).

AI는 항목(items)마다 값, 근거 문장(quote), 출처 id를 적습니다. 서버는 출처를 실제 조회 기록으로 판정한
sources와 대조해 항목의 상태를 정합니다. 모델이 "확인했다"고 써도 읽은 페이지가 없으면 확인된 것이 아닙니다.

상태 (state)
- verified    공식 출처 페이지를 읽어 확인
- secondary   2차 출처 페이지를 읽어 확인 (캐릭터 소개에서만 근거로 인정, 공식만 허용하는 항목에는 부족)
- user        사용자가 입력한 자료
- listed      검색 목록에 주소만 있음 (확인 아님)
- unverified  근거를 확인하지 못함 (일반 지식 포함)
- conflict    출처마다 값이 다름 → 사용자 검토 필요
- missing     찾지 못함 → 정보 확인 필요
"""

import re

USER_NOTES_ID = "u1"  # 사용자가 입력 화면에 직접 쓴 참고 자료

# (key, 이름, 공식 자료만 허용)
ITEMS = {
    "character": [
        ("official_name", "캐릭터 이름·공식 표기", False), ("series", "작품·시리즈명", False), ("creator", "제작자", False),
        ("debut", "첫 등장·데뷔 정보", False), ("birthday", "생일 등 공식 프로필", False), ("personality", "성격과 특징", False),
        ("favorite", "좋아하는 것", False), ("friends", "친구·관련 캐릭터", False), ("relations", "관계 설명", False),
        ("tmi", "공식 TMI", False), ("official_account", "공식 계정", False),
    ],
    "goods": [
        ("product_names", "상품명", True), ("official_images", "공식 상품 이미지 위치", False), ("release_date", "출시일", True),
        ("seller", "판매처", True), ("price", "가격", True), ("size", "크기·규격", True), ("material", "소재", True),
        ("components", "구성품", True), ("features", "상품별 특징", False), ("how_to_buy", "구매 방법", True),
        ("purchase_limit", "구매 제한", True), ("shipping", "판매·배송 안내", True), ("benefits", "구매 혜택·특전", True),
    ],
    "collab": [
        ("partners", "협업 브랜드·캐릭터", True), ("collab_name", "콜라보 명칭", True), ("period", "진행 기간", True),
        ("place", "장소·판매처", True), ("content", "협업 내용", True), ("menu", "메뉴·상품 구성", True),
        ("item_prices", "상품별 가격", True), ("perks", "특전·이벤트", True), ("perk_conditions", "특전 제공 조건", True),
        ("how_to_join", "참여 방법", True),
    ],
    "popup": [
        ("popup_name", "팝업스토어 명칭", True), ("period", "진행 기간", True), ("hours", "운영 시간", True), ("place", "장소", True),
        ("closed_days", "휴무일", True), ("entry", "입장 방법", True), ("reservation", "사전 예약 여부", True),
        ("goods", "현장 판매 굿즈", True), ("goods_prices", "굿즈 가격", True), ("purchase_limit", "구매 제한", True),
        ("photozone", "포토존", True), ("perks", "방문 특전", True), ("notices", "유의 사항", True),
    ],
}
STATE_LABELS = {"verified": "공식 확인", "secondary": "2차 자료", "user": "사용자 제공", "listed": "검색 목록만",
                "unverified": "근거 없음", "conflict": "출처 충돌", "missing": "정보 확인 필요"}


def keys_of(content_type: str) -> list[str]:
    return [key for key, _, _ in ITEMS.get(content_type, [])]


def checklist_text(content_type: str) -> str:
    lines = ["[조사 항목] 아래 항목을 하나씩 찾아 items에 적는다. key는 그대로 쓴다."]
    for key, label, strict in ITEMS[content_type]:
        lines.append(f"- {key}: {label}{' (공식 출처만)' if strict else ''}")
    lines += [
        "- value는 출처 표기 그대로 짧게 쓴다. 숫자·날짜·가격은 바꾸거나 계산하지 않는다.",
        "- quote에는 근거가 된 페이지 문장을 80자 이내로 그대로 옮긴다. 사용자 참고 자료가 근거면 그 문장을 옮긴다.",
        "- sourceIds에는 그 값을 실제로 읽은 sources id를 적는다. 사용자 참고 자료가 근거면 u1을 적는다.",
        "- 찾지 못한 항목도 빠뜨리지 않고 value를 빈 문자열, sourceIds를 빈 배열로 적는다. 일반 지식이나 짐작으로 채우지 않는다.",
        "- 같은 항목의 값이 출처마다 다르면 값마다 따로 items에 넣는다. 하나로 고르지 않는다.",
        "- 카드 fields에는 items에서 출처로 확인된 값만 쓴다.",
    ]
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"[\s·,./~\-()]+", "", text).lower()


def verify_items(content_type: str, raw_items: list, sources: list[dict]) -> list[dict]:
    """AI가 적은 항목을 정리합니다. 같은 항목은 하나로 합치고, 값이 다르면 출처 충돌로 표시합니다."""
    by_id = {s["id"]: s for s in sources}
    grouped: dict[str, list[dict]] = {}
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict) or raw.get("key") not in keys_of(content_type):
            continue
        value = " ".join(str(raw.get("value") or "").split())[:200]
        ids = [i for i in raw.get("sourceIds", []) if i in by_id]
        grouped.setdefault(raw["key"], []).append({"value": value, "quote": " ".join(str(raw.get("quote") or "").split())[:160], "sourceIds": ids})

    items = []
    for key, label, strict in ITEMS[content_type]:
        entries = [e for e in grouped.get(key, []) if e["value"]]
        merged: dict[str, dict] = {}  # 같은 값은 출처를 합칩니다 (중복 정리)
        for entry in entries:
            slot = merged.setdefault(_norm(entry["value"]), {**entry, "sourceIds": []})
            slot["sourceIds"] = list(dict.fromkeys(slot["sourceIds"] + entry["sourceIds"]))
            slot["quote"] = slot["quote"] or entry["quote"]
        values = list(merged.values())
        main = values[0] if values else {"value": "", "quote": "", "sourceIds": []}
        state = _state(main, values, by_id)
        items.append({"key": key, "label": label, "strict": strict, "value": main["value"], "quote": main["quote"],
                      "sourceIds": main["sourceIds"], "alternatives": values[1:], "state": state})
    return items


def _state(main: dict, values: list[dict], by_id: dict) -> str:
    if not main["value"]:
        return "missing"
    if len(values) > 1:
        return "conflict"
    cited = [by_id[i] for i in main["sourceIds"]]
    verifications = {s["verification"] for s in cited}
    read = [s for s in cited if s["verification"] == "fetched"]
    if any(s["kind"] == "official" for s in read):
        return "verified"
    if read:
        return "secondary"
    if "user_provided" in verifications:
        return "user"
    if "search_result" in verifications:
        return "listed"
    return "unverified"


def facts_from_items(items: list[dict]) -> list[dict]:
    """예전 형식의 facts(숫자 대조, 화면 표시)에 쓰도록 확인된 항목을 문장으로 만듭니다."""
    facts = []
    for item in items:
        for entry in [item] + item["alternatives"]:
            if entry["value"]:
                facts.append({"text": f"{item['label']}: {entry['value']}", "sourceIds": entry["sourceIds"],
                              "origin": "ai", "item": item["key"]})
    return facts


def field_states(cards: list[dict], templates_of, items: list[dict] | None, card_state) -> dict:
    """카드 필드마다 어떤 근거에서 왔는지 표시합니다. {frame: {field: state}}

    templates_of(frame) → 템플릿, card_state(card) → 카드 출처 상태(verified/user_provided/listed/...)
    """
    by_key = {i["key"]: i for i in items or []}
    fallback = {"verified": "verified", "user_provided": "user", "listed": "listed"}
    result = {}
    for card in cards:
        tpl = templates_of(card["frame"])
        card_level = fallback.get(card_state(card), "unverified")
        states = {}
        for field in tpl["fields"]:
            key = field.get("item")
            if not key or field["type"] == "flag":
                continue
            value = card["fields"].get(field["key"])
            item_state = by_key[key]["state"] if key in by_key else "missing"
            if not value:
                states[field["key"]] = "missing"
            elif item_state in ("verified", "secondary", "conflict"):
                states[field["key"]] = item_state  # 페이지에서 확인한 항목, 또는 출처끼리 다른 항목
            elif card_level == "user":
                states[field["key"]] = "user"  # 사용자 자료로 쓴 카드
            elif item_state != "missing":
                states[field["key"]] = item_state
            else:
                states[field["key"]] = card_level
        result[card["frame"]] = states
    return result
