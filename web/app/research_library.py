"""조사 자료 보관함. 같은 콘텐츠 유형·주제의 AI 조사 결과를 버전으로 쌓아 두고 다시 씁니다.

- 저장 위치: data/research/<버전 id>.json (작업 파일과 같은 JSON 방식, 별도 데이터베이스 없음)
- 같은 주제: 콘텐츠 유형 + 정규화한 주제(대소문자·공백·문장부호 무시)가 같으면 같은 주제로 봅니다.
- 새로 조사하면 새 버전을 추가합니다. 예전 버전을 덮어쓰거나 지우지 않습니다.
- 사용자는 버전 이름을 바꾸거나(이름 필드만 저장) 버전 하나를 지울 수 있습니다. 조사 자료(research)는 고치지 않습니다.
  작업은 시작할 때 자료를 복사해 두므로(research_for_job) 버전을 지워도 그 자료로 만든 작업은 그대로입니다.
- 저장하는 것은 자료(출처·사실·조사 항목)뿐입니다. 카드 문구와 디자인은 저장하지 않아 매번 새로 쓸 수 있습니다.
"""

import hashlib
import json
import os
import re
import unicodedata
import uuid
from datetime import date, datetime
from pathlib import Path

from . import research as research_items

DIR = Path(os.environ.get("SEMOGWI_DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / "research"
VERSION_ID_RE = re.compile(r"^[0-9a-f]{32}$")
NAME_MAX = 40  # 사용자가 붙이는 버전 이름 길이
# 가격·일정이 바뀔 수 있는 유형. 저장된 자료를 쓸 때 오래된 정보일 수 있다고 알립니다
TIME_SENSITIVE = {"goods": "굿즈 가격·판매 일정", "popup": "팝업스토어 일정·운영 시간", "collab": "콜라보 기간·메뉴·특전"}
STALE_DAYS = 7
# 보관함에 남기는 조사 기록 (카드 문구·검색 실패 같은 작업 상태는 남기지 않음)
# peopleResearch: 캐릭터별 이름·관계·TMI·근거·출처 / pipeline·researchedAtTime: 조사 방식과 시각 (비교용)
# items 안에는 항목별 조사 결과(빈 이유)·충분성·근거 기록(evidence)·확인한 페이지(attempts)가 함께 저장됩니다
# supplement·basedOn: 저장된 자료를 바탕으로 보완 조사한 버전의 통합 기록 (어느 버전에서, 무엇을 더했는지)
# moreResearch: 조사 결과 화면의 '추가 조사'를 통합한 기록 (회차·요청 내용·더한 항목과 출처)
KEEP = ("sources", "facts", "items", "missing", "queries", "searchPerformed", "partial", "peopleResearch", "pipeline", "researchedAtTime",
        "supplement", "basedOn", "moreResearch", "friendCandidates", "friendResearch")


def topic_key(content_type: str, topic: str) -> str:
    text = unicodedata.normalize("NFKC", topic or "").lower()
    text = re.sub(r"[\s\W_]+", "", text)
    return hashlib.sha1(f"{content_type}|{text}".encode("utf-8")).hexdigest()[:16]


def _path(version_id: str) -> Path:
    return DIR / f"{version_id}.json"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _summary(record: dict) -> dict:
    research = record["research"]
    sources = research.get("sources", [])
    items = research.get("items") or []
    states: dict[str, int] = {}
    for item in items:
        states[item["state"]] = states.get(item["state"], 0) + 1
    people = research_items.people_from(research) if record["contentType"] == "character" else {}
    researched = record.get("researchedAt") or record["createdAt"][:10]
    try:
        age = (date.today() - date.fromisoformat(researched[:10])).days
    except ValueError:
        age = None
    sensitive = TIME_SENSITIVE.get(record["contentType"])
    return {
        "id": record["id"], "number": record.get("number", 1), "topic": record["topic"], "contentType": record["contentType"],
        "basedOn": (research.get("basedOn") or {}).get("number"),  # 보완 조사로 만든 버전이면 바탕 버전 번호
        "name": record.get("name") or "",  # 사용자가 붙인 이름. 비어 있으면 화면에서 조사일·유형으로 기본 이름을 만듭니다
        "createdAt": record["createdAt"], "researchedAt": researched, "ageDays": age, "jobId": record.get("jobId"),
        "sourceCount": len([s for s in sources if s.get("verification") == "fetched"]),
        "officialCount": len([s for s in sources if s.get("verification") == "fetched" and s.get("kind") == "official"]),
        "sources": [{k: s.get(k, "") for k in ("id", "title", "url", "kind", "verification")} for s in sources],
        "itemStates": states, "factCount": len(research.get("facts", [])),
        "hasUserMaterial": any(s.get("verification") == "user_provided" for s in sources),
        "people": {k: [p["name"] for p in v] for k, v in people.items()},
        # 캐릭터별 상세 (시작 화면 '자료 보기'에서 TMI와 출처를 확인)
        "peopleDetails": {k: [{key: p.get(key, "") for key in ("name", "relation", "tmi", "quote", "sourceIds", "state")} for p in v]
                          for k, v in people.items()},
        "timeSensitive": bool(sensitive),
        "staleNote": (f"{researched} 조사 자료예요. {sensitive}은(는) 바뀌었을 수 있으니 '새로 조사하기'로 최신 정보를 확인해 주세요"
                      + (f" ({age}일 지남)" if age and age >= STALE_DAYS else "")) if sensitive else "",
    }


def versions(content_type: str, topic: str) -> list[dict]:
    """같은 유형·주제의 조사 버전 요약 (최근 것부터)."""
    if not DIR.is_dir():
        return []
    key = topic_key(content_type, topic)
    found = []
    for path in DIR.glob("*.json"):
        record = _read(path)
        if record and record.get("topicKey") == key:
            found.append(record)
    found.sort(key=lambda r: (r["createdAt"], r.get("number", 0)), reverse=True)  # 같은 초에 저장돼도 버전 번호 순
    return [_summary(r) for r in found]


def get(version_id: str) -> dict | None:
    """버전 하나 (요약 + 조사 자료 전체)."""
    if not VERSION_ID_RE.match(version_id or ""):
        return None
    record = _read(_path(version_id))
    if not record:
        return None
    return {**_summary(record), "research": record["research"]}


def save(job: dict, research: dict) -> dict:
    """새 조사 버전을 추가합니다. 같은 주제의 예전 버전은 그대로 둡니다."""
    DIR.mkdir(parents=True, exist_ok=True)
    key = topic_key(job["contentType"], job["topic"])
    # 버전을 지운 뒤에도 번호가 겹치지 않게 가장 큰 번호 다음으로 붙입니다
    number = max((v["number"] for v in versions(job["contentType"], job["topic"])), default=0) + 1
    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "id": uuid.uuid4().hex, "number": number, "topicKey": key, "topic": job["topic"], "contentType": job["contentType"],
        "createdAt": now, "researchedAt": research.get("researchedAt") or now[:10], "jobId": job["id"],
        "research": {k: research[k] for k in KEEP if k in research},
    }
    _write(record)
    return _summary(record)


def _write(record: dict) -> None:
    path = _path(record["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def clean_name(name: str) -> str:
    """이름: 앞뒤 공백·줄바꿈·제어 문자를 정리하고 길이를 제한합니다."""
    text = "".join(ch for ch in unicodedata.normalize("NFC", name or "") if unicodedata.category(ch)[0] != "C")
    return re.sub(r"\s+", " ", text).strip()[:NAME_MAX]


def rename(version_id: str, name: str) -> dict | None:
    """버전 이름만 바꿉니다 (빈 이름이면 기본 이름으로 되돌림). 조사 자료와 다른 기록은 그대로 둡니다."""
    if not VERSION_ID_RE.match(version_id or ""):
        return None
    record = _read(_path(version_id))
    if not record:
        return None
    name = clean_name(name)
    if name:
        record["name"] = name
    else:
        record.pop("name", None)
    _write(record)
    return _summary(record)


def delete(version_id: str) -> bool:
    """버전 파일 하나만 지웁니다. 같은 주제의 다른 버전과 작업 파일은 건드리지 않습니다."""
    if not VERSION_ID_RE.match(version_id or ""):
        return False
    path = _path(version_id)
    if not path.is_file():
        return False
    path.unlink()
    return True


def research_for_job(version: dict, notes: str = "", notes_kind: str = "", notes_url: str = "") -> dict:
    """작업에 넣을 조사 자료. 웹 조사를 하지 않았으므로 검색·접속 기록은 비우고, 어느 버전을 썼는지 남깁니다.
    예전에 저장된 자료에도 지금 출처 규칙(나무위키 보조 출처·미러 제외)을 적용합니다. 저장된 파일은 고치지 않습니다."""
    saved = json.loads(json.dumps(version["research"]))
    research = {
        "searchPerformed": False, "queries": saved.get("queries", []), "searchResults": [], "fetched": [],
        "sources": saved.get("sources", []), "facts": saved.get("facts", []), "missing": saved.get("missing", []),
        "fetchFailures": [], "searchFailures": [], "retryAfter": 0, "policyStops": [],
        "researchedAt": version["researchedAt"], "pipeline": saved.get("pipeline", 1),
        "fromLibrary": {"id": version["id"], "number": version["number"], "researchedAt": version["researchedAt"], "staleNote": version["staleNote"]},
    }
    if saved.get("items") is not None:
        research["items"] = saved["items"]
    if saved.get("peopleResearch"):
        research["peopleResearch"] = saved["peopleResearch"]
    if saved.get("moreResearch"):
        research["moreResearch"] = saved["moreResearch"]
    for key in ("friendCandidates", "friendResearch"):  # card-04 친구 후보 (저장된 자료를 쓰면 다시 추천하지 않음)
        if saved.get(key):
            research[key] = saved[key]
    if notes:
        # 시작 화면에 새로 적은 참고 자료는 사용자 제공 자료로 더합니다 (저장된 자료를 고치지 않음)
        research["sources"] = [s for s in research["sources"] if s.get("id") != research_items.USER_NOTES_ID] + [
            research_items.user_notes_source(notes_kind, notes_url, version["contentType"])]
        research["facts"] = [f for f in research["facts"] if research_items.USER_NOTES_ID not in f.get("sourceIds", [])] + [
            {"text": f"사용자 참고 자료: {notes[:4000]}", "sourceIds": [research_items.USER_NOTES_ID], "origin": "user"}]
    return research_items.apply_source_rules(research, version["contentType"])
