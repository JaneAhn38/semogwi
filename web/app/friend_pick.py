"""캐릭터 소개 card-04 '친구 고르기' (2026-11-23).

조사가 끝나면 AI가 친구 후보를 최대 4명 추천하고(귀여운 캐릭터 우선, 이유 한 줄 + 출처), 제작은 '친구 고르기'(waiting_friends)에서 멈춥니다.
사용자가 2~4명을 고르면(목록에 없는 캐릭터도 직접 입력 가능, 고른 순서 = 카드 순서) 고른 친구만 공식 출처 우선으로 조사하고,
그 자료를 새 조사 버전으로 저장한 뒤 구성안을 씁니다. 친구 이름과 순서는 서버가 정하고 AI는 관계·TMI만 씁니다.

job["friendPick"] = {
    candidates: [{name, relation, reason, sourceIds}],  # 추천 후보 (reason은 고를 때만 보여 주고 카드 문구에 쓰지 않음)
    chosen: [name, ...] | None,                       # 고른 친구 (순서 = 카드 순서). None이면 아직 고르지 않음
    recommendedAt, chosenAt, error,                   # error: 추천이 실패해 조사 자료의 친구로 대신 보여 줄 때의 안내
}
조사 자료에도 research["friendCandidates"]로 후보를 남겨, '저장된 자료 사용'에서 다시 추천하지 않고 씁니다.
"""

from datetime import datetime

from . import research as research_items
from . import templates
from .friends import COVER_NAME_KEY, same_character

FRAME = "card-04"
TEMPLATE = "character-04"
MIN_PICK, MAX_PICK, NAME_MAX, MAX_CANDIDATES = 2, 4, 8, 4  # 후보는 최대 4명 (조사도 친구를 최대 4명 모음, 2026-11-24)
REASON_MAX = 40
NO_TMI = "출처에서 찾지 못했어요"
WAITING = "waiting_friends"

