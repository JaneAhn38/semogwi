"""저장된 조사 자료 + 보완(추가) 조사 결과 통합.

'저장된 자료 사용'은 저장된 버전을 그대로 다시 쓰지 않고, 그 자료를 AI에게 맥락으로 주어 부족한 부분만 더 조사한 뒤 합칩니다.
통합 규칙 (항목별):
- 기존 값이 있고 추가 조사에서 못 찾음      → 기존 값 유지 (추가 조사에 없다는 이유로 지우지 않음)
- 기존 값이 없고 추가 조사에서 찾음          → 새 값 (added)
- 같은 값                                   → 기존 값 + 새 출처를 근거로 더함 (confirmed)
- 새 값이 기존 값을 포함 (목록이 늘어남)      → 새 값, 기존 값은 previousValue로 기록 (extended)
- 기존 값이 새 값을 포함                     → 기존 값 유지 + 새 출처 (confirmed)
- 서로 다른 값                              → 기존 값을 그대로 두고 새 값을 '다른 값'으로 붙여 사용자 확인 (conflict)
출처는 주소가 같으면 하나로 합치고, id가 겹치면 새 출처의 id를 바꿔 근거가 섞이지 않게 합니다. 사실·출처를 새로 만들지 않습니다.
"""

import json
from datetime import date, datetime

from . import research as research_items

USER_EDIT_ID = "u2"  # 검토 단계에서 사용자가 직접 고친 값의 출처


def _url(url: str) -> str:
    return research_items._url_key(url or "")


def _has_value(item: dict | None) -> bool:
    return bool(item and item.get("value") and item.get("state") not in research_items.EMPTY_STATES)


def _remap_ids(ids, mapping: dict) -> list[str]:
    return list(dict.fromkeys(mapping.get(i, i) for i in ids or []))


def merge_sources(base_sources: list[dict], new_sources: list[dict]) -> tuple[list[dict], dict]:
    """출처 합치기. (합친 목록, 새 출처 id → 합친 목록의 id)"""
    merged = [dict(s) for s in base_sources]
    by_url = {_url(s.get("url", "")): s for s in merged if _url(s.get("url", ""))}
    by_id = {s["id"]: s for s in merged}
    used = set(by_id)
    mapping: dict[str, str] = {}
    for source in new_sources:
        old_id = str(source.get("id", ""))
        key = _url(source.get("url", ""))
        same = by_url.get(key) if key else None
        if same is None and not key and old_id in by_id and by_id[old_id].get("title") == source.get("title"):
            same = by_id[old_id]  # 주소 없는 같은 출처 (사용자 자료 u1, 상세 이미지 img…)
        if same is not None:
            mapping[old_id] = same["id"]
            if source.get("verification") == "fetched" and same.get("verification") != "fetched":
                same["verification"] = "fetched"  # 이번 추가 조사에서 그 페이지를 실제로 읽음
            continue
        new_id = old_id
        if not new_id or new_id in used:
            new_id = next(f"r{n}" for n in range(1, 1000) if f"r{n}" not in used)  # 추가 조사 출처
        used.add(new_id)
        mapping[old_id] = new_id
        copy = {**source, "id": new_id, "addedBy": "supplement"}
        merged.append(copy)
        by_id[new_id] = copy
        if key:
            by_url[key] = copy
    return merged, mapping


def _remap_item(item: dict, mapping: dict) -> dict:
    item = json.loads(json.dumps(item))
    item["sourceIds"] = _remap_ids(item.get("sourceIds"), mapping)
    for alt in item.get("alternatives", []):
        alt["sourceIds"] = _remap_ids(alt.get("sourceIds"), mapping)
        for ev in alt.get("evidence", []):
            ev["sourceId"] = mapping.get(ev.get("sourceId"), ev.get("sourceId"))
    for ev in item.get("evidence", []):
        ev["sourceId"] = mapping.get(ev.get("sourceId"), ev.get("sourceId"))
    for entry in item.get("unclear", []):
        entry["sourceIds"] = _remap_ids(entry.get("sourceIds"), mapping)
    return item


def _restate(item: dict, by_id: dict) -> str:
    """출처가 늘어난 값의 상태를 다시 정합니다 (예: 공식 페이지를 이번에 읽었으면 공식 확인)."""
    main = {"value": item["value"], "sourceIds": [i for i in item["sourceIds"] if i in by_id]}
    if not main["sourceIds"]:
        return item["state"]
    values = [main] + [a for a in item.get("alternatives", []) if a.get("value")]
    return research_items._state(main, values, by_id, item["key"])


