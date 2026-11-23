"""캐릭터 소개 '친구와 TMI' 가로형 카드 (character-04): 친구 2~4명, 친구마다 이름·관계·이미지·개별 TMI."""

import json

import pytest

from app import jobs, templates
from tests.test_templates import (FRAMES, PNG, api, approve_all, client, clear_cooldowns, edit, fake, get, start,  # noqa: F401
                                  upload, wait)

USE_TEMPLATES = True

TMI_60 = "하치와레는 노래를 잘 불러서 길에서 기타를 치며 노래하는 장면이 자주 나와요. 친구들 앞에서는 늘 씩씩하고 다정해요!"[:59] + "!"


def friends(n, tmi=TMI_60):
    names = ["하치와레", "우사기", "모몽가", "쿠리만주", "시사"]
    return [{"name": names[i], "relation": "단짝 친구", "tmi": tmi} for i in range(n)]


# ---------- 템플릿 정의 ----------
def test_friends_template_definition():
    tpl = templates.TEMPLATES["character-04"]
    # 공통 TMI 입력란(tmi_items)은 없고, 친구 목록만 둡니다 (가족 카드는 2026-11-23에 없앰)
    assert [f["key"] for f in tpl["fields"]] == ["friends"]
    for field in tpl["fields"]:
        assert (field["minItems"], field["maxItems"], field["defaultItems"]) == (2, 4, 3)
        assert {s["key"]: s["max"] for s in field["fields"]} == {"name": 8, "relation": 8, "tmi": 60}
    assert [s["key"] for s in tpl["images"]] == [f"friend_image_{i}" for i in range(1, 5)]
    assert any(el["type"] == "columns" for el in tpl["elements"])
    assert not any(el.get("field") == "tmi_items" for el in tpl["elements"])
    trait = next(f for f in templates.TEMPLATES["character-03"]["fields"] if f["key"] == "traits")
    assert next(s for s in trait["fields"] if s["key"] == "description")["max"] == 60
    assert TMI_60 and len(TMI_60) == 60


@pytest.mark.parametrize("count, error", [(1, "2개 이상"), (2, None), (3, None), (4, None), (5, "4개까지")])
def test_friend_count_rules(count, error):
    tpl = templates.TEMPLATES["character-04"]
    fields = templates.clean_fields(tpl, {"friends": friends(count)})
    result = templates.check_card({"role": "친구", "fields": fields, "source": "출처: 공식"}, tpl)
    assert (error is None and not result["errors"]) or any(error in e for e in result["errors"]), result


def test_tmi_and_trait_description_limits():
    tpl = templates.TEMPLATES["character-04"]
    over = templates.clean_fields(tpl, {"friends": friends(2, TMI_60 + "요")})
    assert any("TMI: 60자 이내" in e for e in templates.check_card({"role": "친구", "fields": over, "source": "출처: 공식"}, tpl)["errors"])
    traits = templates.TEMPLATES["character-03"]
    ok = templates.clean_fields(traits, {"traits": [{"label": "공식 설정", "keyword": "울보", "description": "가" * 60}]})
    assert not templates.check_card({"role": "성격", "fields": ok, "source": "출처: 공식"}, traits)["errors"]
    long = templates.clean_fields(traits, {"traits": [{"label": "공식 설정", "keyword": "울보", "description": "가" * 61}]})
    assert any("60자 이내" in e for e in templates.check_card({"role": "성격", "fields": long, "source": "출처: 공식"}, traits)["errors"])


# ---------- 작업 흐름 ----------
def test_demo_makes_three_friends_by_default(client):
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-04" and len(card["fields"]["friends"]) == 3
    assert all(set(f) == {"name", "relation", "tmi"} for f in card["fields"]["friends"])


@pytest.mark.parametrize("count", [2, 3, 4])
def test_edit_preview_and_download_flow_for_each_count(client, count):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    r = edit(client, job_id, "card-04", {"friends": friends(count)}, role="친구")
    assert r.status_code == 200, r.text
    card = r.json()["outline"]["cards"][3]
    assert card["template"] == "character-04" and len(card["fields"]["friends"]) == count
    assert not r.json()["outline"]["issues"]["card-04"]["errors"]
    job = approve_all(client, job_id)
    spec = job["preview"]["cards"][3]["spec"]
    assert spec["template"] == "character-04" and len(spec["fields"]["friends"]) == count
    assert {f"friend_image_{i}" for i in range(1, 5)} <= set(spec["images"])


