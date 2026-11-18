"""사진으로 확정한 캐릭터와 카드 문구를 잇습니다 (캐릭터 소개 card-04의 친구 칸).

- 친구 칸(identify가 있는 이미지 자리)에 사진을 넣으면 그 사진의 캐릭터 이름을 확인해 slotIdentities에 둡니다.
- 사용자가 이름을 확정하면 친구 항목의 이름과 slot을 서버가 정합니다. AI는 관계·TMI만 씁니다.
- 친구 칸에 사진이 있으면 그 카드에는 확정한 친구와 중심 캐릭터 말고 다른 캐릭터 이름을 쓰지 않습니다.

slotIdentities[frame][slot] = {assetId, status, name, suggested, confidence, candidates, evidence, error}
status: processing(AI 확인 중) / suggested(AI 제안) / failed / manual(직접 입력) / confirmed(사용자 확정)
"""

import re

from . import templates
from .provider import FRAMES

COVER_NAME_KEY = "character_name"
NAME_MAX = 20
_SPLIT = re.compile(r"[,，、/·|\n;]+|\s+(?:및|그리고)\s+")
_PAREN = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_GENERIC = {"친구", "친구들", "동료", "가족", "라이벌", "단짝", "캐릭터", "주인공", "관계", "없음"}


def frames(job: dict) -> list[str]:
    if not templates.is_template_job(job):
        return []
    return [f for f in FRAMES if templates.identify_slots(templates.template_for(job, f))]


def slots(job: dict, frame: str) -> list[dict]:
    return templates.identify_slots(templates.template_for(job, frame))


def is_identify_slot(job: dict, frame: str, slot: str) -> bool:
    return frame in frames(job) and slot in {s["key"] for s in slots(job, frame)}


def _field(job: dict, frame: str) -> dict:
    key = slots(job, frame)[0]["identify"]
    return next(f for f in templates.template_for(job, frame)["fields"] if f["key"] == key)


def name_max(job: dict, frame: str) -> int:
    field = _field(job, frame)
    sub = next(s for s in field["fields"] if s["key"] == field["linkedName"])
    return sub["max"]


def _image(job: dict, frame: str, slot: str) -> dict | None:
    return ((job.get("slotImages") or {}).get(frame) or {}).get(slot)


def identity(job: dict, frame: str, slot: str) -> dict | None:
    """지금 그 자리에 있는 사진의 식별 기록. 사진이 바뀌었으면 옛 기록은 쓰지 않습니다."""
    record = ((job.get("slotIdentities") or {}).get(frame) or {}).get(slot)
    image = _image(job, frame, slot)
    return record if record and image and record["assetId"] == image["assetId"] else None


def filled(job: dict, frame: str) -> list[str]:
    return [s["key"] for s in slots(job, frame) if _image(job, frame, s["key"])]


def confirmed(job: dict, frame: str) -> list[tuple[str, str]]:
    """사진 자리 순서대로 (slot, 확정 이름)."""
    result = []
    for key in filled(job, frame):
        record = identity(job, frame, key)
        if record and record["status"] == "confirmed":
            result.append((key, record["name"]))
    return result


def ready(job: dict, frame: str) -> bool:
    """친구 칸 사진이 있고, 모두 이름을 확정했는지."""
    keys = filled(job, frame)
    return bool(keys) and len(confirmed(job, frame)) == len(keys)


def main_name(job: dict, cards: list[dict] | None = None) -> str:
    cards = cards if cards is not None else (job.get("outline") or {}).get("cards", [])
    cover = next((c for c in cards if c["frame"] == FRAMES[0]), None)
    return str(((cover or {}).get("fields") or {}).get(COVER_NAME_KEY) or "").strip()


def _card(job: dict, frame: str) -> dict | None:
    return next((c for c in (job.get("outline") or {}).get("cards", []) if c["frame"] == frame), None)


def sync(job: dict) -> bool:
    """친구 항목을 확정한 이름과 사진 순서에 맞춥니다. 바뀌었으면 True.

    - 친구 칸에 사진이 없으면 지금 친구를 그대로 두고 slot만 비웁니다.
    - 사진이 있으면 확정한 친구만 남깁니다. 같은 이름이던 항목의 관계는 이어 쓰고, 빠진 이름은 금지 이름으로 기억합니다.
    """
    changed = False
    for frame in frames(job):
        card = _card(job, frame)
        if not card:
            continue
        field = _field(job, frame)
        name_key, subs = field["linkedName"], [s["key"] for s in field["fields"]]
        items = [i for i in card["fields"].get(field["key"]) or [] if isinstance(i, dict)]
        if not filled(job, frame):
            new = [{**i, "slot": ""} for i in items]
        else:
            chosen = confirmed(job, frame)
            names = {n for _, n in chosen}
            by_slot = {i.get("slot"): i for i in items if i.get("slot")}
            by_name = {i.get(name_key): i for i in items if i.get(name_key)}
            new = []
            for key, name in chosen:
                same = by_slot.get(key)
                base = same if same and same.get(name_key) == name else by_name.get(name, {})
                new.append({**{s: "" for s in subs}, **base, name_key: name, "slot": key})
            dropped = [i[name_key] for i in items if i.get(name_key) and i[name_key] not in names]
            remember(job, dropped)
        if new != items:
            card["fields"][field["key"]] = new
            changed = True
    return changed


