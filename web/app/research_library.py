"""조사 자료 보관함. 같은 콘텐츠 유형·주제의 AI 조사 결과를 버전으로 쌓아 두고 다시 씁니다.

- 저장 위치: data/research/<버전 id>.json (작업 파일과 같은 JSON 방식, 별도 데이터베이스 없음)
- 같은 주제: 콘텐츠 유형 + 정규화한 주제(대소문자·공백·문장부호 무시)가 같으면 같은 주제로 봅니다.
- 새로 조사하면 새 버전을 추가합니다. 예전 버전을 덮어쓰거나 지우지 않습니다.
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
# 가격·일정이 바뀔 수 있는 유형. 저장된 자료를 쓸 때 오래된 정보일 수 있다고 알립니다
TIME_SENSITIVE = {"goods": "굿즈 가격·판매 일정", "popup": "팝업스토어 일정·운영 시간", "collab": "콜라보 기간·메뉴·특전"}
STALE_DAYS = 7
# 보관함에 남기는 조사 기록 (카드 문구·검색 실패 같은 작업 상태는 남기지 않음)
# peopleResearch: 캐릭터별 이름·관계·TMI·근거·출처 / pipeline·researchedAtTime: 조사 방식과 시각 (비교용)
# items 안에는 항목별 조사 결과(빈 이유)·충분성·근거 기록(evidence)·확인한 페이지(attempts)가 함께 저장됩니다
KEEP = ("sources", "facts", "items", "missing", "queries", "searchPerformed", "partial", "peopleResearch", "pipeline", "researchedAtTime")


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
    number = len(versions(job["contentType"], job["topic"])) + 1
    now = datetime.now().isoformat(timespec="seconds")
    record = {
        "id": uuid.uuid4().hex, "number": number, "topicKey": key, "topic": job["topic"], "contentType": job["contentType"],
        "createdAt": now, "researchedAt": research.get("researchedAt") or now[:10], "jobId": job["id"],
        "research": {k: research[k] for k in KEEP if k in research},
    }
    path = _path(record["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return _summary(record)


def research_for_job(version: dict, notes: str = "") -> dict:
    """작업에 넣을 조사 자료. 웹 조사를 하지 않았으므로 검색·접속 기록은 비우고, 어느 버전을 썼는지 남깁니다."""
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
    if notes:
        # 시작 화면에 새로 적은 참고 자료는 사용자 제공 자료로 더합니다 (저장된 자료를 고치지 않음)
        research["sources"] = [s for s in research["sources"] if s.get("id") != research_items.USER_NOTES_ID] + [
            {"id": research_items.USER_NOTES_ID, "title": "사용자가 입력한 참고 자료", "url": "", "kind": "user",
             "verification": "user_provided", "origin": "user", "officialBasis": None}]
        research["facts"] = [f for f in research["facts"] if research_items.USER_NOTES_ID not in f.get("sourceIds", [])] + [
            {"text": f"사용자 참고 자료: {notes[:4000]}", "sourceIds": [research_items.USER_NOTES_ID], "origin": "user"}]
    return research