def merge_item(base: dict | None, new: dict | None, by_id: dict, spec: dict) -> tuple[dict | None, str]:
    """항목 하나 통합. (통합된 항목, 결과 종류: kept/added/confirmed/extended/conflict/empty)"""
    if base is None and new is None:
        return None, "empty"
    if not _has_value(base) and not _has_value(new):
        # 둘 다 비었으면 더 최근 조사의 '빈 이유'를 씁니다 (추가 조사에서 찾아봤는지가 더 정확)
        return dict(new or base), "empty"
    if not _has_value(new):
        return dict(base), "kept"
    if not _has_value(base):
        return {**new, "supplement": "added"}, "added"
    nb, nn = research_items._norm(base["value"]), research_items._norm(new["value"])
    item = json.loads(json.dumps(base))
    evidence_ids = {e.get("sourceId") for e in item.get("evidence", [])}
    extra_evidence = [e for e in new.get("evidence", []) if e.get("sourceId") not in evidence_ids]
    if nb == nn or (nn in nb):
        # 같은 값이거나 기존 값이 더 넓음: 기존 값을 유지하고 새 출처를 근거로 더합니다
        item["sourceIds"] = list(dict.fromkeys(item.get("sourceIds", []) + new.get("sourceIds", [])))
        item["evidence"] = item.get("evidence", []) + extra_evidence
        item["state"] = _restate(item, by_id)
        item["supplement"] = "confirmed"
        return item, "confirmed"
    if nb in nn and spec.get("many"):
        # 목록이 늘어남: 새 값이 기존 값을 모두 포함하므로 잃는 정보가 없습니다
        item.update(value=new["value"], quote=new.get("quote") or item.get("quote", ""),
                    sourceIds=list(dict.fromkeys(new.get("sourceIds", []) + item.get("sourceIds", []))),
                    evidence=new.get("evidence", []) + item.get("evidence", []), previousValue=base["value"])
        if new.get("coverage"):
            item["coverage"] = new["coverage"]
        item["state"] = _restate(item, by_id)
        item["supplement"] = "extended"
        return item, "extended"
    # 서로 다른 값: 덮어쓰지 않고 기존 값을 그대로 둔 채 새 값을 다른 값으로 붙여 사용자 확인을 받습니다
    alt = {"value": new["value"], "quote": new.get("quote", ""), "sourceIds": new.get("sourceIds", []),
           "evidence": new.get("evidence", []), "origin": "supplement"}
    item["alternatives"] = item.get("alternatives", []) + [alt] + [{**a, "origin": "supplement"} for a in new.get("alternatives", [])]
    item["state"] = "conflict"
    item["savedConflict"] = True
    item["supplement"] = "conflict"
    return item, "conflict"


def _merge_people(base: dict | None, new: dict | None) -> dict | None:
    if not base and not new:
        return None
    if not base:
        return new
    if not new:
        return base
    people = [dict(p) for p in base.get("people", [])]
    names = {p["name"] for p in people}
    for person in new.get("people", []):
        if person["name"] not in names:
            people.append({**person, "supplement": "added"})
            names.add(person["name"])
    found = {p["name"] for p in people if p.get("tmi")}
    return {**base, "people": people,
            "rejected": [r for r in base.get("rejected", []) + new.get("rejected", []) if r["name"] not in found],
            "missing": [m for m in dict.fromkeys(base.get("missing", []) + new.get("missing", [])) if m not in found],
            "queries": base.get("queries", []) + new.get("queries", []), "pages": base.get("pages", []) + new.get("pages", []),
            "rounds": base.get("rounds", 0) + new.get("rounds", 0)}


