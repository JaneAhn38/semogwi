"""캐릭터 소개 card-04의 친구 칸: 사진 확인과 다른 캐릭터 이름 금지.

- 사진과 친구는 자리 번호로 잇습니다: friend_image_N이 N번째 친구의 사진입니다.
  사진이 없는 친구도 지우지 않습니다. 1·3번에만 사진이 있으면 2번째 친구는 사진 없이 그려집니다.
  친구를 지우거나 순서를 바꾸면 사진이 그 친구를 따라갑니다(templates.remap_item_slots).
- 친구 이름은 사용자가 고른 이름(또는 직접 고친 이름)입니다. 사진은 이름을 바꾸지 않습니다.
  칸에 사진을 넣으면 AI가 사진 속 캐릭터를 알아보고, 그 번호 친구의 이름과 달라 보이면 경고만 합니다 (승인은 막지 않음).
- 칸에 사진이 있으면 그 카드에는 목록의 친구와 중심 캐릭터 말고 다른 캐릭터 이름을 쓰지 않습니다 (이건 승인을 막음).

slotIdentities[frame][slot] = {assetId, status, suggested, confidence, candidates, evidence, error}
status: processing(AI 확인 중) / suggested(AI 결과) / failed / manual(데모: 확인하지 않음)
기록은 사진(assetId)을 따라갑니다. 사진이 다른 자리로 옮겨지면 rekey가 기록도 그 자리로 옮깁니다.
"""

import re

from . import templates
from .provider import FRAMES

COVER_NAME_KEY = "character_name"
NAME_MAX = 20
WARN_CONFIDENCE = ("높음", "중간")  # 확신이 낮은 결과로는 경고하지 않습니다
_SPLIT = re.compile(r"[,，、/·|\n;]+|\s+(?:및|그리고)\s+")
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_GENERIC = {"친구", "친구들", "동료", "가족", "라이벌", "단짝", "캐릭터", "주인공", "관계", "없음", "엄마", "아빠", "형", "누나", "언니", "오빠", "동생"}


def frames(job: dict) -> list[str]:
    if not templates.is_template_job(job):
        return []
    return [f for f in FRAMES if templates.identify_slots(templates.template_for(job, f))]


def _card(job: dict, frame: str) -> dict | None:
    return next((c for c in (job.get("outline") or {}).get("cards", []) if c["frame"] == frame), None)


def _field(job: dict, frame: str, card: dict | None = None) -> dict:
    """사진과 잇는 항목 (조건이 있는 템플릿이면 지금 카드에 보이는 쪽)."""
    tpl = templates.template_for(job, frame)
    keys = list(dict.fromkeys(s["identify"] for s in templates.identify_slots(tpl)))
    fields = [f for f in tpl["fields"] if f["key"] in keys]
    card = card if card is not None else _card(job, frame)
    values = (card or {}).get("fields") or {}
    return next((f for f in fields if templates.condition_met(tpl, values, f.get("if"))), fields[0])


def slots(job: dict, frame: str, card: dict | None = None) -> list[dict]:
    """사진 자리, 번호 순서대로."""
    key = _field(job, frame, card)["key"]
    return [s for s in templates.identify_slots(templates.template_for(job, frame)) if s["identify"] == key]


def is_identify_slot(job: dict, frame: str, slot: str) -> bool:
    return frame in frames(job) and slot in {s["key"] for s in slots(job, frame)}


def _image(job: dict, frame: str, slot: str) -> dict | None:
    return ((job.get("slotImages") or {}).get(frame) or {}).get(slot)


def rekey(job: dict, frame: str) -> None:
    """식별 기록을 지금 그 사진이 있는 자리로 옮깁니다. 사진이 없어진 기록은 지웁니다."""
    records = (job.get("slotIdentities") or {}).get(frame)
    if not records:
        return
    by_asset = {r["assetId"]: r for r in records.values() if r.get("assetId")}
    moved = {}
    for key, image in ((job.get("slotImages") or {}).get(frame) or {}).items():
        if image and image.get("assetId") in by_asset:
            moved[key] = by_asset[image["assetId"]]
    job["slotIdentities"][frame] = moved


def sync(job: dict) -> None:
    """사진을 옮기거나 지운 뒤 식별 기록을 사진에 맞춥니다. 친구 이름은 바꾸지 않습니다."""
    for frame in frames(job):
        rekey(job, frame)


def identity(job: dict, frame: str, slot: str) -> dict | None:
    """지금 그 자리에 있는 사진의 식별 기록. 사진이 바뀌었으면 옛 기록은 쓰지 않습니다."""
    image = _image(job, frame, slot)
    if not image:
        return None
    records = ((job.get("slotIdentities") or {}).get(frame) or {}).values()
    return next((r for r in records if r.get("assetId") == image["assetId"]), None)


def filled(job: dict, frame: str, card: dict | None = None) -> list[str]:
    return [s["key"] for s in slots(job, frame, card) if _image(job, frame, s["key"])]


