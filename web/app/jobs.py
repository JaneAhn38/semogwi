"""제작 작업의 상태 관리. 작업마다 data/jobs/<id>/job.json에 저장하므로 새로 고침해도 이어서 볼 수 있습니다.

파일을 읽고 쓰는 함수는 모두 이벤트 루프에서만 호출합니다 (읽기-수정-저장이 끊기지 않도록).
"""

import asyncio
import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import claude_cli, cutout, detail_images, friends, research as research_items, research_library, research_merge, site_policy, templates
from .ai_provider import card_source_state, get_ai_provider, material_text, policy_stop_research, separates_research
from .claude_cli import AIError
from .layout import ImageElement, LayoutError, TextElement, validate_layout
from .outline import check_card, issues_of, unsupported_numbers
from .provider import DEFAULT_THEME, FRAMES, IMAGE_LAYOUTS, LAYOUT_LABELS, TEXT_LAYOUTS, THEMES, get_provider

DATA_DIR = Path(os.environ.get("SEMOGWI_DATA_DIR", Path(__file__).resolve().parent.parent / "data")) / "jobs"
DEMO_STEP_SECONDS = float(os.environ.get("SEMOGWI_DEMO_DELAY", "0.9"))
JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
PERMITTED = "허가됨"
NOT_PERMITTED = "허가 안 됨"
UNCHECKED = "확인 필요"  # 업로드 기본값. 사용 허가를 확인했다는 뜻이 아니므로 '허가됨'으로 바꿔 기록하지 않습니다


def usable_asset(asset: dict) -> bool:
    """카드에 쓸 수 있는 이미지인지. 학술 연구·내부 시연용이라 권한을 따로 고르지 않아도 씁니다.

    예전에 '허가 안 됨'으로 직접 표시한 이미지만 쓰지 않습니다. 사용 권한 기록 자체(rights)는 그대로 둡니다.
    """
    return not asset.get("removed") and asset.get("rights") != NOT_PERMITTED
MAX_DESIGN_REQUESTS = 20
TEMPLATE_ONLY = "고정 템플릿 카드뉴스는 디자인이 정해져 있어요. 문구는 구성안에서, 이미지는 카드별 이미지 선택에서 바꿔 주세요"

# mode: real = 실제 동작, demo = 시뮬레이션
STEPS = [
    ("input", "입력 저장", "real"),
    ("research", "자료 조사", "demo"),
    ("outline", "구성안 작성", "demo"),
    ("copy", "문구 작성", "demo"),
    ("layout", "카드 레이아웃", "demo"),
    ("export", "PNG 준비", "demo"),
]

_tasks: dict[str, asyncio.Task] = {}
_cutout_tasks: dict[str, asyncio.Task] = {}
_ai_tasks: dict[str, asyncio.Task] = {}
_identify_tasks: dict[str, asyncio.Task] = {}


class JobConflict(Exception):
    """지금 상태에서 할 수 없는 요청."""


def _path(job_id: str) -> Path:
    return DATA_DIR / job_id / "job.json"


def job_dir(job_id: str) -> Path:
    return DATA_DIR / job_id


def uploads_dir(job_id: str) -> Path:
    return job_dir(job_id) / "uploads"