def merge(base: dict, new: dict, content_type: str, base_info: dict) -> dict:
    """기존 조사(base)와 추가 조사(new)를 합친 새 조사 결과. base와 new는 고치지 않습니다."""
    base = json.loads(json.dumps(base))
    sources, mapping = merge_sources(base.get("sources", []), new.get("sources", []))
    by_id = {s["id"]: s for s in sources}
    base_items = {i["key"]: i for i in base.get("items") or []}
    new_items = {i["key"]: _remap_item(i, mapping) for i in new.get("items") or []}
    items, summary = [], {"added": [], "extended": [], "confirmed": [], "conflicts": [], "kept": []}
    for spec in research_items.SPECS[content_type]:
        item, kind = merge_item(base_items.get(spec["key"]), new_items.get(spec["key"]), by_id, spec)
        if item is None:
            continue
        items.append(item)
        bucket = {"added": "added", "extended": "extended", "confirmed": "confirmed", "conflict": "conflicts", "kept": "kept"}.get(kind)
        if bucket:
            summary[bucket].append(spec["key"])
    new_facts = [{**f, "sourceIds": _remap_ids(f.get("sourceIds"), mapping)} for f in new.get("facts", [])]
    seen, facts = set(), []
    for fact in base.get("facts", []) + new_facts:
        key = research_items._norm(fact.get("text", ""))
        if key and key not in seen:
            seen.add(key)
            facts.append(fact)
    new_people = new.get("peopleResearch")
    if new_people:
        new_people = json.loads(json.dumps(new_people))
        for person in new_people.get("people", []):
            person["sourceIds"] = _remap_ids(person.get("sourceIds"), mapping)
    now = datetime.now().isoformat(timespec="seconds")
    merged = {
        **{k: v for k, v in base.items() if k not in ("fromLibrary",)},
        "pipeline": 2, "researchedAt": date.today().isoformat(), "researchedAtTime": now,
        "searchPerformed": bool(new.get("searchPerformed") or base.get("searchPerformed")),
        "queries": base.get("queries", []) + new.get("queries", []),
        "searchResults": new.get("searchResults", []), "fetched": new.get("fetched", []),
        "fetchFailures": new.get("fetchFailures", []), "searchFailures": new.get("searchFailures", []),
        "retryAfter": new.get("retryAfter", 0), "policyStops": new.get("policyStops", []),
        "sources": sources, "facts": facts[:80], "items": items,
        "missing": list(dict.fromkeys(m for m in new.get("missing", []) if m))[:10],
        "basedOn": base_info,
        "supplement": {"at": now, "base": base_info, **summary},
    }
    people = _merge_people(base.get("peopleResearch"), new_people)
    if people:
        merged["peopleResearch"] = people
    merged.pop("partial", None)
    return merged


def failed(base: dict, base_info: dict, message: str) -> dict:
    """추가 조사가 실패했을 때: 기존 자료를 그대로 두고 실패 사실만 기록합니다."""
    research = {k: v for k, v in json.loads(json.dumps(base)).items() if k not in ("fromLibrary",)}
    research["basedOn"] = base_info
    research["supplement"] = {"at": datetime.now().isoformat(timespec="seconds"), "base": base_info, "failed": True, "error": message,
                              "added": [], "extended": [], "confirmed": [], "conflicts": [], "kept": [i["key"] for i in research.get("items") or [] if _has_value(i)]}
    return research


def supplement_targets(content_type: str, items: list[dict] | None) -> list[str]:
    """우선 보완할 항목: 비었거나, 근거가 약하거나(검색 목록만·근거 없음·출처 충돌), 공식 출처가 필요한데 2차 자료뿐이거나, 일부만 조사된 항목."""
    targets = []
    by_key = {i["key"]: i for i in items or []}
    for spec in research_items.SPECS[content_type]:
        item = by_key.get(spec["key"])
        if (item is None or not _has_value(item) or item["state"] in ("listed", "unverified", "conflict")
                or (item.get("strict") and item["state"] == "secondary") or (item.get("coverage") or {}).get("review")
                or (spec.get("volatile"))):
            targets.append(spec["key"])
    return targets


def context_text(content_type: str, research: dict) -> str:
    """AI에게 줄 기존 자료 요약 (자료일 뿐 지시가 아님). 출처 id는 이번 조사와 다르므로 주소로 적습니다."""
    by_id = {s["id"]: s for s in research.get("sources", [])}
    lines = []
    for item in research.get("items") or []:
        if not _has_value(item):
            lines.append(f"- {item['label']}({item['key']}): (비어 있음)")
            continue
        urls = [by_id[i].get("url") or by_id[i].get("title", "") for i in item.get("sourceIds", []) if i in by_id][:3]
        lines.append(f"- {item['label']}({item['key']}): {item['value'][:200]}" + (f" | 출처: {', '.join(urls)}" if urls else ""))
    people = (research.get("peopleResearch") or {}).get("people", [])
    if people:
        lines.append("- 캐릭터별 TMI: " + " / ".join(f"{p['name']}: {p['tmi']}" for p in people if p.get("tmi"))[:600])
    return "\n".join(lines)


