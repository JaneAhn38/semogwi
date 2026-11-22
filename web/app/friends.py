"""사진으로 확정한 캐릭터와 카드 문구를 잇습니다 (캐릭터 소개 card-04의 친구·가족 칸).

- 칸(identify가 있는 이미지 자리)에 사진을 넣으면 그 사진의 캐릭터 이름을 확인해 slotIdentities에 둡니다.
- 사진과 항목은 자리 번호로 잇습니다: friend_image_N(가족은 family_image_N)이 N번째 항목의 사진입니다.
  사진이 없는 항목도 지우지 않습니다. 1·3번에만 사진이 있으면 2번째 항목은 사진 없이 그려집니다.
  항목을 지우거나 순서를 바꾸면 사진이 그 항목을 따라갑니다(templates.remap_item_slots).
- 사용자가 이름을 확정하면 그 번호 항목의 이름을 서버가 정합니다. AI는 관계·TMI만 씁니다.
- 칸에 사진이 있으면 그 카드에는 목록의 캐릭터(확정한 이름, 사진 없는 항목의 이름)와 중심 캐릭터 말고
  다른 캐릭터 이름을 쓰지 않습니다.
- 카드에는 친구 또는 가족 중 고른 쪽(category)만 보이므로, 확인도 고른 쪽 칸만 합니다.

slotIdentities[frame][slot] = {assetId, status, name, suggested, confidence, candidates, evidence, error}
status: processing(AI 확인 중) / suggested(AI 제안) / failed / manual(직접 입력) / confirmed(사용자 확정)
기록은 사진(assetId)을 따라갑니다. 사진이 다른 자리로 옮겨지면 rekey가 기록도 그 자리로 옮깁니다.
"""

import re

from . import templates
from .provider import FRAMES

COVER_NAME_KEY = "character_name"
NAME_MAX = 20
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
    """사진으로 이름을 확인하는 항목 가운데 지금 카드에 보이는 쪽(친구 또는 가족)."""
    tpl = templates.template_for(job, frame)
    keys = list(dict.fromkeys(s["identify"] for s in templates.identify_slots(tpl)))
    fields = [f for f in tpl["fields"] if f["key"] in keys]
    card = card if card is not None else _card(job, frame)
    values = (card or {}).get("fields") or {}
    return next((f for f in fields if templates.condition_met(tpl, values, f.get("if"))), fields[0])


def slots(job: dict, frame: str, card: dict | None = None) -> list[dict]:
    """지금 보이는 쪽의 사진 자리, 번호 순서대로."""
    key = _field(job, frame, card)["key"]
    return [s for s in templates.identify_slots(templates.template_for(job, frame)) if s["identify"] == key]


def is_identify_slot(job: dict, frame: str, slot: str) -> bool:
    return frame in frames(job) and slot in {s["key"] for s in slots(job, frame)}


def name_max(job: dict, frame: str) -> int:
    field = _field(job, frame)
    sub = next(s for s in field["fields"] if s["key"] == field["linkedName"])
    return sub["max"]


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


def identity(job: dict, frame: str, slot: str) -> dict | None:
    """지금 그 자리에 있는 사진의 식별 기록. 사진이 바뀌었으면 옛 기록은 쓰지 않습니다."""
    image = _image(job, frame, slot)
    if not image:
        return None
    records = ((job.get("slotIdentities") or {}).get(frame) or {}).values()
    return next((r for r in records if r.get("assetId") == image["assetId"]), None)


def filled(job: dict, frame: str, card: dict | None = None) -> list[str]:
    return [s["key"] for s in slots(job, frame, card) if _image(job, frame, s["key"])]


def confirmed(job: dict, frame: str, card: dict | None = None) -> list[tuple[str, str]]:
    """사진 자리 순서대로 (slot, 확정 이름)."""
    result = []
    for key in filled(job, frame, card):
        record = identity(job, frame, key)
        if record and record["status"] == "confirmed":
            result.append((key, record["name"]))
    return result


def ready(job: dict, frame: str) -> bool:
    """칸에 사진이 있고, 모두 이름을 확정했는지."""
    keys = filled(job, frame)
    return bool(keys) and len(confirmed(job, frame)) == len(keys)