def save(job: dict) -> None:
    if templates.is_template_job(job):
        job["slotSuggestions"] = slot_suggestions(job)  # 제안만 합니다. 적용 버튼을 눌러야 slotImages에 들어갑니다
    path = _path(job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read(job_id: str) -> dict:
    return _normalize(json.loads(_path(job_id).read_text(encoding="utf-8")))


def _default_theme(style: str) -> dict:
    # source가 "ai"가 되면 결과 화면에서 AI가 고른 테마와 이유를 보여 줄 수 있습니다
    return {"source": "default", "themeId": style, "label": THEMES[style]["label"], "rationale": None}


def _normalize(job: dict) -> dict:
    """이전 형식의 작업도 그대로 열리도록 빠진 필드를 채웁니다."""
    job.setdefault("designTheme", _default_theme(job["style"]))
    job.setdefault("designRequests", {})
    job.setdefault("mode", "demo")
    job.setdefault("research", None)
    job.setdefault("aiTask", None)
    job.setdefault("aiError", None)
    job.setdefault("aiCalls", [])
    job.setdefault("aiUsage", None)
    job.setdefault("userMaterial", None)
    job.setdefault("format", 1)
    job.setdefault("slotImages", None)
    job.setdefault("slotIdentities", {})  # 친구 칸 사진의 캐릭터 이름 확인 기록 (app/friends.py)
    job.setdefault("templateSet", None)  # 없으면 예전 형식 3(표지 + 본문 반복) 또는 기존 방식
    job.setdefault("typeSource", "user")
    job.setdefault("notes", "")
    job.setdefault("notesKind", "")  # 참고 자료의 출처 종류 ("" / official / namuwiki / other). 공식을 골라도 공식 확인으로 만들지 않습니다
    job.setdefault("notesUrl", "")  # 참고 자료를 옮겨 온 주소 (사용자 제공, 자동으로 읽지 않음)
    job.setdefault("typeReason", "")
    job.setdefault("detailImages", [])  # 자료 조사용 상세페이지 이미지 (카드에 넣는 이미지와 따로 둡니다)
    job.setdefault("detailExtraction", None)  # AI가 상세 이미지에서 읽은 결과
    job.setdefault("detailFetch", None)  # 참고 URL에서 상세 이미지를 찾은 기록
    job.setdefault("researchVersion", None)  # 조사 자료 보관함의 버전 (새로 조사해 저장했거나, 저장된 자료로 시작한 경우)
    job.setdefault("researchStage", None)  # 조사 단계가 끝났는지 (조사와 구성안 작성을 나눈 작업). 구성안만 다시 쓸 때 씁니다
    job.setdefault("researchBase", None)  # '저장된 자료 사용': 보완 조사의 바탕이 된 저장 버전 {id, number, researchedAt, name}
    job.setdefault("researchDraft", None)  # 조사 결과 화면의 '추가 조사' 결과 (통합 전 초안, 통합하기 전에는 research를 바꾸지 않음)
    for asset in job["assets"]:
        asset.setdefault("sha256", None)
        asset.setdefault("useVariant", "original")
        asset.setdefault("cutout", None)
        asset.setdefault("removed", False)
    # 저장된 순서와 상관없이 항상 card-01 ~ card-05 순서로 엽니다 (화면, PNG, ZIP 순서를 맞춤)
    order = {f: i for i, f in enumerate(FRAMES)}
    for part in ("outline", "preview"):
        if job.get(part) and job[part].get("cards"):
            job[part]["cards"].sort(key=lambda c: order.get(c.get("frame"), len(FRAMES)))
    if job.get("outline"):
        for card in job["outline"]["cards"]:
            card.setdefault("edited", False)
            card.setdefault("regenCount", 0)
            card.setdefault("sourceIds", [])
        _open_old_versions(job)
        job["outline"].setdefault("issues", _base_issues(job, job["outline"]["cards"]))
    preview = job.get("preview")
    if preview:
        preview.setdefault("approvalHash", None)
        for card in preview["cards"]:
            card.setdefault("previous", None)
    for slots in (job.get("slotImages") or {}).values():
        for key, image in slots.items():
            if image:
                slots[key] = _slot_image(image["assetId"], image["variant"], image)
    if "cardImages" not in job:
        job["cardImages"] = _images_from_preview(preview) if preview and not templates.is_template_job(job) else None
    return job


def _open_old_versions(job: dict) -> None:
    """디자인이 바뀐 템플릿으로 저장한 카드를 예전 판으로 엽니다 (예: 공통 TMI가 있던 친구와 TMI 카드).

    예전 값을 새 형식으로 옮기면 공통 TMI를 특정 친구의 사실처럼 붙이게 되므로, 내용은 그대로 두고 예전 디자인으로 그립니다.
    """
    if not templates.is_template_job(job) or not job.get("templateSet"):
        return
    preview = job.get("preview")
    old_hash = _approval_hash(job) if preview and preview.get("cards") else None
    changed = False
    for index, card in enumerate(job["outline"]["cards"]):
        old_id = templates.upgrade_card(card)
        if not old_id:
            continue
        card["template"] = old_id
        if index < len(job["templateSet"]):
            job["templateSet"][index] = old_id
        changed = True
        for shown in (preview or {}).get("cards", []):
            if shown.get("frame") == card["frame"] and shown.get("spec", {}).get("template") != old_id:
                shown["spec"]["template"] = old_id
                shown["layoutName"] = old_id
                shown["layoutLabel"] = f"{templates.TEMPLATES[old_id]['label']} 템플릿"
    # 그림 내용은 그대로이므로 승인 기록도 유지합니다
    if changed and old_hash and preview.get("approvalHash") == old_hash:
        preview["approvalHash"] = _approval_hash(job)


def _base_issues(job: dict, cards: list[dict]) -> dict:
    """형식별 글자 수·필드 규칙과 친구 칸 확인. 출처 검증은 _issues가 더합니다."""
    if not templates.is_template_job(job):
        return issues_of(cards)
    _sync_templates(job, cards)  # 카드별 템플릿을 먼저 맞춘 뒤 친구 칸을 확인합니다
    issues = templates.issues_of(job, cards)
    friends.add_issues(job, cards, issues)
    return issues


def _sync_templates(job: dict, cards: list[dict]) -> None:
    """구성안 카드마다 고른 템플릿을 작업의 templateSet에 반영하고, 이미지 자리를 새 템플릿에 맞춥니다.

    card-02 ~ card-05는 자료에 따라 템플릿이 바뀔 수 있습니다. 넣어 둔 이미지는 같은 자리 이름이 있으면 그대로,
    없으면 새 템플릿의 빈 자리에 차례로 옮깁니다 (이미지를 잃지 않게).
    """
    if not templates.is_flexible(job) or len(cards) != len(FRAMES):
        return
    ids = [card.get("template") or job["templateSet"][i] for i, card in enumerate(cards)]
    if ids == job["templateSet"]:
        return
    job["templateSet"] = ids
    slots_all = job.get("slotImages")
    if slots_all is None:
        return
    for frame in FRAMES:
        keys = [slot["key"] for slot in templates.slots_of(job, frame)]
        old = slots_all.get(frame) or {}
        new = {key: old.get(key) for key in keys}
        leftovers = [image for key, image in old.items() if image and key not in keys]
        for key in keys:
            if new[key] is None and leftovers:
                new[key] = leftovers.pop(0)
        slots_all[frame] = new


def _images_from_preview(preview: dict) -> dict:
    images = {}
    for card in preview["cards"]:
        element = next((e for e in card["spec"]["elements"] if e["type"] == "image" and e.get("assetId")), None)
        images[card["frame"]] = {"assetId": element["assetId"], "variant": element.get("variant", "original")} if element else None
    return images


def load(job_id: str) -> dict | None:
    if not JOB_ID_RE.match(job_id) or not _path(job_id).is_file():
        return None
    job = _read(job_id)
    changed = False
    # 서버가 다시 켜져 진행 중이던 작업이 사라진 경우를 그대로 알립니다
    if job["state"] == "running" and job_id not in _tasks:
        job["state"] = "interrupted"
        job["error"] = "서버가 다시 시작되어 작업이 중단됐어요. 새로 만들어 주세요."
        changed = True
    if job["aiTask"] and job_id not in _ai_tasks:
        job["aiTask"] = None
        job["aiError"] = "서버가 다시 시작되어 AI 작업이 중단됐어요. 다시 시도해 주세요."
        changed = True
    for asset in job["assets"]:
        info = asset["cutout"]
        if info and info["status"] == "processing" and _cutout_key(job_id, asset["id"]) not in _cutout_tasks:
            info.update(status="failed", error="서버가 다시 시작되어 처리가 중단됐어요. 다시 시도해 주세요.")
            changed = True
    for frame, records in (job.get("slotIdentities") or {}).items():
        for slot, record in records.items():
            if record["status"] == "processing" and _identity_key(job_id, frame, slot) not in _identify_tasks:
                record.update(status="failed", error="서버가 다시 시작되어 이름 확인이 중단됐어요. 이름을 직접 입력해 주세요.")
                changed = True
    if changed:
        save(job)
    if job["state"] == "waiting_material" and "researchGap" not in job:
        _refresh_gap(job)  # 예전에 자료 부족으로 멈춘 작업도 부족한 정보를 보여 줍니다 (읽을 때 계산만, 파일은 그대로)
    return job


def new_job_id() -> str:
    job_id = uuid.uuid4().hex
    uploads_dir(job_id).mkdir(parents=True)
    return job_id


def new_asset(job_id: str, name: str, data: bytes, ext: str, mime: str, rights: str, source: str) -> dict:
    asset_id = uuid.uuid4().hex
    (uploads_dir(job_id) / f"{asset_id}{ext}").write_bytes(data)  # 파일 이름은 서버가 정합니다
    return {"id": asset_id, "name": name, "ext": ext, "mime": mime, "rights": rights, "source": source,
            "sha256": hashlib.sha256(data).hexdigest(), "useVariant": "original", "cutout": None, "removed": False}


def create_draft(job_id: str) -> dict:
    job = {
        "id": job_id,
        "demo": get_provider().is_demo,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "state": "draft",
        "error": None,
        "topic": "",
        "contentType": "character",
        "style": DEFAULT_THEME,
        "designTheme": _default_theme(DEFAULT_THEME),
        "url": "",
        "assets": [],
        "cardImages": None,
        "designRequests": {},
        "mode": "demo",
        "research": None,
        "aiTask": None,
        "aiError": None,
        "aiCalls": [],
        "aiUsage": None,
        "userMaterial": None,
        "format": 1,
        "slotImages": None,
        "templateSet": None,
        "typeSource": "user",
        "typeReason": "",
        "notes": "",
        "notesKind": "",
        "notesUrl": "",
        "detailImages": [],
        "detailExtraction": None,
        "detailFetch": None,
        "steps": [{"key": k, "label": label, "mode": mode, "status": "pending"} for k, label, mode in STEPS],
        "outline": None,
        "preview": None,
    }
    save(job)
    return job


def create(job_id: str, topic: str, content_type: str, style: str, url: str, assets: list[dict]) -> dict:
    job = create_draft(job_id)
    job.update(topic=topic, contentType=content_type, style=style, url=url, assets=assets, designTheme=_default_theme(style))
    save(job)
    return start(job_id)


def update_input(job_id: str, topic: str, content_type: str, url: str, notes: str | None = None,
                 notes_kind: str | None = None, notes_url: str | None = None) -> dict:
    """입력값은 어느 단계에서든 고칠 수 있습니다. 이미 만든 구성안의 문구는 자동으로 바꾸지 않습니다."""
    job = _require_job(job_id)
    if templates.is_template_job(job) and content_type != job["contentType"]:
        raise JobConflict("이미 만든 카드뉴스의 유형은 바꿀 수 없어요. 새 카드뉴스로 만들어 주세요")
    job.update(topic=topic, contentType=content_type, url=url)
    if notes is not None:
        job["notes"] = notes
    if notes_kind is not None:
        job["notesKind"] = notes_kind
    if notes_url is not None:
        job["notesUrl"] = notes_url
    save(job)
    return job


def _is_ai(job: dict) -> bool:
    return job.get("mode") == "ai"


AUTO_TYPE = "auto"
# AI를 부르지 않을 때(데모, 자동 접근 금지 사이트) 쓰는 키워드 추정. 사용자가 구성안 단계에서 바꿀 수 있습니다.
_TYPE_KEYWORDS = [
    ("popup", ("팝업", "popup", "pop-up", "전시")),
    ("collab", ("콜라보", "collab", "협업", "×", " x ")),
    ("goods", ("굿즈", "goods", "키링", "인형", "피규어", "스티커", "발매", "라인업", "상품", "판매")),
]


def guess_type(topic: str) -> str:
    text = f" {topic.lower()} "
    return next((type_id for type_id, words in _TYPE_KEYWORDS if any(w in text for w in words)), "character")


def _apply_type(job: dict, content_type: str, source: str, reason: str = "") -> None:
    """유형을 정하고, 그 유형의 고정 템플릿 5장을 고릅니다."""
    job.update(contentType=content_type, typeSource=source, typeReason=reason)
    job["format"] = templates.FORMAT if templates.enabled(content_type) else 1
    job["templateSet"] = templates.template_set(content_type) if job["format"] == templates.FORMAT else None


def start(job_id: str, mode: str = "demo", research_mode: str = "new", version_id: str | None = None) -> dict:
    """제작을 시작합니다. research_mode가 saved면 보관함의 조사 버전으로 구성안만 새로 씁니다 (웹 조사 안 함)."""
    job = _require(job_id, "draft")
    if not job["topic"]:
        raise JobConflict("주제를 입력해 주세요")
    if any(_is_processing(a) for a in job["assets"]):
        raise JobConflict("배경 제거가 끝난 뒤에 시작해 주세요")
    if research_mode == "saved":
        return _start_from_library(job, mode, version_id)
    if mode == "ai":
        state = claude_cli.status()
        if not state["available"]:
            raise JobConflict(state["reason"])
        job.update(mode="ai", demo=False)
        for step in job["steps"]:
            step["mode"] = "real"
    site = site_policy.restricted_site(job["url"]) if mode == "ai" else None
    if job["contentType"] != AUTO_TYPE:
        _apply_type(job, job["contentType"], "user")
    elif mode != "ai" or site:
        # AI를 부르지 않는 경우: 키워드로 추정합니다
        _apply_type(job, guess_type(job["topic"]), "keyword")
    else:
        job["typeSource"] = "pending"  # 조사 전에 AI가 고릅니다
    _set_step(job, "input", "done")
    if site:
        # 자동으로 접근하지 않고 AI도 호출하지 않습니다. 사용자가 자료를 주면 이어서 진행합니다.
        job["research"] = policy_stop_research(site)
        _set_step(job, "research", "skipped")
        job["state"] = "waiting_material"
        save(job)
        return job
    job["state"] = "running"
    save(job)
    _start(job_id, _ai_build_outline(job_id) if mode == "ai" else _build_outline(job_id))
    return job


def _start_from_library(job: dict, mode: str, version_id: str | None) -> dict:
    """저장된 조사 자료로 시작합니다. 그 자료를 바탕으로 부족한 내용을 추가 조사해 합친 뒤(보완 조사),
    사용자가 통합 자료를 검토·수정하고 승인하면 구성안을 씁니다. 저장된 버전은 고치지 않습니다."""
    if mode != "ai":
        raise JobConflict("저장된 자료 사용은 실제 AI 모드에서만 쓸 수 있어요")
    version = research_library.get(version_id or "")
    if version is None:
        raise JobConflict("저장된 조사 자료를 찾지 못했어요. '새로 조사하기'로 시작해 주세요")
    content_type = job["contentType"] if job["contentType"] != AUTO_TYPE else version["contentType"]
    if version["topic"] and research_library.topic_key(content_type, job["topic"]) != research_library.topic_key(version["contentType"], version["topic"]):
        raise JobConflict("이 주제·유형의 저장된 자료가 아니에요. 자료를 다시 골라 주세요")
    state = claude_cli.status()
    if not state["available"]:
        raise JobConflict(state["reason"])
    job.update(mode="ai", demo=False)
    for step in job["steps"]:
        step["mode"] = "real"
    _apply_type(job, content_type, "user")
    job["research"] = research_library.research_for_job(version, str(job.get("notes") or "").strip(), job.get("notesKind", ""), job.get("notesUrl", ""))
    job["researchBase"] = {"id": version["id"], "number": version["number"], "researchedAt": version["researchedAt"], "name": version.get("name", "")}
    job["researchVersion"] = {"id": version["id"], "number": version["number"], "researchedAt": version["researchedAt"], "source": "saved"}
    job["researchStage"] = None
    _set_step(job, "input", "done")
    job["state"] = "running"
    save(job)
    _start(job["id"], _ai_supplement(job["id"]))
    return job


async def _ai_supplement(job_id: str) -> None:
    """보완 조사: 저장된 자료를 AI에게 주고 부족한 내용을 더 조사해 합칩니다. 끝나면 사용자가 검토하는 단계(waiting_research)로 갑니다.

    추가 조사가 실패해도 작업을 실패로 끝내지 않습니다. 기존 자료를 그대로 두고 검토 단계로 가서, 그대로 진행하거나 다시 시도할 수 있습니다.
    """
    job = _read(job_id)
    _set_step(job, "research", "active")
    save(job)
    base = job["research"]
    info = job.get("researchBase") or {}
    try:
        result = await asyncio.to_thread(get_ai_provider().supplement_research, job, base, info, uploads_dir(job_id))
    except AIError as e:
        result = {"research": research_merge.failed(base, info, e.message), "calls": [], "extraction": None}
    except Exception as e:  # 통합 중 예기치 못한 오류도 기존 자료를 잃지 않게 합니다
        result = {"research": research_merge.failed(base, info, f"추가 조사 결과를 합치지 못했어요 ({type(e).__name__})"), "calls": [], "extraction": None}
    job = _read(job_id)
    _record_calls(job, result["calls"])
    site_policy.record_failures(result["research"].get("fetchFailures", []))
    job["research"] = result["research"]
    if result.get("extraction") is not None:
        job["detailExtraction"] = result["extraction"]
    if job["contentType"] == "character" and job["research"].get("items"):
        job["research"]["people"] = research_items.people_from(job["research"])
    job["researchStage"] = None  # 사용자가 검토하고 승인하면 조사 단계가 끝납니다
    job["error"] = None
    _set_step(job, "research", "done")
    job["state"] = "waiting_research"
    save(job)


def _require_review(job_id: str) -> dict:
    job = _require(job_id, "waiting_research")
    if not (job.get("research") or {}).get("supplement"):
        raise JobConflict("검토할 추가 조사 결과가 없어요")
    if job.get("researchDraft"):
        raise JobConflict(DRAFT_PENDING)
    return job


def edit_research_item(job_id: str, key: str, value: str) -> dict:
    """검토 단계: 조사 항목 값을 직접 고칩니다 (사용자 제공 값으로 기록, 이전 값은 보존)."""
    job = _require_review(job_id)
    try:
        research_merge.edit_item(job["research"], key, value)
    except KeyError:
        raise JobConflict("조사 항목을 찾을 수 없어요") from None
    job["research"]["supplement"]["edited"] = sorted(set(job["research"]["supplement"].get("edited", [])) | {key})
    _refresh_people(job)
    save(job)
    return job


def choose_research_value(job_id: str, key: str, index: int) -> dict:
    """검토 단계: 기존 값과 추가 조사 값이 다를 때 하나를 고릅니다 (고르지 않은 값은 기록에 남김)."""
    job = _require_review(job_id)
    try:
        research_merge.choose_value(job["research"], key, index)
    except KeyError:
        raise JobConflict("조사 항목을 찾을 수 없어요") from None
    except ValueError as e:
        raise JobConflict(str(e)) from None
    _refresh_people(job)
    save(job)
    return job


def _refresh_people(job: dict) -> None:
    if job["contentType"] == "character" and job["research"].get("items"):
        job["research"]["people"] = research_items.people_from(job["research"])


def retry_supplement(job_id: str) -> dict:
    """검토 단계에서 추가 조사를 다시 합니다 (지금 자료를 바탕으로)."""
    job = _require(job_id, "waiting_research")
    if job.get("researchDraft"):
        raise JobConflict(DRAFT_PENDING)
    state = claude_cli.status()
    if not state["available"]:
        raise JobConflict(state["reason"])
    job.update(state="running", error=None)
    save(job)
    _start(job_id, _ai_supplement(job_id))
    return job


def approve_research(job_id: str) -> dict:
    """검토한 통합 자료를 새 조사 버전으로 저장하고(바탕 버전은 그대로), 그 자료로 구성안을 씁니다."""
    job = _require_review(job_id)
    research = job["research"]
    supplement = research["supplement"]
    if not supplement.get("failed") or supplement.get("edited") or supplement.get("moreRounds"):
        # 추가 조사가 됐거나 사용자가 고쳤거나 '추가 조사' 결과를 통합한 경우에만 새 버전을 만듭니다 (실패 후 그대로 진행하면 바탕 버전과 같음)
        try:
            summary = research_library.save(job, research)
            job["researchVersion"] = {"id": summary["id"], "number": summary["number"], "researchedAt": summary["researchedAt"],
                                      "source": "supplement", "basedOn": job.get("researchBase")}
        except OSError:
            pass  # 보관함에 쓰지 못해도 제작은 계속합니다
    core = research_items.core_status(job["contentType"], research.get("items"))
    job["researchStage"] = {"done": True, "coreOnly": False, "reviewed": True, "at": datetime.now().isoformat(timespec="seconds"),
                            "coreReady": core["ready"]}
    _set_step(job, "outline", "active")
    job.update(state="running", error=None)
    save(job)
    _start(job_id, _ai_research_then_compose(job_id, job, get_ai_provider(), compose_only=True))
    return job


# ---------- 조사 결과 화면의 '추가 조사' ----------
# 사용자가 적은 내용을 지금 자료를 참고해 더 조사합니다. 결과는 초안(researchDraft)으로만 두고,
# 사용자가 '통합'을 누를 때만 조사 자료(research)가 바뀝니다. 구성안은 그대로 두고 경고만 다시 계산합니다.
MORE_STATES = ("waiting_research", "waiting_outline", "waiting_material")  # 자료가 부족해 멈춘 작업도 부족한 항목만 더 조사할 수 있습니다
DRAFT_PENDING = "확인하지 않은 추가 조사 결과가 있어요. 먼저 '통합' 또는 '버리기'를 골라 주세요"


def _research_hash(research: dict | None) -> str:
    return hashlib.sha256(json.dumps(research, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _require_more(job_id: str) -> dict:
    job = _require(job_id, *MORE_STATES)  # AI 작업 중이면 여기서 막혀 같은 요청이 두 번 실행되지 않습니다
    if not _is_ai(job):
        raise JobConflict("추가 조사는 실제 AI 모드에서만 쓸 수 있어요")
    if job.get("outline") and job["outline"].get("approved"):
        raise JobConflict("구성안을 승인한 뒤에는 추가 조사를 할 수 없어요")
    if not job.get("research") or not separates_research(job):
        raise JobConflict("추가 조사할 조사 자료가 없어요")
    return job


def _require_draft(job_id: str) -> tuple[dict, dict]:
    job = _require_more(job_id)
    draft = job.get("researchDraft")
    if not draft:
        raise JobConflict("확인할 추가 조사 결과가 없어요")
    return job, draft


def _next_more_round(job: dict) -> int:
    used = [r.get("round", 0) for r in (job.get("research") or {}).get("moreResearch") or []] + [r.get("round", 0) for r in job.get("moreResearchLog") or []]
    return max(used, default=0) + 1


def request_more_research(job_id: str, request: str) -> dict:
    """추가 조사를 시작합니다. 화면과 작업 상태는 그대로 두고 AI 작업으로 실행합니다 (실패해도 지금 자료와 구성안은 그대로)."""
    job = _require_more(job_id)
    request = " ".join(str(request or "").split())[:research_merge.MORE_REQUEST_MAX]
    if len(request) < 2:
        raise JobConflict("추가로 조사할 내용을 적어 주세요")
    if job.get("researchDraft"):
        raise JobConflict(DRAFT_PENDING)
    state = claude_cli.status()
    if not state["available"]:
        raise JobConflict(state["reason"])
    round_no = _next_more_round(job)
    base_hash = _research_hash(job["research"])
    content_type = job["contentType"]

    def work(snapshot):
        return get_ai_provider().more_research(snapshot, snapshot["research"], request, round_no)

    def apply(current, result):
        # 조사하는 동안 자료나 단계가 바뀌었으면 결과를 쓰지 않습니다 (지금 자료를 덮지 않게)
        approved = current.get("outline") and current["outline"].get("approved")
        if (current["state"] not in MORE_STATES or approved or current["contentType"] != content_type
                or _research_hash(current.get("research")) != base_hash):
            current["aiError"] = "추가 조사 중에 조사 자료나 단계가 바뀌어 결과를 쓰지 않았어요. 지금 자료는 그대로예요"
            return
        research = result["research"]
        if content_type == "character" and research.get("items"):
            research["people"] = research_items.people_from(research)
        current["researchDraft"] = {"round": round_no, "request": request, "at": datetime.now().isoformat(timespec="seconds"),
                                    "contentType": content_type, "baseHash": base_hash, "research": research, "summary": result["summary"]}

    return _start_ai_task(job, "research", None, work, apply)


def choose_more_value(job_id: str, key: str, index: int) -> dict:
    """초안에서 기존 값과 추가 조사 값이 다를 때 하나를 고릅니다. 지금 자료는 바꾸지 않습니다."""
    job, draft = _require_draft(job_id)
    try:
        research_merge.choose_more_value(draft["research"], key, index)
    except KeyError:
        raise JobConflict("조사 항목을 찾을 수 없어요") from None
    except ValueError as e:
        raise JobConflict(str(e)) from None
    if job["contentType"] == "character" and draft["research"].get("items"):
        draft["research"]["people"] = research_items.people_from(draft["research"])
    save(job)
    return job


def accept_more_research(job_id: str) -> dict:
    """초안을 조사 자료로 통합합니다. 구성안 단계면 새 조사 버전으로 저장하고(이전 버전은 그대로), 구성안은 바꾸지 않고 경고만 다시 계산합니다.
    통합 자료 검토 단계(waiting_research)면 '이 자료로 구성안 만들기'를 누를 때 검토 결과와 함께 새 버전으로 저장합니다."""
    job, draft = _require_draft(job_id)
    if draft.get("contentType") != job["contentType"] or _research_hash(job["research"]) != draft["baseHash"]:
        raise JobConflict("추가 조사 뒤에 조사 자료가 바뀌었어요. 이 결과를 버리고 다시 조사해 주세요")
    left = research_merge.open_conflicts(draft["research"], draft["round"])
    if left:
        labels = {i["key"]: i["label"] for i in draft["research"].get("items") or []}
        raise JobConflict(f"기존 자료와 추가 조사 값이 다른 항목({', '.join(labels.get(k, k) for k in left)})에서 쓸 값을 먼저 골라 주세요")
    research = draft["research"]
    previous = job.get("researchVersion")
    entry = {"round": draft["round"], "request": draft["request"], "at": draft["at"], "acceptedAt": datetime.now().isoformat(timespec="seconds"),
             **{k: draft["summary"].get(k, []) for k in ("added", "extended", "confirmed", "conflicts", "sources", "people")},
             "facts": draft["summary"].get("facts", 0),
             "basedOn": {k: previous.get(k) for k in ("id", "number", "researchedAt")} if previous else None}
    research["moreResearch"] = (research.get("moreResearch") or []) + [entry]
    job["research"] = research
    job["researchDraft"] = None
    job.setdefault("moreResearchLog", []).append({"round": draft["round"], "request": draft["request"], "at": draft["at"], "result": "accepted"})
    _refresh_people(job)
    if job["state"] == "waiting_research":
        job["research"]["supplement"]["moreRounds"] = job["research"]["supplement"].get("moreRounds", []) + [draft["round"]]
    else:
        if previous:
            research["basedOn"] = entry["basedOn"]
        try:
            summary = research_library.save(job, research)
            job["researchVersion"] = {"id": summary["id"], "number": summary["number"], "researchedAt": summary["researchedAt"],
                                      "source": "more", "basedOn": entry["basedOn"], "round": draft["round"]}
        except OSError:
            pass  # 보관함에 쓰지 못해도 작업의 자료는 통합됩니다
        if job.get("outline"):
            job["outline"]["researchUpdated"] = {"round": draft["round"], "at": entry["acceptedAt"]}  # 구성안 다시 생성 안내
            job["outline"]["issues"] = _issues(job)
    _refresh_gap(job)
    save(job)
    return job


def discard_more_research(job_id: str) -> dict:
    """초안을 버립니다. 지금 자료와 구성안은 바뀌지 않습니다 (요청 내용만 기록에 남김)."""
    job = _require(job_id, *MORE_STATES)
    draft = job.get("researchDraft")
    if not draft:
        raise JobConflict("버릴 추가 조사 결과가 없어요")
    job.setdefault("moreResearchLog", []).append({"round": draft["round"], "request": draft["request"], "at": draft["at"], "result": "discarded"})
    job["researchDraft"] = None
    save(job)
    return job


def research_versions(content_type: str, topic: str) -> list[dict]:
    return research_library.versions(content_type, topic)


def research_version_usage(version_id: str) -> list[dict]:
    """이 조사 버전과 연결된 작업 (그 자료로 시작했거나, 새로 조사해 그 버전을 저장한 작업).

    작업은 시작할 때 자료를 복사해 두므로 버전을 지워도 작업 내용은 바뀌지 않습니다. 삭제 전에 알려 주는 데 씁니다.
    """
    used = []
    if not DATA_DIR.is_dir():
        return used
    for path in DATA_DIR.glob("*/job.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        research = job.get("research") or {}
        linked = version_id in ((job.get("researchVersion") or {}).get("id"), (job.get("researchBase") or {}).get("id"),
                                (research.get("fromLibrary") or {}).get("id"), (research.get("basedOn") or {}).get("id"))
        if linked:
            used.append({"id": job.get("id"), "topic": job.get("topic", ""), "state": job.get("state", ""),
                         "source": (job.get("researchVersion") or {}).get("source", "saved")})
    return used


def delete_research_version(version_id: str) -> dict | None:
    """조사 버전 하나를 지웁니다. 연결된 작업은 복사해 둔 자료를 그대로 쓰므로 고치지 않습니다. 없으면 None."""
    usage = research_version_usage(version_id)
    if not research_library.delete(version_id):
        return None
    return {"deleted": version_id, "usedBy": usage}


def _set_step(job: dict, key: str, status: str) -> None:
    for step in job["steps"]:
        if step["key"] == key:
            step["status"] = status


def _start(job_id: str, coro) -> None:
    task = asyncio.create_task(_guard(job_id, coro))
    _tasks[job_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(job_id, None))


async def _guard(job_id: str, coro) -> None:
    try:
        await coro
    except Exception as e:  # 실패를 화면에 그대로 보여 줍니다
        job = _read(job_id)
        job["state"] = "failed"
        job["error"] = f"제작 중 오류가 났어요: {e}"
        for step in job["steps"]:
            if step["status"] == "active":
                step["status"] = "failed"
        save(job)


async def _step(job_id: str, key: str, work=None) -> None:
    job = _read(job_id)
    _set_step(job, key, "active")
    save(job)
    await asyncio.sleep(0 if _is_ai(job) else DEMO_STEP_SECONDS)
    job = _read(job_id)
    if work:
        work(job)
    _set_step(job, key, "done")
    save(job)


def _finish(job_id: str, state: str) -> None:
    job = _read(job_id)
    job["state"] = state
    save(job)


# ---------- 이미지 ----------
def _visible(job: dict) -> list[dict]:
    return [a for a in job["assets"] if not a["removed"]]


def _asset(job: dict, asset_id: str) -> dict:
    asset = next((a for a in _visible(job) if a["id"] == asset_id), None)
    if asset is None:
        raise KeyError(asset_id)
    return asset


def _is_processing(asset: dict) -> bool:
    return bool(asset["cutout"]) and asset["cutout"]["status"] == "processing"


def _has_cutout(asset: dict) -> bool:
    return bool(asset["cutout"]) and bool(asset["cutout"].get("file"))


def _ensure_not_running(job: dict) -> None:
    if job["state"] == "running" or job.get("aiTask"):
        raise JobConflict("제작이 진행 중이에요. 끝난 뒤에 다시 시도해 주세요")


def add_asset(job_id: str, asset: dict) -> dict:
    job = _require_job(job_id)
    _ensure_not_running(job)
    job["assets"].append(asset)
    save(job)
    return job


def update_asset(job_id: str, asset_id: str, rights: str | None, source: str | None, use_variant: str | None) -> dict:
    job = _require_job(job_id)
    _ensure_not_running(job)
    asset = _asset(job, asset_id)
    new_rights = asset["rights"] if rights is None else rights
    new_source = asset["source"] if source is None else source
    if new_rights == PERMITTED and not new_source:
        raise JobConflict("사용 권한이 '허가됨'이면 출처를 적어 주세요")
    if use_variant == "cutout" and not _has_cutout(asset):
        raise JobConflict("아직 배경을 제거한 이미지가 없어요")
    asset.update(rights=new_rights, source=new_source)
    if use_variant and use_variant != asset["useVariant"]:
        asset["useVariant"] = use_variant
        _apply_variant(job, asset_id, use_variant)  # 배경 제거 ON/OFF: 원본을 직접 고른 자리는 그대로 둡니다
    _drop_unusable_images(job)
    save(job)
    return job


def remove_asset(job_id: str, asset_id: str) -> dict:
    """목록에서만 뺍니다. 올린 원본과 누끼 파일은 지우지 않습니다."""
    job = _require_job(job_id)
    _ensure_not_running(job)
    asset = _asset(job, asset_id)
    if _is_processing(asset):
        raise JobConflict("배경 제거가 끝난 뒤에 뺄 수 있어요")
    asset["removed"] = True
    _drop_unusable_images(job)
    save(job)
    return job


def _usable(job: dict, image: dict) -> bool:
    asset = next((a for a in _visible(job) if a["id"] == image["assetId"]), None)
    return bool(asset) and usable_asset(asset) and (image["variant"] == "original" or _has_cutout(asset))


def _drop_unusable_images(job: dict) -> None:
    """쓸 수 없게 됐거나 뺀 이미지를 카드에서 내립니다. 그 카드가 바뀌므로 디자인 승인을 해제합니다."""
    if templates.is_template_job(job):
        before = json.loads(json.dumps(job.get("slotImages") or {}))
        if _drop_slot_images(job):
            dropped = {f: [k for k, image in slots.items() if image != before[f].get(k)] for f, slots in job["slotImages"].items()}
            _on_slots_changed(job, dropped)  # 이미지를 내리기만 하므로 새로 확인할 사진은 없습니다
        return
    images = job.get("cardImages") or {}
    changed = [frame for frame, image in images.items() if image and not _usable(job, image)]
    for frame in changed:
        images[frame] = None
    if changed and job.get("preview"):
        for frame in changed:
            _rebuild_card(job, frame)
        _revoke_preview(job)


def start_cutout(job_id: str, asset_id: str, model: str) -> dict:
    job = _require_job(job_id)
    _ensure_not_running(job)
    asset = _asset(job, asset_id)
    if _is_processing(asset):
        raise JobConflict("이미 배경을 제거하고 있어요")
    if model not in cutout.MODELS:
        raise JobConflict("알 수 없는 모델이에요")
    info = asset["cutout"] or {"file": None, "version": 0, "stats": None}
    # 이전 결과는 성공할 때까지 그대로 둡니다
    asset["cutout"] = {**info, "status": "processing", "pendingModel": model, "error": None}
    save(job)
    key = _cutout_key(job_id, asset_id)
    task = asyncio.create_task(_run_cutout(job_id, asset_id, model))
    _cutout_tasks[key] = task
    task.add_done_callback(lambda _t: _cutout_tasks.pop(key, None))
    return job


def _cutout_key(job_id: str, asset_id: str) -> str:
    return f"{job_id}:{asset_id}"


async def _run_cutout(job_id: str, asset_id: str, model: str) -> None:
    job = _read(job_id)
    asset = next(a for a in job["assets"] if a["id"] == asset_id)
    version = asset["cutout"]["version"] + 1
    source = uploads_dir(job_id) / f"{asset_id}{asset['ext']}"
    target = uploads_dir(job_id) / f"{asset_id}-cutout-{version}.png"  # 원본과 이전 결과를 덮어쓰지 않음
    stats, error = None, None
    try:
        stats = await asyncio.to_thread(cutout.run_cutout, source, target, model)
    except cutout.CutoutError as e:
        error = str(e)
    except Exception:
        error = "배경 제거 중 오류가 났어요."

    job = _read(job_id)
    asset = next(a for a in job["assets"] if a["id"] == asset_id)
    if error:
        asset["cutout"].update(status="failed", error=error, pendingModel=None)
    else:
        asset["cutout"] = {"status": "done", "file": target.name, "version": version, "model": model, "stats": stats, "error": None, "pendingModel": None}
        asset["useVariant"] = "cutout"  # 배경 제거 ON
        _apply_variant(job, asset_id, "cutout", refresh=True)
    save(job)


def _apply_variant(job: dict, asset_id: str, variant: str, refresh: bool = False) -> None:
    """이 이미지를 쓰는 카드 자리를 원본 또는 누끼로 바꿉니다. 사용자가 그 자리에서 원본을 직접 고른 경우(keepOriginal)는 그대로 둡니다.

    refresh: 누끼를 새로 만든 경우. 이미 누끼를 쓰던 자리도 그림이 달라지므로 다시 승인받습니다.
    """
    changed = False
    if templates.is_template_job(job):
        for slots in (job.get("slotImages") or {}).values():
            for image in slots.values():
                if not image or image["assetId"] != asset_id or image.get("keepOriginal"):
                    continue
                changed = changed or image["variant"] != variant or (refresh and variant == "cutout")
                image["variant"] = variant
        if changed and job.get("preview"):
            _refresh_template_preview(job)
            _revoke_preview(job)
        return
    images = job.get("cardImages") or {}
    frames = [f for f, i in images.items() if i and i["assetId"] == asset_id and (i["variant"] != variant or refresh)]
    for frame in frames:
        images[frame] = {"assetId": asset_id, "variant": variant}
    if frames and job.get("preview"):
        for frame in frames:
            _rebuild_card(job, frame)
        _revoke_preview(job)


# ---------- 구성안 ----------
def _issues(job: dict) -> dict:
    """글자 수 규칙에 출처 검증을 더합니다. 검색 기록으로 확인되지 않은 출처는 확인된 것으로 표시하지 않습니다."""
    cards = job["outline"]["cards"]
    issues = _base_issues(job, cards)
    if not _is_ai(job):
        return issues
    if templates.is_template_job(job) and job.get("research"):
        _check_fields_against_research(job, cards, issues)
        job["outline"]["publishWarnings"] = publish_warnings(job)
        _refresh_gap(job)
    strict = job["contentType"] != "character"
    research = job.get("research")
    if strict:
        material = material_text(research, job.get("userMaterial"))
        for card in cards:
            text = templates.card_text(card) if templates.is_template_job(job) else f"{card['title']} {card['body']}"
            numbers = unsupported_numbers(text, material)
            if numbers:
                message = f"자료에 없는 숫자예요: {', '.join(numbers)}"
                issues[card["frame"]]["warnings" if card["edited"] else "errors"].append(message)
    for card in cards[1:]:  # 표지는 사실을 담지 않으므로 근거가 없어도 됩니다
        state = card_source_state(card, research)
        cited = [s for s in research["sources"] if s["id"] in card["sourceIds"]] if research else []
        if any(s["verification"] == "user_provided" for s in cited):
            issues[card["frame"]]["warnings"].append("사용자가 제공한 자료가 들어 있어요. 게시 전에 내용을 한 번 더 확인해 주세요")
        if any(s["verification"] == "image" for s in cited):
            issues[card["frame"]]["warnings"].append("상세 이미지에서 AI가 읽은 정보가 들어 있어요. 조사 결과의 출처 이미지와 대조해 확인해 주세요")
        # 공식 여부로는 막지 않습니다 (2차 자료·나무위키·값이 적힌 검색 결과도 근거). 출처 종류는 조사 결과에 남습니다
        if state in ("user_provided", "image", "verified"):
            continue
        if state == "listed":
            issues[card["frame"]]["warnings"].append("검색 결과에서 확인한 정보예요. 원문 페이지는 읽지 못했어요")
            continue
        # 근거 URL이 조회 기록에 없음 = 출처가 없는 사실: 지어낸 내용을 막기 위해 직접 고치기 전까지 승인을 막습니다 (캐릭터 소개는 경고)
        message = "이 카드의 근거 URL을 실제 조회 기록에서 확인하지 못했어요. 근거 없는 내용을 지우거나 고쳐 주세요"
        issues[card["frame"]]["errors" if strict and not card["edited"] else "warnings"].append(message)
    return issues


VOLATILE_DAYS = 30  # 원문 게시일이 조사일보다 이만큼 오래되면 최신 정보인지 확인을 권합니다


def item_dates(item: dict | None) -> tuple[str, str]:
    """(원문 게시일, 조사일). 게시일은 출처에 보이는 날짜만 (없으면 빈 문자열), 조사일은 근거 기록 시각의 날짜입니다."""
    if not item:
        return "", ""
    evidence = item.get("evidence") or []
    published = max((e.get("publishedAt") or "" for e in evidence), default="")
    researched = max(((e.get("at") or "")[:10] for e in evidence), default="")
    return published, researched


def _stale(published: str, researched: str) -> bool:
    try:
        return (datetime.fromisoformat(researched) - datetime.fromisoformat(published)).days > VOLATILE_DAYS
    except ValueError:
        return False


def publish_warnings(job: dict) -> list[dict]:
    """PNG로 저장하기 전에 알려 줄 확인할 정보. 저장을 막지 않습니다. [{frame, text}]

    공식 확인 여부가 아니라 근거가 약한 정보(출처 충돌·근거 확인 못 함·원문 미확인 검색 결과), 사용자 제공·이미지 판독,
    변동 정보(가격·기간 등)의 원문 게시일과 조사일을 알립니다.
    """
    research = job.get("research") or {}
    items = {i["key"]: i for i in research.get("items") or []}
    states = (job.get("outline") or {}).get("fieldStates") or {}
    warnings = []
    if research.get("partial") or (job.get("researchStage") or {}).get("forced"):
        warnings.append({"frame": "", "text": "자료가 부족한 상태에서 작성한 카드뉴스예요. 비어 있는 정보가 없는지 확인해 주세요"})
    labels = research_items.FIELD_STATE_LABELS
    for card in (job.get("outline") or {}).get("cards", []):
        tpl = templates.template_for(job, card["frame"])
        for field in tpl["fields"]:
            state = (states.get(card["frame"]) or {}).get(field["key"])
            item = items.get(field.get("item"))
            if not state or state == "missing" or not item:
                continue
            # 가격·일정·장소처럼 공식 우선이거나 중요한 정보는 공식 확인이 아니면 출처 종류를 알립니다 (막지 않음)
            important = item.get("strict") or item.get("volatile") or item.get("importance") in ("core", "high")
            notes = [labels.get(state, state)] if state != "verified" and (important or state in ("conflict", "unverified", "absent")) else []
            if state == "listed":
                notes.append("서버가 검색 결과 원문을 확인하지 못함")
            if item.get("volatile"):
                published, researched = item_dates(item)
                notes.append(f"원문 게시일 {published or '확인 안 됨'} · 조사일 {researched or '확인 안 됨'} 기준")
            if notes:
                warnings.append({"frame": card["frame"], "text": f"{field['label']}: {' · '.join(notes)}"})
    return warnings


def _check_fields_against_research(job: dict, cards: list[dict], issues: dict) -> None:
    """필드마다 근거가 된 조사 항목의 상태를 기록하고, 출처 충돌·근거가 약한 정보를 알립니다.

    공식 확인 여부로는 막지 않습니다. 출처가 없는 사실(조회 기록에 없는 근거)만 굿즈·팝업·콜라보에서 직접 고치기 전까지 승인을 막습니다.
    """
    research = job["research"]
    states = _field_states(job, cards)
    job["outline"]["fieldStates"] = states
    items = {i["key"]: i for i in research.get("items") or []}
    for card in cards:
        tpl = templates.template_for(job, card["frame"])
        notes = issues[card["frame"]]
        for field in tpl["fields"]:
            if field.get("verifyItems"):
                _check_profile_rows(card, field, states[card["frame"]], notes)
                continue
            state = states[card["frame"]].get(field["key"])
            item = items.get(field.get("item"))
            strict = job["contentType"] != "character"
            target = notes["warnings"]
            if state == "conflict" and item:
                values = " / ".join([item["value"]] + [a["value"] for a in item["alternatives"]])
                message = f"출처마다 값이 달라요: {field['label']} ({values}). 맞는 값을 확인해 고쳐 주세요"
            elif state == "listed" and item and not item.get("quote"):
                message = f"근거를 확인하지 못한 정보예요: {field['label']} (검색 결과에 값이 없음)"
            elif state == "absent":
                # 조사 항목에도 자료에도 없는 값: 수정을 안내하고 막지는 않습니다 (지어낸 숫자는 숫자 검사가 따로 막음)
                message = f"조사에서 찾지 못한 정보예요: {field['label']}. 근거를 확인하고 고치거나 지워 주세요"
            elif state == "unverified":
                message = f"근거를 확인하지 못한 정보예요: {field['label']}. 지우거나 고쳐 주세요"
                if strict and not card["edited"] and item and item["state"] == "unverified":
                    # 조사 항목의 근거가 조회 기록에 없음 = 출처가 없는 사실: 지어낸 내용일 수 있어 직접 확인하기 전까지 막습니다
                    target = notes["errors"]
            elif item and item.get("volatile") and state not in (None, "missing"):
                published, researched = item_dates(item)
                if not (published and researched and _stale(published, researched)):
                    continue
                message = f"{field['label']}: 원문 게시일 {published} 자료예요 (조사일 {researched}). 최신 정보인지 확인해 주세요"
            else:
                continue
            if message not in target:
                target.append(message)
        for cleared in card.get("cleared") or []:
            message = f"조사에서 찾지 못한 정보라 비웠어요: {cleared['label']} ('{cleared['value']}'). 확인했다면 직접 입력해 주세요"
            if message not in notes["warnings"]:
                notes["warnings"].append(message)
        if tpl["id"].endswith(f"-{templates.FREE}"):
            _check_free_card(card, items, notes, job["contentType"] != "character")


def support_text(job: dict) -> str:
    """칸 값을 대조할 자료: 근거가 있는 조사 사실, 조사 항목의 값과 근거 문장(다른 값 포함), 사용자가 준 자료."""
    research = job.get("research") or {}
    ok = {s["id"] for s in research.get("sources", []) if s.get("verification") in ("fetched", "search_result", "user_provided", "image")}
    parts = [f.get("text", "") for f in research.get("facts", []) if set(f.get("sourceIds", [])) & ok]
    for item in research.get("items") or []:
        if item.get("state") in research_items.EMPTY_STATES:
            continue
        for entry in [item] + list(item.get("alternatives") or []):
            parts += [str(entry.get("value") or ""), str(entry.get("quote") or "")]
    for person in (research.get("peopleResearch") or {}).get("people", []):
        parts += [str(person.get(k) or "") for k in ("name", "relation", "tmi")]
    parts.append(material_text(research, job.get("userMaterial")))
    parts += [str(job.get("notes") or ""), str((job.get("userMaterial") or {}).get("pasted") or "")]
    return "\n".join(parts)


def _field_states(job: dict, cards: list[dict]) -> dict:
    research = job["research"]
    return research_items.field_states(cards, lambda frame: templates.template_for(job, frame), research.get("items"),
                                       lambda card: card_source_state(card, research), support_text(job))


def clear_unsupported(job: dict, frames: list[str] | None = None) -> None:
    """AI가 쓴 카드에서 조사 항목에도 자료에도 없는 짧은 사실 칸(날짜·가격·장소·명칭 등)을 비웁니다.

    공식 우선 항목이거나 바뀌기 쉬운 정보인 한 줄 칸만 비우고, 꼭 필요한 칸·여러 줄 글·목록은 남겨 경고로 안내합니다 (제작을 멈추지 않게).
    사용자가 직접 고친 카드는 건드리지 않습니다. 비운 값은 card.cleared에 남겨 구성안에서 알려 줍니다.
    """
    if not job.get("research") or not templates.is_template_job(job) or not job.get("outline"):
        return
    cards = [c for c in job["outline"]["cards"] if (frames is None or c["frame"] in frames) and not c.get("edited")]
    if not cards:
        return
    states = _field_states(job, cards)
    items = {i["key"]: i for i in job["research"].get("items") or []}
    for card in cards:
        tpl = templates.template_for(job, card["frame"])
        cleared = []
        for field in tpl["fields"]:
            item = items.get(field.get("item")) or {}
            spec_fact = item.get("strict") or item.get("volatile")
            if states[card["frame"]].get(field["key"]) != "absent" or field["type"] != "text" or field.get("required") or not spec_fact:
                continue
            cleared.append({"key": field["key"], "label": field["label"], "value": card["fields"][field["key"]]})
            card["fields"][field["key"]] = ""
        if cleared:
            card["cleared"] = cleared


def _check_profile_rows(card: dict, field: dict, states: dict, notes: dict) -> None:
    """프로필 줄마다 조사 값과 대조합니다. 조사 값에 없는 줄은 근거 없음, 출처끼리 다른 값은 충돌로 알립니다 (캐릭터 소개는 경고)."""
    for n, row in enumerate(card["fields"].get(field["key"]) or []):
        state = states.get(f"{field['key']}.{n}")
        label = row.get("label") or f"{field['label']} {n + 1}"
        if state == "conflict":
            message = f"출처마다 값이 달라요: {label} ({row.get('value', '')}). 맞는 값을 확인해 고쳐 주세요"
        elif state in ("listed", "unverified"):
            message = f"근거를 확인하지 못한 정보예요: {label}"
        else:
            continue
        if message not in notes["warnings"]:
            notes["warnings"].append(message)


def _check_free_card(card: dict, items: dict, notes: dict, strict: bool = False) -> None:
    """자유 구성 카드는 필드가 조사 항목과 연결되지 않으므로, 문구 안에 충돌·근거 없는 값이 들어 있는지 직접 찾습니다."""
    text = research_items._norm(templates.card_text(card))
    for item in items.values():
        weak = item["state"] in research_items.WEAK_STATES or (item["state"] == "listed" and not item.get("quote"))
        if not weak:
            continue
        values = [v for v in [item["value"]] + [a["value"] for a in item.get("alternatives", [])] if v]
        if not any(len(research_items._norm(v)) >= 2 and research_items._norm(v) in text for v in values):
            continue
        target = notes["warnings"]
        if item["state"] == "conflict":
            message = f"출처마다 값이 달라요: {item['label']} ({' / '.join(values)}). 맞는 값을 확인해 고쳐 주세요"
        else:
            message = f"근거를 확인하지 못한 정보예요: {item['label']}. 확인해서 고치거나 지워 주세요"
            if strict and item["state"] == "unverified" and not card["edited"]:
                target = notes["errors"]
        if message not in target:
            target.append(message)


def _make_outline(job: dict) -> None:
    version = (job["outline"]["version"] + 1) if job.get("outline") else 1
    if templates.is_template_job(job):
        old = {c["frame"]: c for c in (job.get("outline") or {}).get("cards", [])}
        made = [templates.keep_user_fields(old.get(frame), templates.demo_card(job, frame, version - 1)) for frame in FRAMES]
    else:
        made = get_provider().create_outline(job)
    cards = [{**c, "edited": False, "regenCount": 0} for c in made]
    job["outline"] = {"version": version, "cards": cards, "approved": False, "issues": {},
                      "otherNames": (job.get("outline") or {}).get("otherNames", [])}
    _ensure_slot_images(job)
    friends.sync(job)
    job["outline"]["issues"] = _base_issues(job, cards)


def _record_calls(job: dict, calls: list[dict]) -> None:
    job["aiCalls"] = (job["aiCalls"] + calls)[-30:]
    for call in reversed(calls):
        if call.get("fiveHourUtilization") is not None:
            job["aiUsage"] = {"fiveHourUtilization": call["fiveHourUtilization"], "at": call["at"]}
            break


def _ai_fail(job_id: str, message: str) -> None:
    job = _read(job_id)
    job["state"] = "failed"
    job["error"] = message
    for step in job["steps"]:
        if step["status"] == "active":
            step["status"] = "failed"
    save(job)


async def _ai_build_outline(job_id: str) -> None:
    job = _read(job_id)
    _set_step(job, "research", "active")
    save(job)
    if job["contentType"] == AUTO_TYPE:
        try:
            chosen = await asyncio.to_thread(get_ai_provider().classify_type, job)
        except AIError as e:
            _ai_fail(job_id, e.message)
            return
        job = _read(job_id)
        _record_calls(job, chosen["calls"])
        _apply_type(job, chosen["contentType"], "ai", chosen["reason"])
        save(job)
    provider = get_ai_provider()
    if separates_research(job) and hasattr(provider, "research_only"):
        await _ai_research_then_compose(job_id, job, provider)
        return
    try:
        result = await asyncio.to_thread(provider.research_outline, job, uploads_dir(job_id))
    except AIError as e:
        _ai_fail(job_id, e.message)
        return
    job = _read(job_id)
    _record_calls(job, result["calls"])
    site_policy.record_failures(result["research"]["fetchFailures"])
    _apply_outline_result(job, result)
    save(job)


async def _ai_research_then_compose(job_id: str, job: dict, provider, compose_only: bool = False) -> None:
    """1단계 자료 조사 → 조사 결과를 작업에 저장 → 2단계 구성안 작성.

    조사 결과를 먼저 저장하므로 구성안 작성이 실패해도 조사를 잃지 않고, 다시 시도하면 검색 없이 구성안만 씁니다.
    """
    if not compose_only:
        try:
            found = await asyncio.to_thread(provider.research_only, job, uploads_dir(job_id))
        except AIError as e:
            _ai_fail(job_id, e.message)
            return
        job = _read(job_id)
        _record_calls(job, found["calls"])
        site_policy.record_failures(found["research"]["fetchFailures"])
        if found["status"] == "need_material":
            _apply_outline_result(job, found)
            save(job)
            return
        job["research"] = found["research"]
        if found.get("extraction") is not None:
            job["detailExtraction"] = found["extraction"]
        if job["contentType"] == "character" and job["research"].get("items"):
            job["research"]["people"] = research_items.people_from(job["research"])
        job["researchStage"] = {"done": True, "coreOnly": found["coreOnly"], "at": datetime.now().isoformat(timespec="seconds")}
        _set_step(job, "research", "done")
        _set_step(job, "outline", "active")
        save(job)  # 조사 결과를 먼저 저장합니다 (화면에서 바로 볼 수 있고, 구성안 실패 시에도 남음)
    stage = job.get("researchStage") or {}
    try:
        result = await asyncio.to_thread(provider.compose_from_research, job, job["research"], job.get("detailExtraction"), stage.get("coreOnly", False),
                                         bool(stage.get("forced")))
    except AIError as e:
        _ai_fail(job_id, e.message)
        return
    job = _read(job_id)
    _record_calls(job, result["calls"])
    _apply_outline_result(job, result)
    save(job)


def _apply_outline_result(job: dict, result: dict) -> None:
    """구성안이 나오면 승인 단계로, 자료가 부족하면 자료 입력 단계로 갑니다. 어느 쪽도 제작을 끝내지 않습니다."""
    job["research"] = result["research"]
    if result.get("extraction") is not None:
        job["detailExtraction"] = result["extraction"]
    _set_step(job, "research", "done")
    job["error"] = None
    if job["contentType"] == "character" and job["research"].get("items"):
        # 친구·가족을 카테고리별로 나눠 둡니다 (구성안 편집에서 카테고리를 바꿀 때 불러옴)
        job["research"]["people"] = research_items.people_from(job["research"])
    if result["status"] == "need_material":
        # 조사는 끝났습니다. 다시 검색하지 않고 '현재 자료로 구성안 작성'이나 자료 보완을 고를 수 있게 기록만 남깁니다
        stage = job.get("researchStage") or {}
        job["researchStage"] = {**stage, "done": True, "coreOnly": False, "insufficient": True, "at": datetime.now().isoformat(timespec="seconds")}
        _store_research(job)
        _refresh_gap(job)
        job["state"] = "waiting_material"
        return
    _store_research(job)
    _refresh_gap(job)
    version = job["outline"]["version"] + 1 if job.get("outline") else 1
    cards = [{**c, "edited": False, "regenCount": 0} for c in result["cards"]]
    job["outline"] = {"version": version, "cards": cards, "approved": False, "issues": {},
                      "otherNames": (job.get("outline") or {}).get("otherNames", [])}
    _ensure_slot_images(job)
    friends.sync(job)
    clear_unsupported(job)  # AI가 조사에 없는 날짜·가격·장소 등을 써 넣었으면 비우고 알립니다
    job["outline"]["issues"] = _issues(job)
    _set_step(job, "outline", "done")
    job["state"] = "waiting_outline"


def _refresh_gap(job: dict) -> None:
    """자료 부족 안내(무엇이 왜 부족한지). 진행을 막는 데는 쓰지 않고, 공식 확인 여부와도 따로 둡니다."""
    research = job.get("research") or {}
    if not templates.is_template_job(job) or not _is_ai(job) or not research:
        return
    job["researchGap"] = research_items.gap_report(job["contentType"], research.get("items"), research.get("missing"))


def _store_research(job: dict) -> None:
    """새로 조사한 자료를 보관함에 새 버전으로 남깁니다 (작업당 한 번). 저장된 자료로 시작한 작업은 다시 저장하지 않습니다."""
    research = job.get("research") or {}
    if job.get("researchVersion") or research.get("fromLibrary") or not research.get("searchPerformed") or not templates.is_template_job(job):
        return
    try:
        summary = research_library.save(job, research)
    except OSError:
        return  # 보관함에 쓰지 못해도 제작은 계속합니다
    job["researchVersion"] = {"id": summary["id"], "number": summary["number"], "researchedAt": summary["researchedAt"], "source": "new"}


def compose_with_current(job_id: str) -> dict:
    """자료가 부족하다고 판단됐어도 사용자가 지금 자료로 구성안을 쓰기로 고릅니다. 다시 검색하지 않습니다 (구성안 1회).

    부족 판단은 안내로만 남기고(researchStage.forced), 출처 종류(공식·2차 자료 등)는 바꾸지 않습니다. 찾지 못한 칸은 비웁니다.
    """
    job = _require(job_id, "waiting_material")
    if not _is_ai(job) or not separates_research(job):
        raise JobConflict("이 작업은 자료를 입력해서 이어 가 주세요")
    if job.get("researchDraft"):
        raise JobConflict(DRAFT_PENDING)
    research = job.get("research") or {}
    has_material = bool(research.get("facts")) or any(i.get("value") for i in research.get("items") or [])
    if not has_material:
        raise JobConflict("조사된 자료가 없어 구성안을 쓸 수 없어요. 자료를 입력하거나 추가 조사를 해 주세요")
    stage = job.get("researchStage") or {}
    job["researchStage"] = {**stage, "done": True, "forced": True, "forcedAt": datetime.now().isoformat(timespec="seconds")}
    for step in job["steps"]:
        if step["status"] in ("failed", "active", "skipped"):
            step["status"] = "pending"
    _set_step(job, "research", "done")
    _set_step(job, "outline", "active")
    job.update(state="running", error=None)
    save(job)
    _start(job_id, _ai_research_then_compose(job_id, job, get_ai_provider(), compose_only=True))
    return job


def submit_material(job_id: str, material: dict) -> dict:
    """사용자가 준 자료로 구성안을 만듭니다. 웹에 접속하지 않아 막힌 사이트에 다시 요청하지 않습니다."""
    job = _require(job_id, "waiting_material", "waiting_outline", "failed", "interrupted")
    if not _is_ai(job):
        raise JobConflict("실제 AI 모드에서만 쓸 수 있어요")
    if job.get("outline") and job["outline"]["approved"]:
        raise JobConflict("승인된 구성안이 있어요. 구성안 카드를 직접 수정해 주세요")
    material = _clean_material(material or {})
    for url, kind in [(material.get("sourceUrl", ""), material.get("sourceKind", ""))] + [(b.get("url", ""), b.get("kind", "")) for b in material.get("sources", [])]:
        if url and site_policy.mirror_site(url):
            raise JobConflict("나무위키 미러 사이트 주소는 받지 않아요. 원본 문서나 공식 페이지 주소를 적어 주세요")
    if material:
        job["userMaterial"] = {**material, "submittedAt": datetime.now().isoformat(timespec="seconds")}
    elif not job["detailImages"]:
        raise JobConflict("자료를 입력하거나 상세페이지 이미지를 올려 주세요")
    for step in job["steps"]:
        if step["status"] in ("failed", "active"):
            step["status"] = "pending"
    if job["state"] in ("failed", "interrupted"):
        job["state"] = "waiting_material"
    job["error"] = None
    # 자료를 직접 냈으면 이후 같은 부족 판단으로 다시 막지 않습니다 (공식 확인 여부는 그대로)
    job["researchStage"] = {**(job.get("researchStage") or {}), "forced": True}
    uploads = uploads_dir(job_id)
    return _start_ai_task(job, "compose", None, lambda snapshot: get_ai_provider().compose_outline(snapshot, uploads), _apply_outline_result)


MATERIAL_KINDS = ("", "official", "namuwiki", "other")


def _clean_material(material: dict) -> dict:
    """자료 직접 입력 정리. 빈 칸과 빈 출처 묶음은 버립니다. 출처 종류는 사용자가 고른 표시일 뿐 검증이 아닙니다."""
    out = {k: " ".join(str(material.get(k) or "").split()) if k not in ("features", "pasted", "extra") else str(material.get(k) or "").strip()
           for k in ("name", "price", "seller", "sourceUrl", "features", "pasted", "extra")}
    out["sourceKind"] = material.get("sourceKind") if material.get("sourceKind") in MATERIAL_KINDS else ""
    blocks = []
    for block in (material.get("sources") or [])[:3]:
        if not isinstance(block, dict):
            continue
        url, text = str(block.get("url") or "").strip(), str(block.get("text") or "").strip()
        if url and not re.match(r"^https?://", url):
            raise JobConflict("출처 주소는 http:// 또는 https://로 시작해야 해요")
        if url or text:
            blocks.append({"url": url, "kind": block.get("kind") if block.get("kind") in MATERIAL_KINDS else "", "text": text})
    out["sources"] = blocks
    return {k: v for k, v in out.items() if v}


# ---------- 상세페이지 이미지 (자료 조사용) ----------
DETAIL_STATES = ("draft", "waiting_material", "waiting_outline", "failed", "interrupted")


def _require_detail(job_id: str) -> dict:
    job = _require(job_id, *DETAIL_STATES)
    if job.get("outline") and job["outline"]["approved"]:
        raise JobConflict("승인된 구성안이 있어요. 구성안 카드를 직접 수정해 주세요")
    return job


def check_detail_upload(job_id: str, count: int = 1) -> None:
    job = _require_detail(job_id)
    if len(job["detailImages"]) + count > detail_images.MAX_DETAIL_IMAGES:
        raise JobConflict(f"상세 이미지는 {detail_images.MAX_DETAIL_IMAGES}장까지 올릴 수 있어요")


def new_detail_image(job_id: str, name: str, data: bytes, ext: str, mime: str, origin: str, page_url: str = "", image_url: str = "") -> dict:
    image_id = uuid.uuid4().hex
    (uploads_dir(job_id) / f"{image_id}{ext}").write_bytes(data)  # 파일 이름은 서버가 정합니다
    return {"id": image_id, "name": name, "ext": ext, "mime": mime, "origin": origin, "pageUrl": page_url, "imageUrl": image_url,
            "sha256": hashlib.sha256(data).hexdigest(), "addedAt": datetime.now().isoformat(timespec="seconds")}


def add_detail_images(job_id: str, images: list[dict], fetch_report: dict | None = None) -> dict:
    job = _require_detail(job_id)
    known = {i["sha256"] for i in job["detailImages"]}
    for image in images:
        if image["sha256"] not in known and len(job["detailImages"]) < detail_images.MAX_DETAIL_IMAGES:
            job["detailImages"].append(image)
            known.add(image["sha256"])
    if fetch_report is not None:
        job["detailFetch"] = fetch_report
    save(job)
    return job


def remove_detail_image(job_id: str, image_id: str) -> dict:
    """목록에서만 뺍니다. 파일은 지우지 않습니다. 다음 판독·구성안에서 쓰지 않습니다."""
    job = _require_detail(job_id)
    if not any(i["id"] == image_id for i in job["detailImages"]):
        raise KeyError(image_id)
    job["detailImages"] = [i for i in job["detailImages"] if i["id"] != image_id]
    save(job)
    return job


def detail_image(job_id: str, image_id: str) -> tuple[Path, str] | None:
    job = load(job_id)
    image = next((i for i in (job or {}).get("detailImages", []) if i["id"] == image_id), None) if job else None
    if image is None:
        # 판독 결과가 가리키는 이미지는 목록에서 빼도 보여 줍니다 (출처 확인용)
        refs = ((job or {}).get("detailExtraction") or {}).get("refs") or {}
        if job and image_id in refs.values():
            found = list(uploads_dir(job_id).glob(f"{image_id}.*"))
            return (found[0], "image/jpeg" if found[0].suffix == ".jpg" else f"image/{found[0].suffix[1:]}") if found else None
        return None
    return uploads_dir(job_id) / f"{image['id']}{image['ext']}", image["mime"]


def extract_details(job_id: str) -> dict:
    """상세 이미지에서 상품 정보를 읽습니다 (실제 AI 모드). 결과는 다음 조사·구성안에 함께 씁니다."""
    job = _require_detail(job_id)
    if not _is_ai(job) and job["state"] != "draft":
        raise JobConflict("실제 AI 모드에서만 쓸 수 있어요")
    if not job["detailImages"]:
        raise JobConflict("상세 이미지를 먼저 올려 주세요")
    state = claude_cli.status()
    if not state["available"]:
        raise JobConflict(state["reason"])
    uploads = uploads_dir(job_id)

    def apply(current, result):
        current["detailExtraction"] = result["extraction"]

    return _start_ai_task(job, "vision", None, lambda snapshot: get_ai_provider().extract_detail(snapshot, uploads), apply)


def _apply_design(job: dict, result: dict) -> None:
    old = {c["frame"]: c for c in (job.get("preview") or {}).get("cards", [])}
    keep_previous = result.get("keepPrevious", True)
    cards = []
    for frame in FRAMES:
        spec = result["specs"][frame]
        cards.append({"frame": frame, "layoutName": spec["layoutName"], "layoutLabel": spec["layoutName"], "seed": 0, "spec": spec,
                      "previous": _snapshot(old[frame]) if keep_previous and frame in old else None})
    job["designTheme"] = result["theme"]
    job["preview"] = {"seed": 0, "approved": False, "approvalHash": None, "cards": cards}
    job["cardImages"] = _images_from_preview(job["preview"])


async def _ai_build_design(job_id: str) -> None:
    job = _read(job_id)
    _set_step(job, "copy", "done")  # 문구는 승인된 구성안을 그대로 씁니다
    _set_step(job, "layout", "active")
    job["error"] = None
    save(job)
    try:
        result = await asyncio.to_thread(get_ai_provider().prepare_design, job, uploads_dir(job_id))
    except AIError as e:
        _ai_fail(job_id, e.message)
        return
    job = _read(job_id)
    _record_calls(job, result["calls"])
    _apply_design(job, {**result, "keepPrevious": False})
    _set_step(job, "layout", "done")
    job["state"] = "waiting_preview"
    save(job)


def retry(job_id: str) -> dict:
    """AI 호출이 실패했거나 중단된 단계, 또는 자료가 부족했던 자동 조사를 다시 실행합니다."""
    job = _require(job_id, "failed", "interrupted", "waiting_material")
    if not _is_ai(job):
        raise JobConflict("데모 작업은 다시 시도할 수 없어요. 새로 만들어 주세요")
    designing = job.get("outline") and job["outline"]["approved"]
    wait = site_policy.cooldown_seconds(job.get("url", ""))
    if wait and not designing:
        minutes = max(1, round(wait / 60))
        raise JobConflict(f"이 사이트에 다시 요청하지 않도록 기다리는 중이에요. {minutes}분 뒤에 다시 조사할 수 있어요. 지금은 자료를 직접 입력해 주세요")
    # 조사는 끝났는데 구성안 작성에서 실패·중단됐으면 다시 조사하지 않고 구성안만 씁니다 (한도와 사이트 요청을 아낌)
    compose_only = (not designing and job["state"] in ("failed", "interrupted") and (job.get("researchStage") or {}).get("done")
                    and job.get("research") and not job.get("outline") and separates_research(job))
    for step in job["steps"]:
        if step["status"] in ("failed", "active", "skipped"):
            step["status"] = "pending"
    if compose_only:
        _set_step(job, "research", "done")
        _set_step(job, "outline", "active")
    job.update(state="running", error=None)
    save(job)
    if not designing and not compose_only and job.get("researchBase") and not (job.get("researchStage") or {}).get("done"):
        _start(job_id, _ai_supplement(job_id))  # 저장된 자료로 시작한 작업: 처음부터 새로 조사하지 않고 보완 조사를 다시 합니다
    elif designing and templates.is_template_job(job):
        _start(job_id, _build_template_preview(job_id))  # 템플릿 작업의 디자인 단계는 AI를 부르지 않습니다
    elif compose_only:
        _start(job_id, _ai_research_then_compose(job_id, job, get_ai_provider(), compose_only=True))
    else:
        _start(job_id, _ai_build_design(job_id) if designing else _ai_build_outline(job_id))
    return job


def _start_ai_task(job: dict, kind: str, frame: str | None, work, apply, on_fail=None) -> dict:
    """화면을 유지한 채 AI 작업을 실행합니다. 실패하면 지금 결과는 그대로 두고 이유만 알립니다."""
    job_id = job["id"]
    job["aiTask"] = {"kind": kind, "frame": frame, "startedAt": datetime.now().isoformat(timespec="seconds")}
    job["aiError"] = None
    save(job)
    snapshot = json.loads(json.dumps(job))

    async def run():
        message, result = None, None
        try:
            result = await asyncio.to_thread(work, snapshot)
        except AIError as e:
            message = e.message
        except Exception:
            message = "AI 작업 중 오류가 났어요. 다시 시도해 주세요."
        current = _read(job_id)
        current["aiTask"] = None
        if message:
            current["aiError"] = message
            if on_fail:
                on_fail(current)
        else:
            _record_calls(current, result["calls"])
            apply(current, result)
        save(current)

    task = asyncio.create_task(run())
    _ai_tasks[job_id] = task
    task.add_done_callback(lambda _t: _ai_tasks.pop(job_id, None))
    return job


async def _build_outline(job_id: str) -> None:
    await _step(job_id, "research")
    await _step(job_id, "outline", _make_outline)
    _finish(job_id, "waiting_outline")


def _revoke_outline(job: dict) -> None:
    """구성안이 바뀌면 구성안과 디자인 승인을 모두 해제합니다."""
    job["outline"]["approved"] = False
    if job.get("preview"):
        job["preview"].update(approved=False, approvalHash=None)
    for key in ("copy", "layout", "export"):
        _set_step(job, key, "pending")
    job["state"] = "waiting_outline"


def regenerate_outline(job_id: str) -> dict:
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    if _is_ai(job):
        return _start_outline_rewrite(job, FRAMES, new_version=True)
    _revoke_outline(job)
    job["state"] = "running"
    save(job)

    async def run():
        await _step(job_id, "outline", _make_outline)
        _finish(job_id, "waiting_outline")

    _start(job_id, run())
    return job


def _start_outline_rewrite(job: dict, frames: list[str], new_version: bool) -> dict:
    """저장된 조사 결과로 문구만 다시 씁니다. 검색을 다시 하지 않아 한도를 아낍니다."""
    def work(snapshot):
        return get_ai_provider().rewrite_outline(snapshot, frames)

    def apply(current, result):
        for card in current["outline"]["cards"]:
            if card["frame"] in result["cards"]:
                # 사용자만 입력하는 칸(다음 캐릭터 이름·힌트·공개 문구·회차)은 다시 써도 그대로 둡니다
                card.update(templates.keep_user_fields(card, result["cards"][card["frame"]]), edited=False, regenCount=card["regenCount"] + 1)
                for key in ("checkMarks", "userFields", "cleared"):
                    card.pop(key, None)  # 새로 쓴 문구는 다시 확인합니다
        if new_version:
            current["outline"]["version"] += 1
        friends.sync(current)
        if set(frames) == set(FRAMES):
            current["outline"].pop("researchUpdated", None)  # 통합된 자료로 구성안을 다시 썼으므로 안내를 거둡니다
        clear_unsupported(current, frames)
        _revoke_outline(current)
        current["outline"]["issues"] = _issues(current)

    return _start_ai_task(job, "outline", frames[0] if len(frames) == 1 else None, work, apply)


def change_content_type(job_id: str, content_type: str) -> dict:
    """구성안 단계에서 유형을 바꿉니다. 그 유형의 템플릿 5장에 맞춰 구성안을 다시 만들고 승인을 해제합니다.

    실제 AI 작업은 저장된 조사 결과로 다시 쓰므로 검색을 다시 하지 않습니다 (호출 1회).
    """
    job = _require(job_id, "waiting_outline", "waiting_material", "waiting_preview", "done")
    if not templates.is_template_job(job):
        raise JobConflict("이 작업은 유형을 바꿀 수 없어요. 새 카드뉴스로 만들어 주세요")
    if not templates.enabled(content_type):
        raise JobConflict("이 유형은 아직 템플릿이 없어요")
    if content_type == job["contentType"]:
        return job

    def switch(target: dict) -> None:
        _apply_type(target, content_type, "user")
        target["slotImages"] = None
        target["slotIdentities"] = {}
        target["preview"] = None

    if job["state"] == "waiting_material" or not job.get("outline"):
        switch(job)
        save(job)
        return job
    if not _is_ai(job):
        switch(job)
        _make_outline(job)
        _revoke_outline(job)
        save(job)
        return job
    target = json.loads(json.dumps(job))
    switch(target)

    def apply(current, result):
        switch(current)
        cards = [{**c, "edited": False, "regenCount": 0} for c in result["cards"]]
        current["outline"].update(version=current["outline"]["version"] + 1, cards=cards)
        clear_unsupported(current)
        _revoke_outline(current)
        current["outline"]["issues"] = _issues(current)
        _ensure_slot_images(current)

    return _start_ai_task(job, "retype", None, lambda _snapshot: get_ai_provider().retype_outline(target), apply)


def _outline_card(job: dict, frame: str) -> dict:
    card = next((c for c in job["outline"]["cards"] if c["frame"] == frame), None)
    if card is None:
        raise JobConflict("알 수 없는 카드예요")
    return card


def edit_outline_card(job_id: str, frame: str, values: dict) -> dict:
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    card = _outline_card(job, frame)
    item_order = values.pop("itemOrder", None) or {}
    if templates.is_template_job(job):
        item_order = _check_item_order(templates.template_for(job, frame), values.get("fields") or {}, item_order)
        values = _template_values(job, frame, values)
        keys = ("role", "fields", "source")
        tpl = templates.template_for(job, frame)
        if templates.is_flexible(job) and frame != FRAMES[0]:
            values = templates.fit_template(job, {**values, "frame": frame, "template": tpl["id"]})
            values.pop("frame")
            keys = ("role", "fields", "source", "template")
            tpl = templates.TEMPLATES[values["template"]]
        checked = templates.check_card(values, tpl)
    else:
        keys = ("role", "title", "body", "source")
        checked = check_card(values)
    if checked["errors"]:
        raise JobConflict(checked["errors"][0])
    if all(card.get(k, "") == values[k] for k in keys):
        return job  # 바뀐 내용이 없으면 승인도 그대로
    if item_order and values.get("template", card.get("template")) == card.get("template") and (job.get("slotImages") or {}).get(frame):
        # 친구를 지우거나 순서를 바꾸면 친구별 이미지가 그 친구를 따라갑니다
        job["slotImages"][frame] = templates.remap_item_slots(templates.template_for(job, frame), job["slotImages"][frame], item_order)
    if values.get("template", card.get("template")) == card.get("template"):
        changed = {k for k, v in values.get("fields", {}).items() if v != (card.get("fields") or {}).get(k)}
        card["userFields"] = sorted(set(card.get("userFields") or []) | changed)  # 사용자가 직접 쓴 칸
    else:
        card.pop("userFields", None)
    card.update(values, edited=True)
    card.pop("checkMarks", None)  # 예전 '확인 필요' 표시는 더 쓰지 않습니다
    card.pop("cleared", None)
    friends.sync(job)  # 사진으로 확정한 친구 이름은 친구 칸에서만 바꿉니다
    job["outline"]["issues"] = _issues(job)
    _revoke_outline(job)
    save(job)
    return job


def _check_item_order(tpl: dict, raw_fields: dict, orders: dict) -> dict:
    """화면이 보낸 항목 순서(저장 전 번호)를 확인합니다. 저장될 항목 수와 맞지 않으면 쓰지 않습니다 (이미지를 엉뚱한 항목에 붙이지 않게)."""
    result = {}
    for field in tpl["fields"]:
        order = orders.get(field["key"])
        if not field.get("slotPrefix") or not isinstance(order, list):
            continue
        kept = templates.clean_fields({"fields": [field]}, {field["key"]: raw_fields.get(field["key"])})[field["key"]]
        valid = [i for i in order if isinstance(i, int) and -1 <= i < field["maxItems"]]
        used = [i for i in valid if i >= 0]
        if len(valid) == len(order) == len(kept) and len(used) == len(set(used)):
            result[field["key"]] = valid
    return result


def change_card_template(job_id: str, frame: str, template_id: str) -> dict:
    """card-02 ~ card-05의 카드 구성(템플릿)을 바꿉니다. 있는 값만 옮기고 새 사실은 만들지 않습니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    if not templates.is_flexible(job):
        raise JobConflict("이 작업은 카드 구성을 바꿀 수 없어요")
    if frame == FRAMES[0]:
        raise JobConflict("표지(card-01)는 구성을 바꿀 수 없어요")
    if template_id not in templates.body_choices(job["contentType"]):
        raise JobConflict("이 유형에서 쓸 수 없는 카드 구성이에요")
    card = _outline_card(job, frame)
    if card["template"] == template_id:
        return job
    moved = templates.move_fields(job, card, template_id)
    if moved["missing"]:
        raise JobConflict(f"이 구성에는 {', '.join(moved['missing'])} 정보가 필요해요. 확인된 값이 없으면 자유 구성을 써 주세요")
    card.update(template=template_id, fields=moved["fields"], edited=True)
    for key in ("checkMarks", "userFields", "cleared"):
        card.pop(key, None)
    card.pop("convertedFrom", None)
    job["outline"]["issues"] = _issues(job)
    _revoke_outline(job)
    if job.get("preview"):
        _refresh_template_preview(job)
    save(job)
    return job


def regenerate_outline_card(job_id: str, frame: str) -> dict:
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    card = _outline_card(job, frame)
    if _is_ai(job):
        return _start_outline_rewrite(job, [frame], new_version=False)
    count = card["regenCount"] + 1
    if templates.is_template_job(job):
        new = templates.keep_user_fields(card, templates.demo_card(job, frame, job["outline"]["version"] + count))
    else:
        new = get_provider().create_outline_card(job, frame, job["outline"]["version"] + count)
    card.update(new, edited=False, regenCount=count)
    for key in ("checkMarks", "userFields", "cleared"):
        card.pop(key, None)
    friends.sync(job)
    job["outline"]["issues"] = _base_issues(job, job["outline"]["cards"])
    _revoke_outline(job)
    save(job)
    return job


# ---------- 다음 캐릭터 예고 (마무리 카드) ----------
_DATE_RE = re.compile(r"\d|[월화수목금토일]요일|오늘|내일|모레|이번\s*주|다음\s*주|주말|이번\s*달|다음\s*달")


def _teaser_evidence(job: dict, source_ids: list[str]) -> str:
    """힌트 근거로 쓸 수 있는 자료 글. 공식 출처(나무위키 같은 보조 출처 제외)와 사용자가 준 자료만 봅니다."""
    research = job.get("research") or {}
    by_id = {s["id"]: s for s in research.get("sources", [])}
    ok = {i for i in source_ids if i in by_id and not by_id[i].get("auxiliary") and by_id[i].get("kind") in ("official", "user")}
    if not ok:
        return ""
    texts = [f.get("text", "") for f in research.get("facts", []) if ok & set(f.get("sourceIds", []))]
    texts += [f"{i.get('value', '')} {i.get('quote', '')}" for i in research.get("items", []) if ok & set(i.get("sourceIds", []))]
    texts += [f"{p.get('name', '')} {p.get('relation', '')} {p.get('tmi', '')}" for p in (research.get("peopleResearch") or {}).get("people", [])
              if ok & set(p.get("sourceIds", []))]
    if any(by_id[i].get("kind") == "user" for i in ok):
        texts += [job.get("notes", ""), str((job.get("userMaterial") or {}).get("pasted", ""))]
    return "\n".join(texts)


def teaser_fields(job: dict, card: dict, result: dict) -> dict:
    """AI가 쓴 힌트·공개 문구를 확인합니다. 근거가 없거나 다음 캐릭터 이름이 근거 자료에 없으면 힌트는 기본 문구,
    공개 문구에 날짜·요일·시점이 있으면 기본 문구로 바꿉니다 (공개 날짜를 지어내지 않게)."""
    tpl = templates.TEMPLATES[card["template"]]
    spec = templates.next_teaser(tpl)
    limits = {f["key"]: f["max"] for f in tpl["fields"]}
    name = card["fields"].get(spec["name"], "")
    hint = " ".join(str(result.get("hint") or "").split())
    reveal = " ".join(str(result.get("reveal") or "").split())
    evidence = _teaser_evidence(job, result.get("hintSourceIds") or [])
    if not hint or len(hint) > limits[spec["hint"]] or not name or name not in evidence or templates.PLACEHOLDER_RE.search(hint):
        hint = spec["hintDefault"]
    if not reveal or len(reveal) > limits[spec["reveal"]] or _DATE_RE.search(reveal) or templates.PLACEHOLDER_RE.search(reveal):
        reveal = spec["revealDefault"]
    return {spec["hint"]: hint, spec["reveal"]: reveal}


def write_next_teaser(job_id: str, frame: str) -> dict:
    """'힌트·공개 문구 AI로 쓰기' 버튼. 누를 때만 AI를 1회 부릅니다 (검색 없음). 데모는 기본 문구를 넣습니다.
    이름·회차·예고·이미지는 바꾸지 않고, 힌트와 공개 문구만 갱신합니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    card = _outline_card(job, frame)
    spec = templates.next_teaser(templates.TEMPLATES.get(card.get("template"), {})) if templates.is_template_job(job) else None
    if not spec:
        raise JobConflict("다음 캐릭터 예고 카드에서만 쓸 수 있어요")
    name = card["fields"].get(spec["name"], "")
    if not name:
        raise JobConflict("다음 캐릭터 이름을 먼저 입력하고 저장해 주세요")

    def apply(current, result):
        target = _outline_card(current, frame)
        if target.get("template") != card["template"] or target["fields"].get(spec["name"]) != name:
            current["aiError"] = "그사이 다음 캐릭터 이름이 바뀌어서 문구를 넣지 않았어요. 다시 눌러 주세요."
            return
        target["fields"].update(teaser_fields(current, target, result))
        target["edited"] = True
        _revoke_outline(current)
        current["outline"]["issues"] = _issues(current)

    if not _is_ai(job) or not job.get("research"):
        apply(job, {})  # 데모: 지어내지 않고 기본 문구
        save(job)
        return job
    return _start_ai_task(job, "outline", frame, lambda snapshot: get_ai_provider().write_next_teaser(snapshot, frame), apply)


def approve_outline(job_id: str) -> dict:
    job = _require(job_id, "waiting_outline")
    if job.get("researchDraft"):
        raise JobConflict(DRAFT_PENDING)
    for frame, issue in job["outline"]["issues"].items():
        if issue["errors"]:
            raise JobConflict(f"{frame}: {issue['errors'][0]}")
    job["outline"]["approved"] = True
    job["state"] = "running"
    save(job)
    if templates.is_template_job(job):
        _start(job_id, _build_template_preview(job_id))  # 디자인은 템플릿이 정하므로 AI를 부르지 않습니다
        return job
    if _is_ai(job):
        _start(job_id, _ai_build_design(job_id))
        return job

    async def run():
        await _step(job_id, "copy")
        await _step(job_id, "layout", _prepare_layouts)
        _finish(job_id, "waiting_preview")

    _start(job_id, run())
    return job


# ---------- 카드 디자인 ----------
def _layout_pool(has_image: bool) -> list[str]:
    return IMAGE_LAYOUTS if has_image else TEXT_LAYOUTS


def _default_layout(frame: str, seed: int, has_image: bool) -> str:
    index = FRAMES.index(frame)
    if index == 0:
        return "cover"
    pool = _layout_pool(has_image)
    return pool[(index - 1 + seed) % len(pool)]


def _default_card_images(job: dict) -> dict:
    """사용자가 고르기 전 기본값: 올린 이미지를 앞 카드부터 한 장씩만 씁니다 (반복하지 않음)."""
    permitted = [a for a in _visible(job) if usable_asset(a)]
    images = {frame: None for frame in FRAMES}
    for frame, asset in zip(FRAMES, permitted):
        images[frame] = {"assetId": asset["id"], "variant": asset["useVariant"] if _has_cutout(asset) else "original"}
    return images


def _check_text_unchanged(spec, card: dict) -> None:
    """승인된 문구를 레이아웃 생성기가 바꾸지 못하게 합니다."""
    texts = {e.role: e.text for e in spec.elements if isinstance(e, TextElement)}
    for role in ("title", "body", "source"):
        if texts.get(role, "") != card.get(role, ""):
            raise LayoutError(f"{card['frame']}: 레이아웃이 승인된 {role} 문구를 바꿨어요")


def _build_card(job: dict, frame: str, layout_name: str, seed: int) -> dict:
    card = _outline_card(job, frame)
    image = (job.get("cardImages") or {}).get(frame)
    raw = get_provider().create_layout(job, frame, card, layout_name, seed, image)
    # 생성기가 데모든 AI든 검증을 통과한 레이아웃만 화면에 나갑니다
    spec = validate_layout(raw, set(THEMES), {a["id"] for a in _visible(job)})
    _check_text_unchanged(spec, card)
    placed = next((e for e in spec.elements if isinstance(e, ImageElement) and e.assetId), None)
    if image != ({"assetId": placed.assetId, "variant": placed.variant} if placed else None):
        raise LayoutError(f"{frame}: 레이아웃이 사용자가 고른 이미지와 달라요")
    return {"frame": frame, "layoutName": layout_name, "layoutLabel": LAYOUT_LABELS[layout_name], "seed": seed,
            "spec": spec.model_dump(), "previous": None}


def _snapshot(card: dict) -> dict:
    return {k: card[k] for k in ("layoutName", "layoutLabel", "seed", "spec")}


def _prepare_layouts(job: dict) -> None:
    """처음이면 새로 만들고, 구성안을 고쳐 다시 승인했다면 레이아웃과 이미지 선택을 유지한 채 문구만 반영합니다."""
    if job.get("cardImages") is None:
        job["cardImages"] = _default_card_images(job)
    _drop_images_quietly(job)
    if not job.get("preview"):
        job["preview"] = {"seed": 0, "approved": False, "approvalHash": None,
                          "cards": [_build_card(job, f, _default_layout(f, 0, bool(job["cardImages"].get(f))), 0) for f in FRAMES]}
        return
    job["preview"]["cards"] = [_rebuilt(job, card) for card in job["preview"]["cards"]]


def _drop_images_quietly(job: dict) -> None:
    for frame, image in job["cardImages"].items():
        if image and not _usable(job, image):
            job["cardImages"][frame] = None


def _with_image(spec: dict, image: dict | None) -> dict:
    """AI 명세의 이미지만 바꾸거나 뺍니다. 문구와 좌표는 그대로입니다."""
    elements = []
    for el in spec["elements"]:
        if el["type"] != "image":
            elements.append(el)
        elif image:
            elements.append({**el, "assetId": image["assetId"], "variant": image["variant"]})
    return {**spec, "elements": elements}


def _rebuilt(job: dict, card: dict) -> dict:
    frame = card["frame"]
    if _is_ai(job):
        return {**card, "spec": _with_image(card["spec"], job["cardImages"].get(frame)), "previous": None}
    has_image = bool(job["cardImages"].get(frame))
    pool = ["cover"] if frame == FRAMES[0] else _layout_pool(has_image)
    layout_name = card["layoutName"] if card["layoutName"] in pool else _default_layout(frame, card["seed"], has_image)
    return _build_card(job, frame, layout_name, card["seed"])


def _rebuild_card(job: dict, frame: str) -> None:
    cards = job["preview"]["cards"]
    index = FRAMES.index(frame)
    rebuilt = _rebuilt(job, cards[index])
    rebuilt["previous"] = _snapshot(cards[index])
    cards[index] = rebuilt


def _revoke_preview(job: dict) -> None:
    job["preview"].update(approved=False, approvalHash=None)
    _set_step(job, "export", "pending")
    if job["state"] == "done":
        job["state"] = "waiting_preview"


def _require_design(job_id: str) -> dict:
    return _require(job_id, "waiting_preview", "done")


def regenerate_all_layouts(job_id: str) -> dict:
    job = _require_design(job_id)
    _reject_template(job)
    if _is_ai(job):
        uploads = uploads_dir(job_id)

        def apply(current, result):
            _apply_design(current, result)
            _revoke_preview(current)

        return _start_ai_task(job, "design", None, lambda snapshot: get_ai_provider().design_all(snapshot, uploads), apply)
    preview = job["preview"]
    seed = preview["seed"] + 1
    old = {c["frame"]: c for c in preview["cards"]}
    cards = []
    for frame in FRAMES:
        card = _build_card(job, frame, _default_layout(frame, seed, bool(job["cardImages"].get(frame))), seed)
        card["previous"] = _snapshot(old[frame])
        cards.append(card)
    preview.update(seed=seed, cards=cards)
    _revoke_preview(job)
    save(job)
    return job


def _check_frame(frame: str) -> int:
    if frame not in FRAMES:
        raise JobConflict("알 수 없는 카드예요")
    return FRAMES.index(frame)


def regenerate_card(job_id: str, frame: str) -> dict:
    job = _require_design(job_id)
    _reject_template(job)
    index = _check_frame(frame)
    if _is_ai(job):
        return start_redesign(job_id, frame, "")
    if index == 0:
        raise JobConflict("표지(card-01)는 레이아웃을 고정해요")
    cards = job["preview"]["cards"]
    current = cards[index]
    pool = _layout_pool(bool(job["cardImages"].get(frame)))
    neighbours = {cards[i]["layoutName"] for i in (index - 1, index + 1) if 0 <= i < len(cards)}
    position = pool.index(current["layoutName"]) if current["layoutName"] in pool else -1
    candidates = [pool[(position + n) % len(pool)] for n in range(1, len(pool) + 1)]
    candidates = [c for c in candidates if c != current["layoutName"]] or candidates
    # 양옆 카드와 같은 레이아웃은 피하고, 그럴 수 없으면 다음 레이아웃을 씁니다
    layout_name = next((c for c in candidates if c not in neighbours), candidates[0])
    card = _build_card(job, frame, layout_name, current["seed"] + 1)
    card["previous"] = _snapshot(current)
    cards[index] = card
    _revoke_preview(job)
    save(job)
    return job


def _replace_card(job: dict, frame: str, spec: dict) -> None:
    index = FRAMES.index(frame)
    current = job["preview"]["cards"][index]
    job["preview"]["cards"][index] = {"frame": frame, "layoutName": spec["layoutName"], "layoutLabel": spec["layoutName"], "seed": 0,
                                      "spec": spec, "previous": _snapshot(current)}


def start_redesign(job_id: str, frame: str, text: str) -> dict:
    """이 카드만 AI로 다시 디자인합니다. 다른 카드와 문구는 그대로이고, 실패하면 지금 카드를 유지합니다."""
    job = _require_design(job_id)
    _reject_template(job)
    _check_frame(frame)
    if not _is_ai(job):
        raise JobConflict("실제 AI 모드에서만 쓸 수 있어요")
    chosen = job["cardImages"].get(frame)
    uploads = uploads_dir(job_id)
    request_id = None
    if text:
        requests = job["designRequests"].setdefault(frame, [])
        if len(requests) >= MAX_DESIGN_REQUESTS:
            raise JobConflict(f"수정 요청은 카드마다 {MAX_DESIGN_REQUESTS}개까지 저장할 수 있어요")
        request_id = uuid.uuid4().hex
        requests.append({"id": request_id, "text": text, "createdAt": datetime.now().isoformat(timespec="seconds"), "status": "진행 중"})

    def mark(current, status):
        for request in current["designRequests"].get(frame, []):
            if request["id"] == request_id:
                request["status"] = status

    def work(snapshot):
        return get_ai_provider().redesign_card(snapshot, frame, text, chosen, uploads)

    def apply(current, result):
        _replace_card(current, frame, result["spec"])
        current["cardImages"][frame] = chosen
        mark(current, "반영됨")
        _revoke_preview(current)

    return _start_ai_task(job, "redesign", frame, work, apply, lambda current: mark(current, "실패"))


def restore_card(job_id: str, frame: str) -> dict:
    """수정 전 결과로 되돌립니다. 지금 결과와 맞바꾸므로 다시 앞으로 돌아갈 수도 있습니다."""
    job = _require_design(job_id)
    _reject_template(job)
    index = _check_frame(frame)
    current = job["preview"]["cards"][index]
    previous = current.get("previous")
    if not previous:
        raise JobConflict("되돌릴 이전 결과가 없어요")
    image = next((e for e in previous["spec"]["elements"] if e["type"] == "image" and e.get("assetId")), None)
    restored_image = {"assetId": image["assetId"], "variant": image.get("variant", "original")} if image else None
    if restored_image and not _usable(job, restored_image):
        raise JobConflict("이전 결과의 이미지를 지금은 쓸 수 없어요")
    job["cardImages"][frame] = restored_image
    job["preview"]["cards"][index] = {"frame": frame, **previous, "previous": _snapshot(current)}
    _revoke_preview(job)
    save(job)
    return job


def set_card_image(job_id: str, frame: str, asset_id: str | None, variant: str) -> dict:
    job = _require_design(job_id)
    _reject_template(job)
    index = _check_frame(frame)
    image = {"assetId": asset_id, "variant": variant} if asset_id else None
    if image and not _usable(job, image):
        raise JobConflict("카드에 쓸 수 없는 이미지예요")
    if job["cardImages"].get(frame) == image:
        return job
    if _is_ai(job):
        has_slot = any(e["type"] == "image" for e in job["preview"]["cards"][index]["spec"]["elements"])
        if not (image and has_slot):
            # 이미지 자리를 새로 만들거나 없애야 하므로 이 카드만 다시 디자인합니다
            request = "지정된 이미지를 넣어 구성한다." if image else "이미지 없이 글과 장식만으로 완성도 있게 구성한다."
            return _redesign_for_image(job_id, frame, request, image)
        _replace_card(job, frame, _with_image(job["preview"]["cards"][index]["spec"], image))
        job["cardImages"][frame] = image
        _revoke_preview(job)
        save(job)
        return job
    job["cardImages"][frame] = image
    current = job["preview"]["cards"][index]
    rebuilt = _rebuilt(job, current)
    rebuilt["previous"] = _snapshot(current)
    job["preview"]["cards"][index] = rebuilt
    _revoke_preview(job)
    save(job)
    return job


def _redesign_for_image(job_id: str, frame: str, request: str, image: dict | None) -> dict:
    job = _require_design(job_id)
    uploads = uploads_dir(job_id)

    def apply(current, result):
        _replace_card(current, frame, result["spec"])
        current["cardImages"][frame] = image
        _revoke_preview(current)

    return _start_ai_task(job, "redesign", frame, lambda snapshot: get_ai_provider().redesign_card(snapshot, frame, request, image, uploads), apply)


def add_design_request(job_id: str, frame: str, text: str) -> dict:
    """요청을 저장만 합니다. AI가 연결되기 전까지 카드는 바뀌지 않으므로 승인도 그대로입니다."""
    job = _require_job(job_id)
    _reject_template(job)
    _check_frame(frame)
    requests = job["designRequests"].setdefault(frame, [])
    if len(requests) >= MAX_DESIGN_REQUESTS:
        raise JobConflict(f"수정 요청은 카드마다 {MAX_DESIGN_REQUESTS}개까지 저장할 수 있어요")
    requests.append({"id": uuid.uuid4().hex, "text": text, "createdAt": datetime.now().isoformat(timespec="seconds"), "status": "저장됨"})
    save(job)
    return job


def _approval_hash(job: dict) -> str:
    keys = ("frame", "fields", "source") if templates.is_template_job(job) else ("frame", "title", "body", "source")
    content = {"outline": [{k: c.get(k, "") for k in keys} for c in job["outline"]["cards"]],
               "cards": [c["spec"] for c in job["preview"]["cards"]]}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def approve_preview(job_id: str) -> dict:
    job = _require(job_id, "waiting_preview")
    if not job["outline"]["approved"]:
        raise JobConflict("구성안을 먼저 승인해 주세요")
    if any(_is_processing(a) for a in _visible(job)):
        raise JobConflict("배경 제거가 끝난 뒤에 승인해 주세요")
    if templates.is_template_job(job) and _is_ai(job):
        missing = templates.missing_required_images(job)
        if missing:
            raise JobConflict(f"꼭 필요한 이미지를 지정해 주세요: {', '.join(missing)}")
    job["preview"].update(approved=True, approvalHash=_approval_hash(job))
    job["state"] = "running"
    save(job)

    async def run():
        await _step(job_id, "export")
        _finish(job_id, "done")

    _start(job_id, run())
    return job


# ---------- 고정 템플릿 (형식 3) ----------
def _reject_template(job: dict) -> None:
    if templates.is_template_job(job):
        raise JobConflict(TEMPLATE_ONLY)


def _template_values(job: dict, frame: str, values: dict) -> dict:
    """사용자가 고친 값을 템플릿 필드 형식으로 정리합니다. 정의에 없는 항목은 받지 않습니다."""
    tpl = templates.template_for(job, frame)
    try:
        fields = templates.clean_fields(tpl, values.get("fields"), strict=True)
    except ValueError as e:
        raise JobConflict(str(e)) from None
    source = str(values.get("source") or "").strip() if templates.has_source(tpl) else ""
    return {"role": str(values.get("role") or "").strip(), "fields": fields, "source": source}


def _ensure_slot_images(job: dict) -> None:
    """이미지 자리를 빈 상태로 만듭니다. 추천(slotSuggestions)은 사용자가 적용해야 들어갑니다."""
    if templates.is_template_job(job) and job.get("slotImages") is None:
        job["slotImages"] = templates.default_slot_images(job, [])


SCALE_RANGE = (0.3, 3.0)
OFFSET_RANGE = (-1.0, 1.0)  # 이미지 자리 크기에 대한 비율


def _slot_image(asset_id: str, variant: str, previous: dict | None = None, keep_original: bool | None = None) -> dict:
    """카드 이미지 자리의 값. 같은 이미지면 크기·위치 조정값을 이어 갑니다."""
    same = bool(previous) and previous.get("assetId") == asset_id
    return {
        "assetId": asset_id, "variant": variant,
        "keepOriginal": bool(previous.get("keepOriginal")) if keep_original is None and same else bool(keep_original),
        "scale": float(previous.get("scale", 1.0)) if same else 1.0,
        "dx": float(previous.get("dx", 0.0)) if same else 0.0,
        "dy": float(previous.get("dy", 0.0)) if same else 0.0,
    }


def _variant_for(asset: dict) -> str:
    return "cutout" if asset["useVariant"] == "cutout" and _has_cutout(asset) else "original"


def slot_suggestions(job: dict) -> dict:
    """빈 이미지 자리에 넣을 만한 이미지를 제안만 합니다. 아직 어느 자리에도 쓰지 않은 이미지를 앞 카드부터 채웁니다."""
    current = job.get("slotImages")
    if not current:
        return {}
    used = {i["assetId"] for slots in current.values() for i in slots.values() if i}
    queue = [a for a in _visible(job) if usable_asset(a) and a["id"] not in used]
    suggestions = {}
    for frame in FRAMES:
        for slot in templates.active_slots(job, frame):  # 카드에 그려지지 않는 자리(없는 친구의 이미지)는 추천하지 않습니다
            if slot.get("userOnly"):
                continue  # 사용자만 넣는 자리(다음 캐릭터 이미지)에 이번 캐릭터 사진을 추천하지 않습니다
            if queue and not (current.get(frame) or {}).get(slot["key"]):
                asset = queue.pop(0)
                suggestions.setdefault(frame, {})[slot["key"]] = {"assetId": asset["id"], "variant": _variant_for(asset)}
    return suggestions


def _drop_slot_images(job: dict) -> bool:
    changed = False
    for slots in (job.get("slotImages") or {}).values():
        for key, image in slots.items():
            if image and not _usable(job, image):
                slots[key] = None
                changed = True
    return changed


def _template_card(job: dict, card: dict) -> dict:
    tpl = templates.template_for(job, card["frame"])
    return {"frame": card["frame"], "layoutName": tpl["id"], "layoutLabel": f"{tpl['label']} 템플릿",
            "seed": 0, "spec": templates.build_spec(job, card, (job.get("slotImages") or {}).get(card["frame"])), "previous": None}


def _refresh_template_preview(job: dict) -> None:
    job["preview"]["cards"] = [_template_card(job, card) for card in job["outline"]["cards"]]


def _prepare_template_preview(job: dict) -> None:
    _ensure_slot_images(job)
    _drop_slot_images(job)
    job["preview"] = {"seed": 0, "approved": False, "approvalHash": None, "cards": []}
    _refresh_template_preview(job)


async def _build_template_preview(job_id: str) -> None:
    await _step(job_id, "copy")
    await _step(job_id, "layout", _prepare_template_preview)
    _finish(job_id, "waiting_preview")


def set_slot_image(job_id: str, frame: str, slot: str, asset_id: str | None, variant: str) -> dict:
    """템플릿 카드의 이미지 자리에 이미지를 넣거나 뺍니다. 디자인 결과가 있으면 그 승인만 해제됩니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)
    _ensure_slot_images(job)
    previous = job["slotImages"][frame].get(slot)
    image = None
    if asset_id:
        if not _usable(job, {"assetId": asset_id, "variant": variant}):
            raise JobConflict("카드에 쓸 수 없는 이미지예요")
        # 누끼가 있는데 원본을 고르면 사용자가 원본을 직접 선택한 것입니다. 나중에 누끼를 다시 만들어도 바꾸지 않습니다
        keep = variant == "original" and _has_cutout(_asset(job, asset_id))
        image = _slot_image(asset_id, variant, previous, keep)
    return _put_slot(job, frame, slot, image)


def _check_slot(job: dict, frame: str, slot: str) -> None:
    if not templates.is_template_job(job):
        raise JobConflict("이 작업은 카드별 이미지 선택을 써 주세요")
    _check_frame(frame)
    if slot not in {s["key"] for s in templates.slots_of(job, frame)}:
        raise JobConflict("이 카드에는 그런 이미지 자리가 없어요")


def _put_slot(job: dict, frame: str, slot: str, image: dict | None) -> dict:
    if job["slotImages"][frame].get(slot) == image:
        return job
    job["slotImages"][frame][slot] = image
    return _save_after_slots(job, *_on_slots_changed(job, {frame: [slot]}))


def _on_slots_changed(job: dict, changed: dict[str, list[str]]) -> tuple[list, list]:
    """이미지 자리가 바뀐 뒤 처리합니다. 친구 칸이면 이름 확인을 새로 하고, 친구 항목을 맞추고, 구성안 승인을 해제합니다.

    돌려주는 값: (AI로 이름을 확인할 (frame, slot, assetId) 목록, 친구 문구를 다시 쓸 카드 목록)
    """
    pending, touched = [], []
    for frame, keys in changed.items():
        identify = [k for k in keys if friends.is_identify_slot(job, frame, k)]
        if identify:
            touched.append(frame)
            pending += _reset_identities(job, frame, identify)
    rewrite = []
    if touched and job.get("outline"):
        if friends.sync(job):
            rewrite = [f for f in touched if _is_ai(job) and friends.ready(job, f)]
        if job["outline"]["approved"]:
            _revoke_outline(job)
        job["outline"]["issues"] = _issues(job)
    if job.get("preview"):
        _refresh_template_preview(job)
        _revoke_preview(job)
    return pending, rewrite


def _save_after_slots(job: dict, pending: list, rewrite: list) -> dict:
    if rewrite:
        _start_friends_rewrite(job, rewrite[0])  # 저장까지 합니다
    else:
        save(job)
    _start_identify(job["id"], pending)
    return job


# ---------- 친구 칸 사진의 캐릭터 이름 ----------
def _identity_key(job_id: str, frame: str, slot: str) -> str:
    return f"{job_id}:{frame}:{slot}"


def _new_identity(asset_id: str, ai: bool) -> dict:
    return {"assetId": asset_id, "status": "processing" if ai else "manual", "name": "", "suggested": "",
            "confidence": "", "candidates": [], "evidence": "", "error": None}


def _reset_identities(job: dict, frame: str, keys: list[str]) -> list:
    """사진이 바뀐 자리의 식별 기록을 새로 만듭니다. 같은 사진(원본/누끼, 크기 조정)이면 그대로 둡니다."""
    job.setdefault("slotIdentities", {}).setdefault(frame, {})
    friends.rekey(job, frame)  # 순서를 바꿔 옮겨진 사진의 기록을 먼저 그 자리로 옮깁니다
    records = job["slotIdentities"][frame]
    pending = []
    for key in keys:
        image = job["slotImages"][frame].get(key)
        record = records.get(key)
        if not image:
            records.pop(key, None)
        elif not record or record["assetId"] != image["assetId"]:
            records[key] = _new_identity(image["assetId"], _is_ai(job))
            if _is_ai(job):
                pending.append((frame, key, image["assetId"]))
    return pending


def _start_identify(job_id: str, pending: list) -> None:
    for frame, slot, asset_id in pending:
        key = _identity_key(job_id, frame, slot)
        task = asyncio.create_task(_run_identify(job_id, frame, slot, asset_id))
        _identify_tasks[key] = task

        def forget(done: asyncio.Task, key: str = key) -> None:
            # 같은 자리에 새 사진을 넣어 새 확인이 시작됐으면 그 기록은 지우지 않습니다
            if _identify_tasks.get(key) is done:
                _identify_tasks.pop(key)

        task.add_done_callback(forget)


async def _run_identify(job_id: str, frame: str, slot: str, asset_id: str) -> None:
    """구성안 화면을 막지 않고 사진 한 장의 캐릭터 이름 후보를 확인합니다. 결과는 제안일 뿐, 사용자가 확정해야 씁니다."""
    job = _read(job_id)
    asset = next(a for a in job["assets"] if a["id"] == asset_id)
    path = uploads_dir(job_id) / f"{asset_id}{asset['ext']}"  # 누끼가 아니라 원본으로 확인합니다
    result, error = None, None
    try:
        result = await asyncio.to_thread(get_ai_provider().identify_character, path, job["topic"])
    except AIError as e:
        error = f"{e.message} 이름을 직접 입력해 주세요."
    except Exception:
        error = "이름 확인 중 오류가 났어요. 이름을 직접 입력해 주세요."
    job = _read(job_id)
    # 확인하는 동안 친구 순서를 바꿨을 수 있어 자리 이름이 아니라 사진으로 기록을 찾습니다
    records = ((job.get("slotIdentities") or {}).get(frame) or {}).values()
    record = next((r for r in records if r.get("assetId") == asset_id), None)
    if not record or record["status"] != "processing":
        return  # 그사이 사진을 바꿨거나 사용자가 먼저 이름을 확정했습니다
    if error:
        record.update(status="failed", error=error)
    else:
        _record_calls(job, result.pop("calls"))
        record.update(status="suggested", error=None, **result)
    if job.get("outline"):
        job["outline"]["issues"] = _issues(job)
    save(job)


def confirm_identity(job_id: str, frame: str, slot: str, name: str) -> dict:
    """친구 칸 사진의 캐릭터 이름을 확정합니다. 친구 항목의 이름과 순서는 이 값으로 정해집니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)
    if not friends.is_identify_slot(job, frame, slot):
        raise JobConflict("이 자리는 캐릭터 이름을 확인하는 친구 칸이 아니에요")
    _ensure_slot_images(job)
    image = job["slotImages"][frame].get(slot)
    if not image:
        raise JobConflict("먼저 이 칸에 사진을 넣어 주세요")
    job.setdefault("slotIdentities", {}).setdefault(frame, {})
    friends.rekey(job, frame)
    name = " ".join(name.split())
    limit = friends.name_max(job, frame)
    if not name:
        raise JobConflict("캐릭터 이름을 입력해 주세요")
    if len(name) > limit:
        raise JobConflict(f"이름은 {limit}자 이내로 입력해 주세요 (현재 {len(name)}자)")
    if name in [n for key, n in friends.confirmed(job, frame) if key != slot]:
        raise JobConflict("다른 친구 칸에서 이미 확정한 이름이에요")
    record = friends.identity(job, frame, slot) or _new_identity(image["assetId"], False)
    if record["status"] == "confirmed" and record["name"] == name:
        return job
    was_ready = friends.ready(job, frame)
    job["slotIdentities"][frame][slot] = {**record, "status": "confirmed", "name": name, "error": None}
    changed = friends.sync(job)
    _revoke_outline(job)
    # 확정 전에도 AI가 제안한 이름이 항목에 들어가 있어 목록이 안 바뀔 수 있습니다. 마지막 칸을 확정한 순간에도 다시 씁니다
    if (changed or not was_ready) and _is_ai(job) and friends.ready(job, frame):
        return _start_friends_rewrite(job, frame)
    job["outline"]["issues"] = _issues(job)
    if job.get("preview"):
        _refresh_template_preview(job)
    save(job)
    return job


def _start_friends_rewrite(job: dict, frame: str) -> dict:
    """확정한 친구로 그 카드의 관계·TMI를 다시 씁니다. 실패해도 확정한 이름은 그대로 둡니다."""
    job["outline"]["issues"] = _issues(job)

    def work(snapshot):
        return get_ai_provider().write_friends(snapshot, frame)

    def apply(current, result):
        card = _outline_card(current, frame)
        card.update(result["card"], edited=False, regenCount=card["regenCount"] + 1)
        for key in ("checkMarks", "userFields", "cleared"):
            card.pop(key, None)
        if result["research"]:
            current["research"] = result["research"]
        friends.sync(current)
        _revoke_outline(current)
        current["outline"]["issues"] = _issues(current)
        if current.get("preview"):
            _refresh_template_preview(current)

    def on_fail(current):
        current["outline"]["issues"] = _issues(current)

    return _start_ai_task(job, "friends", frame, work, apply, on_fail)


def check_slot_upload(job_id: str, frame: str, slot: str) -> None:
    """카드에서 바로 올리기 전에 검사합니다 (파일을 저장하기 전)."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)


def add_asset_to_slot(job_id: str, frame: str, slot: str, asset: dict) -> dict:
    """구성안 단계에서 카드 이미지 자리에 새 이미지를 올려 바로 넣거나 교체합니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)
    job["assets"].append(asset)
    _ensure_slot_images(job)
    return _put_slot(job, frame, slot, _slot_image(asset["id"], "original"))


def _clamp(value: float, low: float, high: float) -> float:
    return round(min(high, max(low, float(value))), 3)


def adjust_slot_image(job_id: str, frame: str, slot: str, scale: float, dx: float, dy: float) -> dict:
    """이미지 자리 안에서 크기와 위치를 조정합니다. 값은 작업 데이터(slotImages)에 저장됩니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)
    _ensure_slot_images(job)
    image = job["slotImages"][frame].get(slot)
    if not image:
        raise JobConflict("이미지를 먼저 넣어 주세요")
    adjusted = {**image, "scale": _clamp(scale, *SCALE_RANGE), "dx": _clamp(dx, *OFFSET_RANGE), "dy": _clamp(dy, *OFFSET_RANGE)}
    return _put_slot(job, frame, slot, adjusted)


def restore_slot_original(job_id: str, frame: str, slot: str) -> dict:
    """이 자리만 원본 이미지로 되돌리고 크기·위치 조정을 초기화합니다. 누끼 파일은 지우지 않습니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    _check_slot(job, frame, slot)
    _ensure_slot_images(job)
    image = job["slotImages"][frame].get(slot)
    if not image:
        raise JobConflict("이미지를 먼저 넣어 주세요")
    keep = _has_cutout(_asset(job, image["assetId"]))
    return _put_slot(job, frame, slot, _slot_image(image["assetId"], "original", None, keep))


def apply_slot_suggestions(job_id: str, frame: str | None = None, slot: str | None = None) -> dict:
    """추천을 실제로 배치합니다. frame·slot을 주면 그 자리만, 없으면 추천 전체를 적용합니다."""
    job = _require(job_id, "waiting_outline", "waiting_preview", "done")
    if not templates.is_template_job(job):
        raise JobConflict("이 작업은 카드별 이미지 선택을 써 주세요")
    _ensure_slot_images(job)
    picked = [(f, s, image) for f, slots in slot_suggestions(job).items() for s, image in slots.items()
              if (frame is None or f == frame) and (slot is None or s == slot)]
    if not picked:
        raise JobConflict("적용할 추천이 없어요")
    changed: dict[str, list[str]] = {}
    for f, s, image in picked:
        job["slotImages"][f][s] = _slot_image(image["assetId"], image["variant"])
        changed.setdefault(f, []).append(s)
    return _save_after_slots(job, *_on_slots_changed(job, changed))


def cutout_path(job_id: str, asset: dict) -> Path | None:
    return uploads_dir(job_id) / asset["cutout"]["file"] if _has_cutout(asset) else None


def _require_job(job_id: str) -> dict:
    job = load(job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def _require(job_id: str, *states: str) -> dict:
    job = _require_job(job_id)
    if job.get("aiTask"):
        raise JobConflict("AI 작업이 끝난 뒤에 다시 시도해 주세요")
    if job["state"] not in states:
        raise JobConflict(f"지금은 할 수 없는 작업이에요 (현재 상태: {job['state']})")
    return job