def main_name(job: dict, cards: list[dict] | None = None) -> str:
    cards = cards if cards is not None else (job.get("outline") or {}).get("cards", [])
    cover = next((c for c in cards if c["frame"] == FRAMES[0]), None)
    return str(((cover or {}).get("fields") or {}).get(COVER_NAME_KEY) or "").strip()


def same_character(a: str, b: str) -> bool:
    """'히로시'와 '노하라 히로시'처럼 한쪽이 다른 쪽을 품으면 같은 캐릭터로 봅니다."""
    a, b = "".join(str(a or "").split()), "".join(str(b or "").split())
    return bool(a and b) and (a in b or b in a)


def _items(job: dict, frame: str, card: dict) -> list[dict]:
    field = _field(job, frame, card)
    return [i for i in (card.get("fields") or {}).get(field["key"]) or [] if isinstance(i, dict)]


def _names(job: dict, frame: str, card: dict) -> list[str]:
    """카드 목록에 있는 친구 이름, 순서대로."""
    key = _field(job, frame, card)["linkedName"]
    return [str(i.get(key) or "").strip() for i in _items(job, frame, card)]


def listed_names(job: dict, frame: str) -> list[str]:
    card = _card(job, frame)
    return _names(job, frame, card) if card else []


def photo_notes(job: dict, frame: str, card: dict) -> list[str]:
    """사진 확인 결과 안내 (승인은 막지 않음): 확인 중, 고른 친구와 달라 보이는 사진."""
    notes = []
    names = _names(job, frame, card)
    for n, slot in enumerate(slots(job, frame, card)):
        record = identity(job, frame, slot["key"])
        if not record:
            continue
        name = names[n] if n < len(names) else ""
        if record["status"] == "processing":
            notes.append(f"{slot['label']}: 사진 속 캐릭터를 확인하고 있어요")
        elif record["status"] == "failed":
            notes.append(f"{slot['label']}: {record.get('error') or '사진 속 캐릭터를 확인하지 못했어요'}")
        elif (record["status"] == "suggested" and record.get("suggested") and record.get("confidence") in WARN_CONFIDENCE
              and name and not same_character(record["suggested"], name)):
            notes.append(f"{slot['label']}: 사진이 '{record['suggested']}'처럼 보여요 (고른 친구: {name}). "
                         "사진을 바꾸거나 친구를 다시 골라 주세요. 맞는 사진이면 그대로 둬도 돼요")
    return notes


def keep_people(job: dict, frame: str, before: list[dict]) -> None:
    """AI가 다시 쓴 카드에서 친구 수·순서·이름을 다시 쓰기 전 목록으로 되돌립니다.

    AI는 관계·TMI만 씁니다. 같은 이름 항목의 관계·TMI를 가져오고, 없으면 빈 문자열로 둡니다
    (사용자가 고른 친구를 AI가 다른 캐릭터로 바꾸지 못하게).
    """
    card = _card(job, frame)
    if not card or frame not in frames(job):
        return
    field = _field(job, frame, card)
    name_key, blank = field["linkedName"], {s["key"]: "" for s in field["fields"]}
    written = {i.get(name_key): i for i in _items(job, frame, card) if i.get(name_key)}
    card["fields"][field["key"]] = [{**blank, **written.get(i.get(name_key), {}), name_key: i.get(name_key, "")}
                                    for i in before if isinstance(i, dict)]


def photo_lists(job: dict) -> dict[str, list[dict]]:
    """사진을 넣은 친구 칸의 지금 친구 목록 (다시 쓰기 전에 받아 두었다가 keep_people로 되돌립니다)."""
    result = {}
    for frame in frames(job):
        card = _card(job, frame)
        if card and filled(job, frame, card):
            result[frame] = [dict(i) for i in _items(job, frame, card)]
    return result


def remember(job: dict, names: list[str]) -> None:
    """카드에서 빠진 캐릭터 이름 (예: 다시 고르기 전 친구). 이후 문구에 다시 나오면 막습니다."""
    if not job.get("outline"):
        return
    known = job["outline"].setdefault("otherNames", [])
    for name in names:
        name = " ".join(str(name).split())
        if name and name not in known:
            known.append(name)
    del known[:-30]


def _tokens(text: str) -> list[str]:
    parts = [" ".join(_PAREN.sub("", t).split()) for t in _SPLIT.split(text or "")]
    return [t for t in parts if 2 <= len(t) <= 10 and " " not in t and t not in _GENERIC]