# 데모(AI 없이)에서 보여 주는 예시 후보
DEMO_CANDIDATES = [
    {"name": "푸린", "relation": "친구", "reason": "동글동글한 몸과 노래로 귀여움 인기가 높아요 (예시)", "sourceIds": []},
    {"name": "이브이", "relation": "친구", "reason": "복슬복슬한 꼬리가 귀여운 인기 캐릭터예요 (예시)", "sourceIds": []},
    {"name": "파이리", "relation": "친구", "reason": "꼬리 불꽃과 동그란 눈이 귀여워요 (예시)", "sourceIds": []},
    {"name": "꼬부기", "relation": "친구", "reason": "등껍질과 웃는 얼굴이 귀여운 캐릭터예요 (예시)", "sourceIds": []},
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clean_name(value) -> str:
    return " ".join(str(value or "").split())


def applies(job: dict) -> bool:
    """친구 고르기를 하는 작업: 고정 템플릿 캐릭터 소개이고 card-04가 친구 카드일 때."""
    if job.get("contentType") != "character" or not templates.is_template_job(job) or not job.get("templateSet"):
        return False
    return TEMPLATE in (job.get("templateSet") or [])


def needed(job: dict) -> bool:
    """구성안을 쓰기 전에 친구를 골라야 하는지. 예전 작업(구성안이 이미 있음)은 지금 친구를 고른 것으로 봅니다."""
    if not applies(job) or job.get("outline"):
        return False
    return not (job.get("friendPick") or {}).get("chosen")


def chosen(job: dict) -> list[str]:
    return list((job.get("friendPick") or {}).get("chosen") or [])


def check_names(names: list) -> list[str]:
    """고른 친구 이름 검사. 문제가 있으면 ValueError (화면에 그대로 보여 줄 문장)."""
    result = []
    for raw in names:
        name = clean_name(raw)
        if not name:
            continue
        if len(name) > NAME_MAX:
            raise ValueError(f"크루 이름은 {NAME_MAX}자 이내로 적어 주세요: {name}")
        if any(same_character(name, n) for n in result):
            raise ValueError(f"같은 캐릭터를 두 번 골랐어요: {name}")
        result.append(name)
    if not MIN_PICK <= len(result) <= MAX_PICK:
        raise ValueError(f"크루원을 {MIN_PICK}~{MAX_PICK}명 골라 주세요 (지금 {len(result)}명)")
    return result


def _main_name(job: dict, research: dict) -> str:
    cover = next((c for c in (job.get("outline") or {}).get("cards", []) if c["frame"] == "card-01"), None)
    name = clean_name(((cover or {}).get("fields") or {}).get(COVER_NAME_KEY))
    if name:
        return name
    return next((clean_name(i["value"]) for i in research.get("items") or [] if i["key"] == "official_name" and i.get("value")), "")


def _text(research: dict) -> str:
    """읽은 자료의 글 (후보 이름이 실제로 나왔는지 확인할 때 씁니다)."""
    parts = [f.get("text", "") for f in research.get("facts") or []]
    parts += [f"{i.get('value', '')} {i.get('quote', '')}" for i in research.get("items") or []]
    for p in (research.get("peopleResearch") or {}).get("people", []):
        parts += [p.get("name", ""), p.get("tmi", ""), p.get("quote", "")]
    return " ".join(parts)


def readable_ids(research: dict) -> set[str]:
    return {s["id"] for s in research.get("sources") or [] if s.get("verification") in ("fetched", "user_provided")}


def clean_candidates(raw: list, job: dict, research: dict) -> list[dict]:
    """AI가 추천한 후보를 검사합니다. 읽은 자료에 이름이 나오고 읽은 페이지가 근거인 후보만 MAX_CANDIDATES(4)명까지 받습니다."""
    text, ids, main = _text(research), readable_ids(research), _main_name(job, research)
    result: list[dict] = []
    for item in raw or []:
        name = clean_name(item.get("name"))
        sources = [str(i) for i in item.get("sourceIds") or [] if str(i) in ids]
        if not name or len(name) > NAME_MAX or name not in text or not sources:
            continue
        if (main and same_character(name, main)) or any(same_character(name, c["name"]) for c in result):
            continue
        result.append({"name": name, "relation": clean_name(item.get("relation"))[:8],
                       "reason": clean_name(item.get("reason"))[:REASON_MAX], "sourceIds": list(dict.fromkeys(sources))})
        if len(result) >= MAX_CANDIDATES:
            break
    return result


def from_research(job: dict, research: dict, found: list[dict] | None = None) -> list[dict]:
    """추천이 실패했거나 모자랄 때 조사 자료의 친구로 후보를 채웁니다 (이유는 '조사 자료에 나온 친구')."""
    result = list(found or [])
    main = _main_name(job, research)
    for person in research_items.people_from(research)["friends"]:
        if len(result) >= MAX_CANDIDATES:
            break
        name = person["name"]
        if len(name) > NAME_MAX or (main and same_character(name, main)) or any(same_character(name, c["name"]) for c in result):
            continue
        result.append({"name": name, "relation": person.get("relation", "")[:8], "reason": "조사 자료에 함께 나온 캐릭터예요",
                       "sourceIds": list(person.get("sourceIds") or [])})
    return result


def offer(job: dict, candidates: list[dict], error: str | None = None) -> None:
    """후보를 작업과 조사 자료에 남깁니다. 이미 고른 친구는 지우지 않습니다."""
    pick = job.setdefault("friendPick", {"candidates": [], "chosen": None})
    pick.update(candidates=candidates, recommendedAt=_now(), error=error)
    if job.get("research") is not None:
        job["research"]["friendCandidates"] = candidates


def saved_candidates(research: dict | None) -> list[dict] | None:
    found = (research or {}).get("friendCandidates")
    return [dict(c) for c in found] if isinstance(found, list) and found else None


def choose(job: dict, names: list[str]) -> None:
    pick = job.setdefault("friendPick", {"candidates": [], "chosen": None})
    pick.update(chosen=names, chosenAt=_now())


def _researched(research: dict) -> dict[str, dict]:
    """캐릭터별 조사에서 확인한 친구 (이름 → 기록)."""
    found = {p["name"]: p for p in research_items.people_from(research)["friends"]}
    for p in (research.get("peopleResearch") or {}).get("people", []):
        if p.get("tmi") or p["name"] not in found:
            found[p["name"]] = {**found.get(p["name"], {}), **p}
    return found


def known_people(research: dict) -> list[dict]:
    """이미 TMI를 찾은 캐릭터 (다시 조사하지 않음)."""
    return [dict(p) for p in (research.get("peopleResearch") or {}).get("people", []) if p.get("tmi")]


def lacking(research: dict, names: list[str]) -> list[str]:
    """TMI를 아직 찾지 못한 친구 (이 친구들만 조사합니다)."""
    known = {p["name"] for p in known_people(research)}
    return [n for n in names if n not in known]


def people_items(job: dict, research: dict, names: list[str], written: list[dict] | None = None) -> list[dict]:
    """고른 친구 순서 그대로의 card-04 친구 목록. 관계·TMI는 조사한 값, 없으면 AI가 같은 이름에 쓴 관계, 그것도 없으면 빈 칸."""
    found = _researched(research)
    candidates = {c["name"]: c for c in (job.get("friendPick") or {}).get("candidates", [])}
    by_name = {clean_name(i.get("name")): i for i in written or [] if isinstance(i, dict)}
    result = []
    for name in names:
        person, ai = found.get(name, {}), by_name.get(name, {})
        relation = person.get("relation") or (candidates.get(name) or {}).get("relation") or ai.get("relation") or ""
        result.append({"name": name, "relation": clean_name(relation)[:8], "tmi": person.get("tmi") or ""})
    return result


def source_ids(research: dict, names: list[str]) -> list[str]:
    found = _researched(research)
    candidates = {c["name"]: c for c in research.get("friendCandidates") or []}
    ids = [i for n in names for i in (found.get(n, {}).get("sourceIds") or (candidates.get(n) or {}).get("sourceIds") or [])]
    known = {s["id"] for s in research.get("sources") or []}
    return [i for i in dict.fromkeys(ids) if i in known]


def apply(job: dict, cards: dict, research: dict) -> None:
    """AI가 쓴 card-04를 고른 친구로 맞춥니다 (이름·순서·인원은 고른 그대로, TMI는 조사로 확인한 것만)."""
    names = chosen(job)
    card = cards.get(FRAME)
    if not names or not card:
        return
    written = (card.get("fields") or {}).get("friends") if card.get("template") == TEMPLATE else []
    card["template"] = TEMPLATE
    card["fields"] = {"friends": people_items(job, research, names, written)}
    card.setdefault("role", "크루와 TMI")
    if not card.get("source"):
        card["source"] = "출처: 조사 자료"
    card["sourceIds"] = list(dict.fromkeys((card.get("sourceIds") or []) + source_ids(research, names)))
    card.pop("convertedFrom", None)


def missing_tmi(job: dict, card: dict) -> list[str]:
    names = chosen(job)
    items = (card.get("fields") or {}).get("friends") or []
    return [i.get("name") for i in items if isinstance(i, dict) and i.get("name") in names and not i.get("tmi")]


def rules_text(job: dict) -> str:
    """AI 프롬프트에 넣는 규칙 (고른 친구가 있을 때)."""
    names = chosen(job)
    if not names:
        return ""
    listing = ", ".join(f"{n}번째 {name}" for n, name in enumerate(names, 1))
    return (f"[사용자가 고른 친구: {FRAME}]\n- {FRAME}는 {TEMPLATE}로 쓰고, friends는 사용자가 고른 {len(names)}명을 이 순서로 쓴다: {listing}. "
            "name은 글자 그대로 쓰고 다른 캐릭터를 더하거나 빼지 않는다.\n"
            "- 자료에 그 친구의 관계·TMI가 없으면 빈 문자열로 둔다. 다른 캐릭터의 정보로 채우지 않는다.\n"
            "- 이 카드 문구에는 고른 친구와 중심 캐릭터 말고 다른 캐릭터 이름을 쓰지 않는다.")