def start_with_images(client, count):
    job_id = client.post("/api/jobs/draft").json()["id"]
    ids = [upload(client, job_id) for _ in range(count)]
    assert api(client, job_id, "POST", "/start", json={"topic": "치이카와 친구들", "contentType": "character", "url": "", "mode": "demo"}).status_code == 200
    wait(client, job_id, "waiting_outline")
    return job_id, ids


def test_slots_follow_friends_when_one_is_deleted(client):
    job_id, ids = start_with_images(client, 3)
    assert edit(client, job_id, "card-04", {"friends": friends(3)}).status_code == 200
    for n, asset in enumerate(ids, 1):
        assert api(client, job_id, "PUT", f"/cards/card-04/slots/friend_image_{n}", json={"assetId": asset, "variant": "original"}).status_code == 200
    # 2번 친구(우사기)를 지움: 저장 전 번호 [0, 2]
    body = {"role": "친구", "fields": {"friends": [friends(3)[0], friends(3)[2]]}, "source": "출처: 공식 계정", "itemOrder": {"friends": [0, 2]}}
    job = api(client, job_id, "PUT", "/outline/cards/card-04", json=body).json()
    images = job["slotImages"]["card-04"]
    assert [f["name"] for f in job["outline"]["cards"][3]["fields"]["friends"]] == ["하치와레", "모몽가"]
    assert images["friend_image_1"]["assetId"] == ids[0] and images["friend_image_2"]["assetId"] == ids[2]
    assert images["friend_image_3"] is None and images["friend_image_4"] is None
    # 새 친구를 추가하면 빈 이미지 자리로 시작합니다
    body = {"role": "친구", "fields": {"friends": [friends(3)[0], friends(3)[2], friends(4)[3]]}, "source": "출처: 공식 계정", "itemOrder": {"friends": [0, 1, -1]}}
    images = api(client, job_id, "PUT", "/outline/cards/card-04", json=body).json()["slotImages"]["card-04"]
    assert images["friend_image_2"]["assetId"] == ids[2] and images["friend_image_3"] is None


def test_wrong_item_order_is_ignored(client):
    job_id, (asset,) = start_with_images(client, 1)
    assert edit(client, job_id, "card-04", {"friends": friends(3)}).status_code == 200
    api(client, job_id, "PUT", "/cards/card-04/slots/friend_image_2", json={"assetId": asset, "variant": "original"})
    body = {"role": "친구", "fields": {"friends": friends(2)}, "source": "출처: 공식 계정", "itemOrder": {"friends": [1, 1]}}
    images = api(client, job_id, "PUT", "/outline/cards/card-04", json=body).json()["slotImages"]["card-04"]
    assert images["friend_image_2"]["assetId"] == asset  # 순서가 맞지 않으면 이미지를 옮기지 않습니다


