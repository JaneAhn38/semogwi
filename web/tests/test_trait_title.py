"""캐릭터 소개 3페이지(성격과 특징) 제목 편집 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import json

from app import jobs, templates
from tests.test_research import client, clear_cooldowns, fake  # noqa: F401
from tests.test_templates import api, approve_all, get, start, wait

USE_TEMPLATES = True
DEFAULT = "이런 성격이에요"


def title_field():
    return next(f for f in templates.TEMPLATES["character-03"]["fields"] if f["key"] == "page_title")


def test_title_is_a_field_with_old_text_as_fallback():
    tpl = templates.TEMPLATES["character-03"]
    field = title_field()
    assert field["type"] == "text" and not field.get("required") and not field.get("userOnly") and field["placeholder"] == DEFAULT
    title = next(e for e in tpl["elements"] if e.get("field") == "page_title")
    assert title["fallback"] == DEFAULT and "text" not in title
    assert not any(e.get("text") == DEFAULT for e in tpl["elements"])
    # 다른 페이지·유형에는 이 필드가 없음
    assert [tid for tid, t in templates.TEMPLATES.items() if any(f["key"] == "page_title" for f in t["fields"])] == ["character-03"]
    # AI에게 제목을 쓰라고 안내함
    assert "page_title (페이지 제목)" in templates.ai_field_rules("character", templates.template_set("character"))


def test_ai_title_is_kept_and_user_can_edit(client, fake):
    fake.overrides = {"card-03": {"page_title": "겁 많지만 다정해요"}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][2]
    assert card["template"] == "character-03" and card["fields"]["page_title"] == "겁 많지만 다정해요"
    for title in ("용기 내는 울보예요", ""):  # 수정, 비우기(기본 문구로 보임)
        r = api(client, job_id, "PUT", "/outline/cards/card-03", json={"role": card["role"], "fields": {**card["fields"], "page_title": title}, "source": card["source"]})
        assert r.status_code == 200, r.text
        assert r.json()["outline"]["cards"][2]["fields"]["page_title"] == title
    r = api(client, job_id, "PUT", "/outline/cards/card-03", json={"role": card["role"], "fields": {**card["fields"], "page_title": "가" * 15}, "source": card["source"]})
    assert r.status_code == 409 and "14자 이내" in r.json()["detail"]


def test_saved_jobs_without_title_open_unchanged(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    approve_all(client, job_id)
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    for fields in (raw["outline"]["cards"][2]["fields"], raw["preview"]["cards"][2]["spec"]["fields"]):
        fields.pop("page_title", None)  # 제목 필드가 생기기 전에 저장된 카드
    raw["preview"]["approvalHash"] = jobs._approval_hash(raw)
    raw["outline"].pop("issues", None)
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    assert job["state"] == "done" and job["outline"]["cards"][2]["template"] == "character-03"
    assert not job["outline"]["issues"]["card-03"]["errors"]


def test_title_moves_to_free_card_heading():
    card = {"template": "character-03", "role": "성격", "fields": templates.clean_fields(
        templates.TEMPLATES["character-03"], {"page_title": "겁 많지만 다정해요", "traits": [{"label": "공식 설정", "keyword": "울보"}]})}
    moved = templates.move_fields({"contentType": "character"}, card, "character-free")["fields"]
    assert moved["heading"] == "겁 많지만 다정해요"
    assert not any("페이지 제목" in r["label"] for r in moved["points"])
