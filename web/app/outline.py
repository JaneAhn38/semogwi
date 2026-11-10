"""구성안 문구 규칙. 기존 slides.json 규격(scripts/fill_figma.py validate)의 오류 기준과 같습니다.

한 줄 42자 경고는 적용하지 않습니다. Figma가 한글을 글자 단위로 줄바꿈해서 생긴 규칙이고,
웹 렌더러는 띄어쓰기 단위로 줄을 바꾸기 때문입니다.
"""

import re

from pydantic import BaseModel, ConfigDict

TITLE_MAX = 20
TITLE_SAFE = 16
BODY_MAX = 80
BODY_MAX_LINES = 2
SOURCE_MAX = 30
SOURCE_PREFIX = "출처: "
ROLE_MAX = 10


class CardEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: str
    title: str
    body: str
    source: str = ""


def _length(text: str) -> int:
    return len(text.replace("\r", "").replace("\n", ""))


def check_card(card: dict) -> dict:
    """{errors, warnings}. errors가 있으면 승인할 수 없습니다."""
    errors, warnings = [], []
    title, body, source = card["title"], card["body"], card.get("source", "")
    role = card.get("role", "")

    if not role:
        errors.append("역할을 입력해 주세요")
    elif len(role) > ROLE_MAX:
        errors.append(f"역할은 {ROLE_MAX}자 이내로 입력해 주세요 (현재 {len(role)}자)")

    if not title:
        errors.append("제목을 입력해 주세요")
    elif "\n" in title:
        errors.append("제목에는 줄바꿈을 넣을 수 없어요")
    elif len(title) > TITLE_MAX:
        errors.append(f"제목은 {TITLE_MAX}자 이내로 입력해 주세요 (현재 {len(title)}자)")
    elif len(title) > TITLE_SAFE:
        warnings.append(f"제목이 {TITLE_SAFE}자를 넘으면 글자가 작아지거나 줄이 늘어날 수 있어요")

    if not body:
        errors.append("본문을 입력해 주세요")
    elif _length(body) > BODY_MAX:
        errors.append(f"본문은 {BODY_MAX}자 이내로 입력해 주세요 (현재 {_length(body)}자)")
    elif len(body.replace("\r", "").split("\n")) > BODY_MAX_LINES:
        warnings.append(f"본문은 {BODY_MAX_LINES}줄 이하를 권장해요")

    if source:
        if "\n" in source:
            errors.append("출처에는 줄바꿈을 넣을 수 없어요")
        elif len(source) > SOURCE_MAX:
            errors.append(f"출처는 {SOURCE_MAX}자 이내로 입력해 주세요 (현재 {len(source)}자)")
        elif not source.startswith(SOURCE_PREFIX):
            errors.append(f"출처는 '{SOURCE_PREFIX}'로 시작해 주세요")
    return {"errors": errors, "warnings": warnings}


def unsupported_numbers(text: str, material: str) -> list[str]:
    """문구의 숫자(가격, 날짜, 수량) 중 자료에 없는 것을 찾습니다. 임의로 만든 가격·일정을 막기 위한 검사입니다."""
    def numbers(source: str) -> list[str]:
        return [token.rstrip(",.") for token in re.findall(r"\d[\d,.]*", source)]

    # 숫자 단위로 비교합니다. "40"이 "440"의 일부라고 통과하지 않게 합니다.
    known = {n.replace(",", "") for n in numbers(material)}
    missing = []
    for token in numbers(text):
        if token.replace(",", "") not in known and token not in missing:
            missing.append(token)
    return missing


def issues_of(cards: list[dict]) -> dict:
    return {card["frame"]: check_card(card) for card in cards}
