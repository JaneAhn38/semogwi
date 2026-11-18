"""캐릭터 소개 card-05 새 디자인 (다음 캐릭터 예고). Claude와 외부 사이트에 접속하지 않습니다."""

import json

from app import jobs, templates
from tests.test_templates import (api, approve_all, client, clear_cooldowns, edit, fake, get, start,  # noqa: F401
                                  wait)

USE_TEMPLATES = True

NEXT = {"next_name": "하치와레", "next_hint": "노래를 좋아하는 고양이", "next_date": "12월 1일", "next_episode": "7",
        "teaser": "세모귀의 단짝이 찾아와요"}


def test_new_design_definition_and_reference_files():
    tpl = templates.TEMPLATES["character-05"]
    assert tpl["reference"] == "reference/캐릭터 소개 · 05 마무리 (새 디자인).png"
    assert (templates.TEMPLATE_DIR / tpl["reference"]).is_file()
    assert (templates.TEMPLATE_DIR / "reference/캐릭터 소개 · 05 마무리.png").is_file()  # 기존 참고 이미지는 그대로
    assert [f["key"] for f in tpl["fields"]] == list(NEXT)
    assert all(f.get("userOnly") for f in tpl["fields"]) and tpl["showSource"] is False
    texts = [e.get("text") for e in tpl["elements"]]
    assert {"다음 캐릭터도 보고 싶다면", "NEXT CHARACTER", "다음 편 예고", "팔로우하면 다음 친구를 제일 먼저 만나요!",
            "저장해 두고 다음 편도 기다려 주세요"} <= set(texts)
    fallbacks = {e["field"]: e["fallback"] for e in tpl["elements"] if e.get("fallback")}
    assert fallbacks == {"next_episode": "다음 회차", "next_name": "???", "next_hint": "다음 캐릭터는 아직 비밀이에요",
                         "next_date": "곧 공개 예정", "teaser": "다음 편에서 또 다른 귀여운 친구를 소개할게요"}
    assert next(e for e in tpl["elements"] if e.get("field") == "next_episode")["prefix"] == "No. "
    # 이전 디자인은 예전 작업용으로 남깁니다
    old = templates.TEMPLATES["character-05-v1"]
    assert old["reference"] == "reference/캐릭터 소개 · 05 마무리.png" and old["deprecated"]
    assert "character-05-v1" not in templates.body_choices("character")


def test_other_cards_and_types_are_unchanged():
    assert templates.template_set("character") == [f"character-0{i}" for i in range(1, 6)]
    for tid in ("character-01", "character-02", "character-03", "character-04", "goods-05", "collab-05", "popup-05"):
        assert templates.has_source(templates.TEMPLATES[tid]) == (templates.TEMPLATES[tid]["kind"] != "cover")


def test_demo_card_uses_default_texts_without_warnings(client):
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][4]
    assert card["template"] == "character-05" and all(v == "" for v in card["fields"].values()) and card["source"] == ""
    assert job["outline"]["issues"]["card-05"] == {"errors": [], "warnings": []}


def test_user_edits_next_character_and_preview_keeps_it(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    r = edit(client, job_id, "card-05", NEXT, role="마무리", source="")
    assert r.status_code == 200, r.text
    assert r.json()["outline"]["cards"][4]["fields"] == NEXT
    assert edit(client, job_id, "card-05", {**NEXT, "next_name": "열한글자이름입니다요!"}, role="마무리", source="").status_code == 409
    job = approve_all(client, job_id)
    spec = job["preview"]["cards"][4]["spec"]
    assert spec["template"] == "character-05" and spec["fields"] == NEXT and spec["source"] == ""
    # 다시 비우면 기본 안내 문구로 돌아갑니다 (값은 비어 있음)
    job_id2 = start(client)
    wait(client, job_id2, "waiting_outline")
    card = edit(client, job_id2, "card-05", {k: "" for k in NEXT}, role="마무리", source="").json()["outline"]["cards"][4]
    assert all(v == "" for v in card["fields"].values())


def test_ai_does_not_write_next_episode_plans(client, fake):
    rules = templates.ai_field_rules("character", templates.template_set("character"))
    assert "다음 편 정보는 사용자가 구성안에서 직접 입력" in rules and "next_name" not in rules
    schema = templates.ai_card_schema("character", templates.template_set("character"))
    assert not set(NEXT) & set(schema["properties"]["fields"]["properties"])
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][4]
    if card["template"] == "character-05":  # 가짜 AI가 값을 적어 보내도 받지 않습니다
        assert all(v == "" for v in card["fields"].values())
        assert not job["outline"]["issues"]["card-05"]["errors"]


def test_saved_jobs_with_old_wrap_card_open_in_previous_design(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = approve_all(client, job_id)
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    old = {"recommend_for": "귀여운 걸 좋아하는 분", "official_account": "@semogwi", "related_character": "하치와레"}
    raw["outline"]["cards"][4].update(template="character-05", fields=old, source="출처: 공식 계정")
    raw["templateSet"][4] = "character-05"
    raw["preview"]["cards"][4]["spec"].update(template="character-05", fields=old)
    raw["preview"]["approvalHash"] = jobs._approval_hash(raw)
    raw["outline"].pop("issues")
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    card = job["outline"]["cards"][4]
    assert card["template"] == "character-05-v1" and card["fields"] == old and job["state"] == "done"
    assert job["preview"]["cards"][4]["spec"]["template"] == "character-05-v1"
    assert not job["outline"]["issues"]["card-05"]["errors"]