def main_name(job: dict, cards: list[dict] | None = None) -> str:
    cards = cards if cards is not None else (job.get("outline") or {}).get("cards", [])
    cover = next((c for c in cards if c["frame"] == FRAMES[0]), None)
    return str(((cover or {}).get("fields") or {}).get(COVER_NAME_KEY) or "").strip()


def sync(job: dict) -> bool:
    """확정한 이름을 그 번호의 항목에 넣습니다. 바뀌었으면 True.

    - 항목 수와 순서는 그대로 둡니다. 사진이 없는 항목도 지우지 않습니다.
    - 사진이 있고 이름을 확정한 N번 칸만 N번째 항목의 이름을 그 이름으로 씁니다. 원래 다른 캐릭터였으면
      그 관계·TMI는 버리고, 목록에 같은 이름의 항목이 있었으면 그 관계·TMI를 이어 씁니다.
    - 확정 전인 칸, 사진이 없는 칸의 항목은 건드리지 않습니다.
    - 확정한 이름으로 바뀐 옛 이름(사진과 맞지 않은 캐릭터)은 금지 이름으로 기억합니다.
    """
    changed = False
    for frame in frames(job):
        card = _card(job, frame)
        if not card:
            continue
        rekey(job, frame)
        field = _field(job, frame, card)
        name_key, subs = field["linkedName"], [s["key"] for s in field["fields"]]
        blank = {s: "" for s in subs}
        items = [i for i in card["fields"].get(field["key"]) or [] if isinstance(i, dict)]
        by_name = {i.get(name_key): i for i in items if i.get(name_key)}
        new, replaced = [dict(i) for i in items], []
        for n, slot in enumerate(slots(job, frame, card)):
            record = identity(job, frame, slot["key"])
            if not record or record["status"] != "confirmed":
                continue
            name = record["name"]
            while len(new) < n:
                new.append(dict(blank))  # 앞 번호 항목이 없을 때만 (보통 칸이 보이지 않아 생기지 않음)
            if n < len(new) and new[n].get(name_key) == name:
                continue
            if n < len(new) and new[n].get(name_key):
                replaced.append(new[n][name_key])
            entry = {**blank, **by_name.get(name, {}), name_key: name}
            if n < len(new):
                new[n] = entry
            else:
                new.append(entry)
        remember(job, replaced)
        if new != items:
            card["fields"][field["key"]] = new
            changed = True
    return changed


def keep_people(job: dict, frame: str, before: list[dict]) -> None:
    """확정 뒤 AI가 다시 쓴 카드에서 항목 수·순서·이름을 다시 쓰기 전 목록으로 되돌립니다.

    AI는 관계·TMI만 씁니다. 같은 이름 항목의 관계·TMI를 가져오고, 없으면 빈 문자열로 둡니다
    (사용자가 남겨 둔 사진 없는 친구를 AI가 다른 캐릭터로 바꾸지 못하게).
    """
    card = _card(job, frame)
    if not card or frame not in frames(job):
        return
    field = _field(job, frame, card)
    name_key, blank = field["linkedName"], {s["key"]: "" for s in field["fields"]}
    written = {i.get(name_key): i for i in _items(job, frame, card) if i.get(name_key)}
    card["fields"][field["key"]] = [{**blank, **written.get(i.get(name_key), {}), name_key: i.get(name_key, "")}
                                    for i in before if isinstance(i, dict)]


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
    """이 카드에 쓰면 안 되는 캐릭터 이름 후보: 조사에서 나온 관련 캐릭터, 사진과 달라 뺀 캐릭터, AI가 제안했지만 확정하지 않은 이름."""
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
    """금지 이름을 찾을 문구. 서버가 정하는 이름은 빼고 봅니다."""
    field = _field(job, frame, card)
    texts = []
    for f in templates.template_for(job, frame)["fields"]:
        value = (card.get("fields") or {}).get(f["key"])
        if f["key"] == field["key"]:
            for item in value or []:
                texts += [str(v) for k, v in item.items() if k != field["linkedName"] and v]
        elif f.get("linkedName"):
            continue  # 카드에 보이지 않는 쪽(친구/가족 중 고르지 않은 쪽)
        else:
            texts += templates._strings(value)
    return texts


def _items(job: dict, frame: str, card: dict) -> list[dict]:
    field = _field(job, frame, card)
    return [i for i in (card.get("fields") or {}).get(field["key"]) or [] if isinstance(i, dict)]


