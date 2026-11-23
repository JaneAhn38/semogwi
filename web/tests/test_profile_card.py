"""캐릭터 소개 2페이지(프로필) 동적 항목 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import json

from app import jobs, research, templates
from app.ai_provider import verify_sources
from app.claude_cli import CliRun
from tests.test_research import OFFICIAL, WIKI, client, clear_cooldowns, fake  # noqa: F401
from tests.test_templates import api, approve_all, get, start, wait

USE_TEMPLATES = True
NAMU = "https://namu.wiki/w/%ED%94%BC%EC%B9%B4%EC%B8%84"


def items_with(raw, sources):
    return research.verify_items("character", raw, sources)


def official_sources():
    return verify_sources([{"id": "s1", "url": OFFICIAL, "kind": "official", "title": "공식"},
                           {"id": "n1", "url": NAMU, "kind": "secondary", "title": "나무위키"}],
                          CliRun(fetches=[{"url": OFFICIAL, "code": 200}, {"url": NAMU, "code": 200}]), "character")


# ---------- 후보 고르기: 근거가 확인된 값만, 자르거나 지어내지 않음 ----------
def test_profile_candidates_use_only_confirmed_values():
    sources = official_sources()
    items = items_with([
        {"key": "profile_extra", "value": "도감 번호: 0025, 타입: 전기, 분류: 쥐포켓몬", "quote": "q", "sourceIds": ["s1"]},
        {"key": "birthday", "value": "5월 5일", "quote": "q", "sourceIds": ["n1"]},  # 나무위키(2차 자료)도 참고 근거로 씀
        {"key": "favorite", "value": "케첩", "quote": "q", "sourceIds": ["s1"]},
        {"key": "creator", "value": "아주 긴 제작사 이름이 들어가서 칸을 넘는 값", "quote": "q", "sourceIds": ["s1"]},  # 16자 초과 → 자르지 않고 뺌
    ], sources)
    rows = research.profile_candidates(items)
    assert [(r["label"], r["value"]) for r in rows] == [("도감 번호", "0025"), ("타입", "전기"), ("분류", "쥐포켓몬"), ("생일", "5월 5일"), ("좋아하는 것", "케첩")]
    assert {tuple(r["sourceIds"]) for r in rows} == {("s1",), ("n1",)}
    assert research.profile_candidates([]) == []


def test_profile_row_state_matches_research_values():
    sources = official_sources()
    items = items_with([{"key": "profile_extra", "value": "타입: 전기", "quote": "q", "sourceIds": ["s1"]}], sources)
    keys = ["birthday", "profile_extra"]
    assert research.profile_row_state({"label": "타입", "value": "전기"}, items, keys) == "verified"
    assert research.profile_row_state({"label": "키", "value": "40cm"}, items, keys) == "unverified"  # 조사에 없는 값


# ---------- 구성안: 서버 보충과 검사 ----------
def test_empty_profile_rows_are_filled_from_research_only(client, fake):
    fake.items = [{"key": "profile_extra", "value": "도감 번호: 0025, 타입: 전기", "quote": "q", "sourceIds": ["s1"]},
                  {"key": "personality", "value": "활발함", "quote": "q", "sourceIds": ["s1"]}]
    fake.overrides = {"card-02": {"profile_rows": [], "profile_intro": ""}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][1]
    assert card["template"] == "character-02"
    assert card["fields"]["profile_rows"] == [{"label": "도감 번호", "value": "0025"}, {"label": "타입", "value": "전기"}]
    assert "s1" in card["sourceIds"]
    states = job["outline"]["fieldStates"]["card-02"]
    assert states["profile_rows.0"] == "verified" and states["profile_rows.1"] == "verified"
    assert not any("프로필" in w or "도감" in w for w in job["outline"]["issues"]["card-02"]["warnings"])


def test_ai_rows_are_kept_and_unconfirmed_rows_warn(client, fake):
    fake.items = [{"key": "profile_extra", "value": "타입: 전기", "quote": "q", "sourceIds": ["s1"]}]
    fake.overrides = {"card-02": {"profile_rows": [{"label": "타입", "value": "전기"}, {"label": "키", "value": "40cm"}]}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][1]
    assert card["fields"]["profile_rows"] == [{"label": "타입", "value": "전기"}, {"label": "키", "value": "40cm"}]  # 덮어쓰지 않음
    issue = job["outline"]["issues"]["card-02"]
    assert any("근거를 확인하지 못한 정보예요: 키" in w for w in issue["warnings"]) and not any("타입" in w for w in issue["warnings"])
    assert not issue["errors"]  # 캐릭터 소개는 경고로 알림 (승인은 막지 않음)


def test_user_can_add_edit_and_remove_profile_rows(client, fake):
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][1]
    base = {**card["fields"], "character_name": "피카츄", "profile_intro": ""}
    for rows in ([], [{"label": "타입", "value": "전기"}], [{"label": "타입", "value": "전기"}, {"label": "분류", "value": "쥐포켓몬"},
                                                            {"label": "도감 번호", "value": "0025"}]):
        r = api(client, job_id, "PUT", "/outline/cards/card-02", json={"role": card["role"], "fields": {**base, "profile_rows": rows}, "source": card["source"]})
        assert r.status_code == 200, r.text
        assert r.json()["outline"]["cards"][1]["fields"]["profile_rows"] == rows
    r = api(client, job_id, "PUT", "/outline/cards/card-02",
            json={"role": card["role"], "fields": {**base, "profile_rows": [{"label": "타입", "value": "전기"}] * 4}, "source": card["source"]})
    assert r.status_code == 409 and "3개까지" in r.json()["detail"]


def test_profile_rows_move_to_free_card_unchanged():
    field = next(f for f in templates.TEMPLATES["character-02"]["fields"] if f["key"] == "profile_rows")
    rows = [{"label": "타입", "value": "전기"}, {"label": "분류", "value": "쥐포켓몬"}]
    assert templates._rows_of(field, rows) == rows


# ---------- 예전 카드 ----------
def test_saved_jobs_with_old_profile_card_open_in_previous_design(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = approve_all(client, job_id)
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    old = {"character_name": "치이카와", "birthday": "", "favorite_things": "", "creator": "나가노", "feature_tags": ["소심함"],
           "debut_year": "", "debut_work": "", "profile_no": ""}
    raw["outline"]["cards"][1].update(template="character-02", fields=old, source="출처: 공식 계정")
    raw["templateSet"][1] = "character-02"
    raw["preview"]["cards"][1]["spec"].update(template="character-02", fields=old)
    raw["preview"]["approvalHash"] = jobs._approval_hash(raw)
    raw["outline"].pop("issues")
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    card = job["outline"]["cards"][1]
    assert card["template"] == "character-02-v1" and card["fields"] == old and job["state"] == "done"  # 내용을 옮기거나 버리지 않음
    assert job["preview"]["cards"][1]["spec"]["template"] == "character-02-v1"
    assert not job["outline"]["issues"]["card-02"]["errors"]


# ---------- 다른 템플릿에 영향 없음 ----------
def test_profile_element_is_only_in_character_02():
    users = sorted(tid for tid, tpl in templates.TEMPLATES.items() if any(e["type"] == "profile" for e in tpl["elements"]))
    assert users == ["character-02"]
    listed = sorted(tid for tid, tpl in templates.TEMPLATES.items() for f in tpl["fields"] if f.get("editor") == "list" or f.get("verifyItems"))
    assert listed == ["character-02"]
    friends = next(f for f in templates.TEMPLATES["character-04"]["fields"] if f["key"] == "friends")
    assert friends["minItems"] == 2 and "editor" not in friends and "unit" not in friends  # 친구 편집기는 그대로