def other_names(job: dict, frame: str, allowed: list[str]) -> list[str]:
    """이 카드에 쓰면 안 되는 캐릭터 이름 후보: 조사에서 나온 관련 캐릭터, 카드에서 빠진 캐릭터, 사진 확인에서 나온 다른 이름."""
    found = list((job.get("outline") or {}).get("otherNames", []))
    item_keys = {f.get("item") or f["key"] for f in templates.template_for(job, frame)["fields"] if f.get("linkedName")}
    for item in (job.get("research") or {}).get("items") or []:
        if item.get("key") in item_keys:
            for entry in [item] + item.get("alternatives", []):
                found += _tokens(entry.get("value", ""))
    for record in ((job.get("slotIdentities") or {}).get(frame) or {}).values():
        found += [record.get("suggested") or ""] + list(record.get("candidates") or [])
    allowed = [a for a in allowed if a]
    result = []
    for name in found:
        name = " ".join(str(name).split())
        if len(name) < 2 or name in _GENERIC or name in result or any(name in a or a in name for a in allowed):
            continue
        result.append(name)
    return result


def _texts(job: dict, frame: str, card: dict) -> list[str]:
    """금지 이름을 찾을 문구. 친구 이름 칸은 빼고 봅니다."""
    field = _field(job, frame, card)
    texts = []
    for f in templates.template_for(job, frame)["fields"]:
        value = (card.get("fields") or {}).get(f["key"])
        if f["key"] == field["key"]:
            for item in value or []:
                texts += [str(v) for k, v in item.items() if k != field["linkedName"] and v]
        elif f.get("linkedName"):
            continue  # 카드에 보이지 않는 목록
        else:
            texts += templates._strings(value)
    return texts


def violations(job: dict, frame: str, card: dict, cards: list[dict] | None = None) -> list[str]:
    """칸에 사진이 있는 카드에서, 목록의 친구와 중심 캐릭터 말고 다른 캐릭터 이름을 찾습니다."""
    if frame not in frames(job) or not filled(job, frame, card):
        return []
    listed = [n for n in _names(job, frame, card) if n]
    main = main_name(job, cards)
    allowed = listed + [main]
    others = other_names(job, frame, allowed)
    hits = []
    for text in _texts(job, frame, card):
        masked = text
        for name in sorted(filter(None, allowed), key=len, reverse=True):
            masked = masked.replace(name, "\0")
        hits += [n for n in others if n in masked and n not in hits]
    if not hits:
        return []
    names = ", ".join(listed) or "없음"
    return [f"목록에 없는 캐릭터 이름이 들어 있어요: {', '.join(hits)}. 목록의 친구({names}){f'와 중심 캐릭터({main})' if main else ''}만 써 주세요"]


def add_issues(job: dict, cards: list[dict], issues: dict) -> None:
    for frame in frames(job):
        card = next((c for c in cards if c["frame"] == frame), None)
        if not card or frame not in issues:
            continue
        issues[frame]["warnings"] += photo_notes(job, frame, card)
        written = _names(job, frame, card)
        repeated = sorted({n for n in written if n and written.count(n) > 1})
        if repeated and filled(job, frame, card):  # 사진을 넣었을 때만 (사진이 어느 친구 것인지 헷갈리지 않게)
            issues[frame]["errors"].append(f"{_field(job, frame, card)['label']}에 같은 캐릭터가 두 번 들어 있어요: {', '.join(repeated)}. 한 명을 다른 친구로 바꿔 주세요")
        issues[frame]["errors"] += violations(job, frame, card, cards)


def rules_text(job: dict) -> str:
    """AI 프롬프트에 넣는 규칙. 칸에 사진이 없으면 빈 문자열입니다."""
    lines = []
    for frame in frames(job):
        if not filled(job, frame):
            continue
        card = _card(job, frame) or {"fields": {}}
        field = _field(job, frame, card)
        key_name = field["linkedName"]
        written = _names(job, frame, card)
        photos = {n + 1: s["key"] for n, s in enumerate(slots(job, frame, card)) if _image(job, frame, s["key"])}
        main = main_name(job)
        lines.append(f"[사진이 붙은 {field['label']}: {frame}]")
        lines.append(f"- {field['key']}는 아래 목록 그대로, 이 순서로 {len(written)}명을 쓴다. {key_name}은 바꾸지 않는다 (N번째 항목 = N번 사진).")
        lines += [f"  - {n}번째: {key_name}={name}{f' (사진 {photos[n]})' if n in photos else ''}" for n, name in enumerate(written, 1)]
        lines.append(f"- 이 카드의 관계·TMI 문구에는 목록의 캐릭터{f'와 중심 캐릭터({main})' if main else ''}만 쓴다. 목록에 없는 캐릭터 이름은 쓰지 않는다.")
        lines.append("- 자료에 그 캐릭터의 정보가 없으면 관계·TMI는 빈 문자열로 둔다. 다른 캐릭터 정보로 채우지 않는다.")
    return "\n".join(lines)


def unknown_names(job: dict, names: list[str]) -> list[str]:
    """저장된 조사 자료에 한 번도 나오지 않는 이름. 이 이름들만 짧게 다시 조사합니다."""
    research = job.get("research") or {}
    text = " ".join([f.get("text", "") for f in research.get("facts", [])]
                    + [f"{i.get('value', '')} {i.get('quote', '')}" for i in research.get("items") or []])
    return [n for n in names if n not in text]