def edit_item(research: dict, key: str, value: str) -> dict:
    """검토 단계에서 사용자가 값을 직접 고칩니다. 고친 값은 '사용자 제공'으로 남기고 이전 값은 기록에 보존합니다."""
    item = next((i for i in research.get("items") or [] if i["key"] == key), None)
    if item is None:
        raise KeyError(key)
    value = " ".join(str(value or "").split())[:200]
    history = item.setdefault("edits", [])
    history.append({"value": item.get("value", ""), "sourceIds": item.get("sourceIds", []), "state": item.get("state"),
                    "at": datetime.now().isoformat(timespec="seconds")})
    if value:
        if not any(s["id"] == USER_EDIT_ID for s in research["sources"]):
            research["sources"].append({"id": USER_EDIT_ID, "title": "검토 중 사용자가 직접 수정한 값", "url": "", "kind": "user",
                                        "verification": "user_provided", "origin": "user", "officialBasis": None})
        item.update(value=value, quote="", sourceIds=[USER_EDIT_ID], evidence=[], state="user", userEdited=True)
    else:
        item.update(value="", quote="", sourceIds=[], evidence=[], state="not_found", userEdited=True)
    item.pop("savedConflict", None)
    if item.get("alternatives"):
        item.setdefault("dismissed", []).extend(item["alternatives"])
        item["alternatives"] = []
    _refresh_facts(research, item)
    return item


def choose_value(research: dict, key: str, index: int) -> dict:
    """충돌한 값 중 하나를 고릅니다 (0 = 기존 값). 고르지 않은 값은 지우지 않고 dismissed에 남깁니다."""
    item = next((i for i in research.get("items") or [] if i["key"] == key), None)
    if item is None:
        raise KeyError(key)
    options = [{k: item.get(k) for k in ("value", "quote", "sourceIds", "evidence")}] + item.get("alternatives", [])
    if not 0 <= index < len(options) or not options[index].get("value"):
        raise ValueError("고를 수 없는 값이에요")
    chosen = options[index]
    item.setdefault("dismissed", []).extend(o for i, o in enumerate(options) if i != index)
    item.update(value=chosen["value"], quote=chosen.get("quote", ""), sourceIds=chosen.get("sourceIds", []),
                evidence=chosen.get("evidence", []), alternatives=[], chosen="saved" if index == 0 else "supplement")
    item.pop("savedConflict", None)
    by_id = {s["id"]: s for s in research.get("sources", [])}
    item["state"] = research_items._state({"value": item["value"], "sourceIds": item["sourceIds"]}, [item], by_id, item["key"]) if item["sourceIds"] else "unverified"
    _refresh_facts(research, item)
    return item


def _refresh_facts(research: dict, item: dict) -> None:
    research["facts"] = [f for f in research.get("facts", []) if f.get("item") != item["key"]] + research_items.facts_from_items([item])


# ---------- 조사 결과 화면의 '추가 조사' (사용자가 적은 내용을 더 조사) ----------
# 추가 조사 결과는 작업의 조사 자료(job.research)에 바로 넣지 않고 초안(job.researchDraft)으로 둡니다.
# 초안은 '지금 자료 + 이번 회차 결과'를 합친 자료이고, 이번 회차에 생긴 것에는 회차 번호(moreRound)를 붙입니다.
# 사용자가 '통합'을 누를 때만 초안이 조사 자료가 됩니다. '버리기'를 누르거나 실패하면 지금 자료는 그대로입니다.
MORE_REQUEST_MAX = 300
_LOG_KEYS = ("fetched", "fetchFailures", "searchFailures")