def _names(job: dict, frame: str, card: dict) -> list[str]:
    """카드 목록에 있는 캐릭터 이름 (확정한 이름 + 사진 없는 항목의 이름), 순서대로."""
    key = _field(job, frame, card)["linkedName"]
    return [str(i.get(key) or "").strip() for i in _items(job, frame, card)]


def numbered(job: dict, frame: str, card: dict | None = None) -> list[tuple[int, str, str]]:
    """사진으로 확정한 (번호 1부터, 사진 자리, 이름). 번호 N = N번째 항목."""
    keys = [s["key"] for s in slots(job, frame, card)]
    return [(keys.index(key) + 1, key, name) for key, name in confirmed(job, frame, card)]


def violations(job: dict, frame: str, card: dict, cards: list[dict] | None = None) -> list[str]:
    """칸에 사진이 있는 카드에서, 목록의 캐릭터와 중심 캐릭터 말고 다른 캐릭터 이름을 찾습니다."""
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
    return [f"확정하지 않은 캐릭터 이름이 들어 있어요: {', '.join(hits)}. 목록의 캐릭터({names}){f'와 중심 캐릭터({main})' if main else ''}만 써 주세요"]


def add_issues(job: dict, cards: list[dict], issues: dict) -> None:
    for frame in frames(job):
        card = next((c for c in cards if c["frame"] == frame), None)
        if not card or frame not in issues:
            continue
        errors = issues[frame]["errors"]
        labels = {s["key"]: s["label"] for s in slots(job, frame, card)}
        keys = filled(job, frame, card)
        for key in keys:
            record = identity(job, frame, key)
            if record and record["status"] == "confirmed":
                continue
            if record and record["status"] == "processing":
                errors.append(f"{labels[key]}: 사진 속 캐릭터 이름을 확인하고 있어요. 끝나면 이름을 확정해 주세요")
            else:
                errors.append(f"{labels[key]}: 사진 속 캐릭터 이름을 확인하고 확정해 주세요")
        field = _field(job, frame, card)
        written = _names(job, frame, card)
        for n, key, name in numbered(job, frame, card):
            if n > len(written) or written[n - 1] != name:
                errors.append(f"{field['label']} {n}번째 이름이 {labels[key]}에서 확정한 이름({name})과 맞지 않아요. 사진 칸에서 이름을 다시 확정해 주세요")
        repeated = sorted({n for n in written if n and written.count(n) > 1})
        if keys and repeated:
            errors.append(f"{field['label']}에 같은 캐릭터가 두 번 들어 있어요: {', '.join(repeated)}. 사진 없는 항목을 지우거나 다른 캐릭터로 바꿔 주세요")
        errors += violations(job, frame, card, cards)


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
        fixed = {n: (key, name) for n, key, name in numbered(job, frame, card)}
        main = main_name(job)
        category = (field.get("if") or "").partition("=")[2]
        lines.append(f"[사진으로 확정한 {field['label']}: {frame}]")
        if category:
            lines.append(f"- category는 {category}로 둔다.")
        lines.append(f"- {field['key']}는 아래 목록 그대로, 이 순서로 {len(written)}명을 쓴다. {key_name}은 바꾸지 않는다 (N번째 항목 = N번 사진).")
        for n, name in enumerate(written, 1):
            if n in fixed:
                lines.append(f"  - {n}번째: {key_name}={fixed[n][1]} (사진 {fixed[n][0]})")
            else:
                lines.append(f"  - {n}번째: {key_name}={name} (사진 없음 또는 이름 확정 전)")
        lines.append(f"- 이 카드의 관계·TMI 문구에는 목록의 캐릭터{f'와 중심 캐릭터({main})' if main else ''}만 쓴다. 목록에 없는 캐릭터 이름은 쓰지 않는다.")
        lines.append("- 자료에 그 캐릭터의 정보가 없으면 관계·TMI는 빈 문자열로 둔다. 다른 캐릭터 정보로 채우지 않는다.")
    return "\n".join(lines)


def unknown_names(job: dict, names: list[str]) -> list[str]:
    """저장된 조사 자료에 한 번도 나오지 않는 이름. 이 이름들만 짧게 다시 조사합니다."""
    research = job.get("research") or {}
    text = " ".join([f.get("text", "") for f in research.get("facts", [])]
                    + [f"{i.get('value', '')} {i.get('quote', '')}" for i in research.get("items") or []])
    return [n for n in names if n not in text]