def test_suggestions_skip_slots_of_missing_friends(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    assert edit(client, job_id, "card-04", {"friends": friends(2)}).status_code == 200
    for _ in range(12):
        upload(client, job_id)
    suggested = get(client, job_id)["slotSuggestions"].get("card-04", {})
    assert set(suggested) == {"friend_image_1", "friend_image_2"}


def test_one_confirmed_friend_becomes_free_card_without_inventing(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = edit(client, job_id, "card-04", {"friends": friends(1)}).json()
    card = job["outline"]["cards"][3]
    # 인원을 채우지 않고 확인된 한 명만 자유 구성 카드로 옮깁니다
    assert card["template"] == "character-free" and card["convertedFrom"] == "character-04"
    assert "하치와레" in json.dumps(card["fields"], ensure_ascii=False) and "우사기" not in json.dumps(card["fields"], ensure_ascii=False)
    # 60자 TMI는 정보 줄(40자)에 억지로 넣거나 자르지 않고 소개 문장(60자)으로 옮깁니다
    assert card["fields"]["lead"] == TMI_60 and card["fields"]["points"] == [{"label": "하치와레", "value": "단짝 친구"}]
    assert not job["outline"]["issues"]["card-04"]["errors"]


FAMILY_TABLE = {"heading": "함께하는 사람들", "lead": "짱구 곁에는 가족과 친구들이 있어요.",
                "points": [{"label": "가족", "value": "부모님, 여동생 히마와리"}, {"label": "친구들", "value": "카스카베 방위대"}], "notes": []}


def test_user_can_pick_friends_card_and_fill_it(client):
    """AI가 표 형태 자유 구성을 골랐어도 사용자가 '친구와 TMI'를 골라 직접 입력하면 가로형으로 끝까지 나옵니다."""
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    api(client, job_id, "PUT", "/outline/cards/card-04/template", json={"template": "character-free"})
    assert edit(client, job_id, "card-04", FAMILY_TABLE, role="가족·친구").status_code == 200
    # 친구 정보가 없어도 고를 수 있고, 표의 '가족'·'친구들' 줄을 친구 이름으로 옮기지 않습니다
    job = api(client, job_id, "PUT", "/outline/cards/card-04/template", json={"template": "character-04"}).json()
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-04" and card["fields"]["friends"] == []
    assert any("꼭 필요한 항목" in e for e in job["outline"]["issues"]["card-04"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409  # 채우기 전에는 승인할 수 없습니다
    job = edit(client, job_id, "card-04", {"friends": friends(4)}, role="친구").json()
    assert job["outline"]["cards"][3]["template"] == "character-04" and job["templateSet"][3] == "character-04"
    job = approve_all(client, job_id)
    assert job["preview"]["cards"][3]["spec"]["template"] == "character-04" and len(job["preview"]["cards"][3]["spec"]["fields"]["friends"]) == 4


def test_converted_friend_card_switches_back_with_its_values(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    card = edit(client, job_id, "card-04", {"friends": friends(1)}).json()["outline"]["cards"][3]
    assert card["template"] == "character-free"
    card = api(client, job_id, "PUT", "/outline/cards/card-04/template", json={"template": "character-04"}).json()["outline"]["cards"][3]
    assert card["fields"]["friends"] == friends(1)  # 이름·관계·TMI를 그대로 되돌립니다 (새 친구는 만들지 않음)


def test_friend_names_from_research():
    from app import research
    item = {"key": "friends", "value": "철수(친구), 유리(친구), 훈이(친구), 맹구(친구)", "state": "verified", "strict": False}
    assert research.friend_names([item]) == ["철수", "유리", "훈이", "맹구"]
    assert research.friend_names([{**item, "value": "카스카베 방위대"}]) == ["카스카베 방위대"]
    assert research.friend_names([{**item, "state": "unverified"}]) == []
    text = research.checklist_text("character")
    assert "그룹 이름(예: OO 방위대)은 캐릭터로 세지 않는다" in text and "'이름(관계), 이름(관계)'" in text
    assert "- friends: 친구 캐릭터" in text and "가족은 넣지 않는다" in text and "- family:" not in text


class FriendsFake:
    """조사 결과(friends 항목)를 정해 주고, 처음에는 AI가 card-04에 표 형태 자유 구성을 고르는 상황을 만듭니다."""

    def __init__(self, base, friends_value):
        self.base, self.friends_value, self.rewrites = base, friends_value, []

    def __call__(self, prompt, system, schema, **kwargs):
        run = self.base(prompt, system, schema, **kwargs)
        data = run.structured
        if "people" in schema["properties"]:
            return run  # 캐릭터별 2차 조사는 기본 가짜 응답(찾지 못함)
        if "sources" in schema["properties"]:
            data["items"] = [
                {"key": "official_name", "value": "짱구", "quote": "짱구", "sourceIds": ["s1"]},
                {"key": "personality", "value": "마이페이스", "quote": "마이페이스", "sourceIds": ["s1"]},
                {"key": "friends", "value": self.friends_value, "quote": self.friends_value, "sourceIds": ["s1"]},
            ]
        elif "status" in schema["properties"]:
            # 구성안 단계: 처음에는 card-04에 표 형태 자유 구성을 고릅니다
            for card in data["cards"]:
                if card["frame"] == "card-04":
                    card.update(template="character-free", fields=FAMILY_TABLE)
        elif "cards" in data:
            self.rewrites.append(prompt)
            for card in data["cards"]:
                if card["frame"] == "card-04":
                    card.update(template="character-04", fields={"friends": [
                        {"name": "철수", "relation": "친구", "tmi": ""}, {"name": "유리", "relation": "친구", "tmi": ""}]})
        return run


def test_ai_must_use_friends_card_when_two_friends_are_confirmed(client, fake, monkeypatch):
    from app import claude_cli
    spy = FriendsFake(fake, "철수(친구), 유리(친구)")
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id = start(client, mode="ai", topic="짱구")
    job = wait(client, job_id, "waiting_outline")
    assert len(spy.rewrites) == 1 and "친구 캐릭터 2명(철수, 유리)" in spy.rewrites[0] and "character-04" in spy.rewrites[0]
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-04" and [f["name"] for f in card["fields"]["friends"]] == ["철수", "유리"]


def test_ai_keeps_free_card_and_explains_when_only_a_group_is_confirmed(client, fake, monkeypatch):
    from app import claude_cli
    spy = FriendsFake(fake, "카스카베 방위대")
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id = start(client, mode="ai", topic="짱구")
    job = wait(client, job_id, "waiting_outline")
    assert spy.rewrites == []  # 친구를 채우라고 요구하지 않습니다 (지어내지 않게)
    assert job["outline"]["cards"][3]["template"] == "character-free"
    warnings = job["outline"]["issues"]["card-04"]["warnings"]
    assert any("2명 미만" in w and "지어내지 않았어요" in w and "'친구와 TMI'를 고르면" in w for w in warnings)


def test_ai_rules_forbid_padding_friends():
    rules = templates.ai_field_rules("character", templates.template_set("character"))
    assert "2~4개" in rules and "친구 캐릭터 2개 이상일 때만" in rules and "가족 캐릭터 2개" not in rules
    from app import ai_rules
    assert "인원을 채우려고" in ai_rules.TEMPLATE_TYPE_RULES["character"]


def test_ai_card_with_one_friend_is_converted(client, fake):
    fake.overrides = {"card-04": {"friends": [{"name": "하치와레", "relation": "단짝", "tmi": ""}]}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-free" and card["convertedFrom"] == "character-04"
    assert not job["outline"]["issues"]["card-04"]["errors"]


# ---------- 예전 데이터 ----------
def test_saved_jobs_with_shared_tmi_open_in_previous_design(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = approve_all(client, job_id)
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    old_fields = {"friends": [{"name": "하치와레", "relation": "단짝"}, {"name": "우사기", "relation": "친구"}], "tmi_items": ["공통 사실 하나", "공통 사실 둘"]}
    raw["outline"]["cards"][3]["fields"] = old_fields
    raw["preview"]["cards"][3]["spec"]["fields"] = old_fields
    raw["preview"]["approvalHash"] = jobs._approval_hash(raw)
    raw["outline"].pop("issues")
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    job = get(client, job_id)
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-04-v1" and card["fields"] == old_fields  # 내용을 옮기거나 버리지 않습니다
    assert job["templateSet"][3] == "character-04-v1" and job["preview"]["cards"][3]["spec"]["template"] == "character-04-v1"
    assert job["state"] == "done" and job["preview"]["approvalHash"] == jobs._approval_hash(job)
    assert not job["outline"]["issues"]["card-04"]["errors"]
    # 새 가로형으로 바꾸면 이름·관계는 옮기고, 공통 TMI는 특정 친구에게 붙이지 않습니다
    moved = api(client, job_id, "PUT", "/outline/cards/card-04/template", json={"template": "character-04"}).json()["outline"]["cards"][3]
    assert moved["template"] == "character-04"
    assert moved["fields"]["friends"] == [{"name": "하치와레", "relation": "단짝", "tmi": ""}, {"name": "우사기", "relation": "친구", "tmi": ""}]