def merge_more(base: dict, new: dict, content_type: str) -> dict:
    """지금 자료(base) + 사용자 요청 추가 조사(new). base와 new는 고치지 않습니다.

    통합 규칙은 보완 조사(merge)와 같고, 다음만 다릅니다.
    - 보완 조사 기록(supplement·basedOn)·조사일·핵심 정보만 사용 여부(partial)는 지금 자료 그대로 둡니다
      (이번 회차는 요청한 내용만 찾으므로 다른 항목을 다시 확인한 것이 아닙니다).
    - 검색·접속 기록은 지금 기록에 이어 붙입니다.
    - 둘 다 비어 있는 항목은, 이번 회차에서 찾아보지 않았으면 지금의 '빈 이유'를 그대로 둡니다.
    """
    merged = merge(base, new, content_type, {})
    result = json.loads(json.dumps(base))
    for key in ("sources", "facts", "items", "queries", "searchPerformed"):
        result[key] = merged[key]
    if merged.get("peopleResearch"):
        result["peopleResearch"] = merged["peopleResearch"]
    for key in _LOG_KEYS:
        result[key] = base.get(key, []) + new.get(key, [])
    result["searchResults"] = (base.get("searchResults", []) + new.get("searchResults", []))[-80:]
    stops = base.get("policyStops", [])
    result["policyStops"] = stops + [s for s in new.get("policyStops", []) if s not in stops]
    result["retryAfter"] = max(base.get("retryAfter", 0) or 0, new.get("retryAfter", 0) or 0)
    result["missing"] = list(dict.fromkeys(m for m in base.get("missing", []) + new.get("missing", []) if m))[:10]
    base_items = {i["key"]: i for i in base.get("items") or []}
    for index, item in enumerate(result["items"]):
        old = base_items.get(item["key"])
        if old is not None and not _has_value(old) and not _has_value(item) and item.get("state") == "not_searched":
            result["items"][index] = json.loads(json.dumps(old))
    return result


def tag_round(base: dict, merged: dict, round_no: int) -> dict:
    """이번 회차에서 생기거나 바뀐 것에 회차 번호를 붙이고 요약을 돌려줍니다. merged를 고칩니다.

    보완 조사(merge)가 붙인 표시(item.supplement)는 지금 자료의 값으로 되돌려, 예전 보완 조사 표시와 섞이지 않게 합니다.
    결과: {added, extended, confirmed, conflicts, sources, facts, people}
    """
    summary = {"added": [], "extended": [], "confirmed": [], "conflicts": [], "sources": [], "facts": 0, "people": []}
    base_items = {i["key"]: i for i in base.get("items") or []}
    for item in merged.get("items") or []:
        old = base_items.get(item["key"])
        if old is not None and "supplement" in old:
            item["supplement"] = old["supplement"]
        else:
            item.pop("supplement", None)
        old_alts = len((old or {}).get("alternatives", []))
        for alt in item.get("alternatives", [])[old_alts:]:
            alt.update(origin="more", round=round_no)
        if not _has_value(item):
            continue
        if not _has_value(old):
            kind = "added"
        elif item["value"] != old["value"]:
            kind = "extended"
            item["previousValue"] = old["value"]
        elif len(item.get("alternatives", [])) > old_alts and item.get("savedConflict"):
            kind = "conflicts"
        elif set(item.get("sourceIds", [])) - set(old.get("sourceIds", [])):
            kind = "confirmed"
        else:
            continue
        item.update(moreRound=round_no, moreResult=kind)
        summary[kind].append(item["key"])
    base_ids = {s["id"] for s in base.get("sources", [])}
    for source in merged.get("sources", []):
        if source["id"] not in base_ids:
            source.update(addedBy="more", round=round_no)
            summary["sources"].append(source["id"])
    base_facts = {research_items._norm(f.get("text", "")) for f in base.get("facts", [])}
    for fact in merged.get("facts", []):
        if research_items._norm(fact.get("text", "")) not in base_facts:
            fact["round"] = round_no
            summary["facts"] += 1
    base_people = {p["name"]: p for p in (base.get("peopleResearch") or {}).get("people", [])}
    for person in (merged.get("peopleResearch") or {}).get("people", []):
        before = base_people.get(person["name"])
        if before is None or (person.get("tmi") and person.get("tmi") != before.get("tmi")):
            person["round"] = round_no
            summary["people"].append(person["name"])
    return summary


def open_conflicts(research: dict, round_no: int) -> list[str]:
    """이번 회차에서 생긴, 아직 고르지 않은 다른 값."""
    return [i["key"] for i in research.get("items") or [] if i.get("moreRound") == round_no and i.get("savedConflict")]


def choose_more_value(research: dict, key: str, index: int) -> dict:
    """초안에서 기존 값과 추가 조사 값 중 하나를 고릅니다 (0 = 기존 값). 고르지 않은 값은 dismissed에 남깁니다."""
    item = choose_value(research, key, index)
    item["moreChosen"] = "saved" if index == 0 else "more"
    item.pop("chosen", None)  # 보완 조사 검토 표시(chosen)와 섞지 않습니다
    return item