def remember(job: dict, names: list[str]) -> None:
    """사진과 맞지 않아 뺀 캐릭터 이름. 이후 문구에 다시 나오면 막습니다."""
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
    """이 카드에 쓰면 안 되는 캐릭터 이름 후보: 조사에서 나온 관련 캐릭터, 사진과 달라 뺀 친구, AI가 제안했지만 확정하지 않은 이름."""
    found = list((job.get("outline") or {}).get("otherNames", []))
    for item in (job.get("research") or {}).get("items") or []:
        if item.get("key") == "friends":
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
    """금지 이름을 찾을 문구. 서버가 정하는 친구 이름과 slot은 빼고 봅니다."""
    field = _field(job, frame)
    texts = []
    for f in templates.template_for(job, frame)["fields"]:
        value = (card.get("fields") or {}).get(f["key"])
        if f["key"] == field["key"]:
            for item in value or []:
                texts += [str(v) for k, v in item.items() if k not in (field["linkedName"], "slot") and v]
        else:
            texts += templates._strings(value)
    return texts


def violations(job: dict, frame: str, card: dict, cards: list[dict] | None = None) -> list[str]:
    """친구 칸에 사진이 있는 카드에서, 확정한 친구와 중심 캐릭터 말고 다른 캐릭터 이름을 찾습니다."""
    if frame not in frames(job) or not filled(job, frame):
        return []
    allowed = [n for _, n in confirmed(job, frame)] + [main_name(job, cards)]
    others = other_names(job, frame, allowed)
    hits = []
    for text in _texts(job, frame, card):
        masked = text
        for name in sorted(filter(None, allowed), key=len, reverse=True):
            masked = masked.replace(name, "\0")
        hits += [n for n in others if n in masked and n not in hits]
    if not hits:
        return []
    names = ", ".join(n for _, n in confirmed(job, frame)) or "없음"
    main = main_name(job, cards)
    return [f"확정하지 않은 캐릭터 이름이 들어 있어요: {', '.join(hits)}. 확정한 친구({names}){f'와 중심 캐릭터({main})' if main else ''}만 써 주세요"]


def add_issues(job: dict, cards: list[dict], issues: dict) -> None:
    for frame in frames(job):
        card = next((c for c in cards if c["frame"] == frame), None)
        if not card or frame not in issues:
            continue
        errors = issues[frame]["errors"]
        labels = {s["key"]: s["label"] for s in slots(job, frame)}
        for key in filled(job, frame):
            record = identity(job, frame, key)
            if record and record["status"] == "confirmed":
                continue
            if record and record["status"] == "processing":
                errors.append(f"{labels[key]}: 사진 속 캐릭터 이름을 확인하고 있어요. 끝나면 이름을 확정해 주세요")
            else:
                errors.append(f"{labels[key]}: 사진 속 캐릭터 이름을 확인하고 확정해 주세요")
        field = _field(job, frame)
        if filled(job, frame):
            written = [(i.get("slot"), i.get(field["linkedName"])) for i in card["fields"].get(field["key"]) or []]
            if written != confirmed(job, frame):
                errors.append("친구 이름이 사진에서 확정한 이름과 맞지 않아요. 친구 칸에서 이름을 다시 확정해 주세요")
        errors += violations(job, frame, card, cards)


def rules_text(job: dict) -> str:
    """AI 프롬프트에 넣는 친구 규칙. 친구 칸에 사진이 없으면 빈 문자열입니다."""
    lines = []
    for frame in frames(job):
        if not filled(job, frame):
            continue
        field = _field(job, frame)
        chosen = confirmed(job, frame)
        main = main_name(job)
        lines.append(f"[사진으로 확정한 친구: {frame}]")
        if chosen:
            lines.append(f"- {field['key']}는 아래 목록 그대로, 이 순서로 쓴다. {field['linkedName']}과 slot은 바꾸지 않는다.")
            lines += [f"  - slot={key}, {field['linkedName']}={name}" for key, name in chosen]
        else:
            lines.append(f"- 사진 속 캐릭터 이름을 아직 확정하지 않았다. {field['key']}는 빈 배열로 둔다.")
        lines.append(f"- 이 카드의 관계·TMI 문구에는 확정한 친구{f'와 중심 캐릭터({main})' if main else ''}만 쓴다. 목록에 없는 캐릭터 이름은 쓰지 않는다.")
        lines.append("- 자료에 확정한 친구의 정보가 없으면 그 친구의 관계는 빈 문자열로 둔다. 다른 캐릭터 정보로 채우지 않는다.")
    return "\n".join(lines)


def unknown_names(job: dict, names: list[str]) -> list[str]:
    """저장된 조사 자료에 한 번도 나오지 않는 이름. 이 이름들만 짧게 다시 조사합니다."""
    research = job.get("research") or {}
    text = " ".join([f.get("text", "") for f in research.get("facts", [])]
                    + [f"{i.get('value', '')} {i.get('quote', '')}" for i in research.get("items") or []])
    return [n for n in names if n not in text]
