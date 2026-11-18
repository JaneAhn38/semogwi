"""조사 자료 보관함(저장된 자료 사용 / 새로 조사하기)과 친구·가족 카테고리 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import json

import pytest

from app import claude_cli, jobs, research, research_library, templates
from app.claude_cli import CliRun
from tests.test_templates import FRAMES, api, approve_all, client, clear_cooldowns, edit, fake, get, start, wait  # noqa: F401

USE_TEMPLATES = True

PEOPLE_ITEMS = [
    {"key": "official_name", "value": "짱구", "quote": "짱구", "sourceIds": ["s1"]},
    {"key": "personality", "value": "마이페이스", "quote": "마이페이스", "sourceIds": ["s1"]},
    {"key": "friends", "value": "철수(유치원 친구), 유리(유치원 친구), 훈이(유치원 친구), 맹구(유치원 친구)", "quote": "친구들", "sourceIds": ["s1"]},
    {"key": "family", "value": "히로시(아빠), 미사에(엄마), 히마와리(여동생), 시로(반려견)", "quote": "가족", "sourceIds": ["s1"]},
    {"key": "tmi", "value": "철수: 공부를 잘해요 / 시로: 짱구가 데려온 강아지예요", "quote": "tmi", "sourceIds": ["s1"]},
]


PEOPLE_PAGE = "https://ko.wikipedia.org/wiki/등장인물_목록"
FRIEND_TMI = [
    {"name": "철수", "tmi": "공부를 잘하고 엘리트를 꿈꾸는 모범생이에요.", "quote": "철수는 성적이 우수한 모범생", "sourceIds": ["p1"]},
    {"name": "유리", "tmi": "소꿉놀이를 좋아하고 리얼한 설정을 고집해요.", "quote": "유리는 소꿉놀이를 즐긴다", "sourceIds": ["p1"]},
    {"name": "훈이", "tmi": "겁이 많고 잘 우는 편이에요.", "quote": "훈이는 울보", "sourceIds": ["p1"]},
    {"name": "맹구", "tmi": "돌을 모으는 것이 취미예요.", "quote": "맹구는 돌 수집이 취미", "sourceIds": ["p1"]},
]


class PeopleFake:
    """조사 결과에 친구·가족 항목을 넣어 주는 가짜 AI. card4에 넣을 card-04 값을 정할 수 있습니다."""

    def __init__(self, base, card4=None, rewrite4=None, items=None, people=None, people_error=None):
        self.base, self.card4, self.rewrite4, self.kinds = base, card4, rewrite4, []
        self.items = PEOPLE_ITEMS if items is None else items
        self.people, self.people_error, self.prompts = people or [], people_error, {}

    def __call__(self, prompt, system, schema, **kwargs):
        props = schema["properties"]
        if "people" in props:
            # 2차 캐릭터별 조사: 등장인물 페이지(p1)를 읽었다고 가정합니다
            self.kinds.append(("people", tuple(kwargs.get("tools") or ())))
            self.prompts.setdefault("people", prompt)  # 1회차 지시문
            self.prompts.setdefault("rounds", []).append(prompt)
            if self.people_error:
                raise claude_cli.AIError("timeout", self.people_error)
            run = CliRun(model="fake", turns=1)
            run.searches = [{"query": "짱구 등장인물", "results": [{"title": "등장인물", "url": PEOPLE_PAGE}]}]
            run.fetches = [{"url": PEOPLE_PAGE, "code": 200}]
            run.structured = {"sources": [{"id": "p1", "title": "등장인물 목록", "url": PEOPLE_PAGE, "kind": "secondary"}],
                              "people": self.people, "missing": []}
            return run
        run = self.base(prompt, system, schema, **kwargs)
        data = run.structured
        kind = "research" if "sources" in props else "compose" if "status" in props else "classify" if "contentType" in props else "rewrite"
        self.kinds.append((kind, tuple(kwargs.get("tools") or ())))
        if kind == "research":
            data["items"] = self.items
        if kind in ("research", "compose") and self.card4 is not None:
            for card in data["cards"]:
                if card["frame"] == "card-04":
                    card.update(template="character-04", fields=self.card4)
        if kind == "rewrite" and self.rewrite4 is not None:
            for card in data["cards"]:
                if card["frame"] == "card-04":
                    card.update(template="character-04", fields=self.rewrite4)
        return run


@pytest.fixture(autouse=True)
def separate_library(tmp_path, monkeypatch):
    """테스트마다 빈 보관함을 씁니다."""
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")


@pytest.fixture
def people_fake(fake, monkeypatch):
    spy = PeopleFake(fake)
    monkeypatch.setattr(claude_cli, "run", spy)
    return spy


def start_ai(client, topic="짱구", content_type="character", **extra):
    job_id = client.post("/api/jobs/draft").json()["id"]
    body = {"topic": topic, "contentType": content_type, "url": "", "mode": "ai", **extra}
    r = api(client, job_id, "POST", "/start", json=body)
    return job_id, r


def library(client, topic="짱구", content_type="character"):
    return client.get("/api/research-library", params={"topic": topic, "contentType": content_type}).json()["versions"]


# ---------- 조사 항목: 친구와 가족 분리 ----------
def test_people_are_split_into_friends_and_family():
    items = [{**i, "state": "verified", "strict": False} for i in PEOPLE_ITEMS]
    people = research.people_of(items)
    assert [p["name"] for p in people["friends"]] == ["철수", "유리", "훈이", "맹구"]
    assert [p["name"] for p in people["family"]] == ["히로시", "미사에", "히마와리", "시로"]
    assert people["family"][3]["relation"] == "반려견"  # 반려동물은 가족
    assert people["friends"][0]["tmi"] == "공부를 잘해요" and people["family"][3]["tmi"] == "짱구가 데려온 강아지예요"
    assert people["friends"][1]["tmi"] == ""  # 그 캐릭터 이름으로 적힌 TMI만 붙입니다
    unverified = [{**i, "state": "unverified", "strict": False} for i in PEOPLE_ITEMS]
    assert research.people_of(unverified) == {"friends": [], "family": []}
    keys = research.keys_of("character")
    assert {"official_name", "personality", "friends", "family", "tmi"} <= set(keys)


# ---------- 보관함 ----------
def test_new_research_is_saved_as_a_version_with_date_and_sources(client, people_fake):
    assert library(client) == []
    job_id, r = start_ai(client)
    assert r.status_code == 200
    job = wait(client, job_id, "waiting_outline")
    info = job["researchVersion"]
    assert info["source"] == "new" and info["number"] == 1 and info["researchedAt"]
    versions = library(client)
    assert len(versions) == 1 and versions[0]["id"] == info["id"] and versions[0]["sourceCount"] >= 1
    assert versions[0]["people"]["friends"] == ["철수", "유리", "훈이", "맹구"] and versions[0]["people"]["family"][-1] == "시로"
    detail = client.get(f"/api/research-library/{info['id']}").json()
    assert detail["researchedAt"] == info["researchedAt"] and detail["sources"][0]["url"].startswith("https://")
    assert {i["key"] for i in detail["research"]["items"]} >= {"friends", "family", "tmi"}
    # 같은 주제의 다른 표기도 같은 주제로 봅니다 (공백·대소문자 무시)
    assert len(library(client, topic=" 짱 구 ")) == 1


def test_saved_research_makes_new_outline_without_web_research(client, people_fake):
    job_id, _ = start_ai(client)
    first = wait(client, job_id, "waiting_outline")
    version_id = first["researchVersion"]["id"]
    people_fake.kinds.clear()

    job_id2, r = start_ai(client, researchMode="saved", researchVersion=version_id)
    assert r.status_code == 200, r.text
    job = wait(client, job_id2, "waiting_outline")
    # 새 조사(웹 도구) 호출 없이 구성안만 새로 씁니다
    assert people_fake.kinds and all(kind != "research" and not tools for kind, tools in people_fake.kinds)
    assert ("compose", ()) in people_fake.kinds
    assert job["researchVersion"] == {"id": version_id, "number": 1, "researchedAt": first["researchVersion"]["researchedAt"], "source": "saved"}
    assert job["research"]["fromLibrary"]["id"] == version_id and not job["research"]["searchPerformed"]
    assert len(job["outline"]["cards"]) == 5 and not any(i["errors"] for i in job["outline"]["issues"].values())
    assert job["research"]["people"]["family"][0]["name"] == "히로시"
    assert len(library(client)) == 1  # 저장된 자료를 쓴 작업은 새 버전을 만들지 않습니다


def test_new_research_keeps_previous_versions(client, people_fake):
    job_id, _ = start_ai(client)
    first = wait(client, job_id, "waiting_outline")["researchVersion"]
    before = research_library._path(first["id"]).read_text(encoding="utf-8")
    job_id2, _ = start_ai(client, researchMode="new")
    second = wait(client, job_id2, "waiting_outline")["researchVersion"]
    assert second["number"] == 2 and second["id"] != first["id"]
    assert research_library._path(first["id"]).read_text(encoding="utf-8") == before  # 덮어쓰지 않음
    assert [v["number"] for v in library(client)] == [2, 1]  # 최근 버전부터


def test_saved_mode_needs_a_matching_version(client, people_fake):
    job_id, r = start_ai(client, researchMode="saved", researchVersion="0" * 32)
    assert r.status_code == 409 and "새로 조사하기" in r.json()["detail"]
    other, _ = start_ai(client, topic="치이카와")
    version_id = wait(client, other, "waiting_outline")["researchVersion"]["id"]
    _, r = start_ai(client, topic="짱구", researchMode="saved", researchVersion=version_id)
    assert r.status_code == 409 and "주제" in r.json()["detail"]
    draft = client.post("/api/jobs/draft").json()["id"]
    r = api(client, draft, "POST", "/start", json={"topic": "치이카와", "contentType": "character", "url": "", "mode": "demo",
                                                    "researchMode": "saved", "researchVersion": version_id})
    assert r.status_code == 409 and "실제 AI" in r.json()["detail"]


def test_time_sensitive_types_warn_saved_data_may_be_old(client, people_fake):
    job_id, _ = start_ai(client, topic="세모귀 키링 발매", content_type="goods")
    wait(client, job_id, "waiting_outline", "waiting_material")
    versions = library(client, topic="세모귀 키링 발매", content_type="goods")
    if versions:  # 구성안까지 나온 경우에만 저장됩니다
        assert versions[0]["timeSensitive"] and "새로 조사하기" in versions[0]["staleNote"]
    character = research_library._summary({"id": "x", "topic": "t", "contentType": "character", "createdAt": "2026-01-01T00:00:00",
                                           "researchedAt": "2026-01-01", "research": {"sources": []}})
    goods = research_library._summary({"id": "x", "topic": "t", "contentType": "goods", "createdAt": "2026-01-01T00:00:00",
                                       "researchedAt": "2026-01-01", "research": {"sources": []}})
    assert character["staleNote"] == "" and "2026-01-01 조사 자료" in goods["staleNote"] and "일 지남" in goods["staleNote"]


def test_user_notes_are_added_to_saved_research_as_user_material(client, people_fake):
    job_id, _ = start_ai(client)
    version_id = wait(client, job_id, "waiting_outline")["researchVersion"]["id"]
    job_id2, _ = start_ai(client, researchMode="saved", researchVersion=version_id, notes="짱구는 초코비를 좋아해요 (공식 홈페이지 확인)")
    job = wait(client, job_id2, "waiting_outline")
    user = [s for s in job["research"]["sources"] if s["id"] == research.USER_NOTES_ID]
    assert user and user[0]["verification"] == "user_provided"
    stored = json.loads(research_library._path(version_id).read_text(encoding="utf-8"))
    assert not any(s["id"] == research.USER_NOTES_ID for s in stored["research"]["sources"])  # 저장된 자료는 바뀌지 않음


# ---------- 친구·가족 카테고리 ----------
FRIENDS = [{"name": "철수", "relation": "유치원 친구", "tmi": "공부를 잘해요"}, {"name": "유리", "relation": "유치원 친구", "tmi": ""}]
FAMILY = [{"name": "히로시", "relation": "아빠", "tmi": ""}, {"name": "미사에", "relation": "엄마", "tmi": ""}, {"name": "시로", "relation": "반려견", "tmi": ""}]


def test_category_switch_keeps_both_lists_and_their_images(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = edit(client, job_id, "card-04", {"category": "friends", "friends": FRIENDS, "family": FAMILY}, role="친구").json()
    card = job["outline"]["cards"][3]
    assert card["fields"]["category"] == "friends" and not job["outline"]["issues"]["card-04"]["errors"]
    # 가족으로 바꿔도 친구 목록은 지워지지 않습니다
    job = edit(client, job_id, "card-04", {"category": "family", "friends": FRIENDS, "family": FAMILY}, role="가족").json()
    card = job["outline"]["cards"][3]
    assert card["fields"]["category"] == "family" and card["fields"]["friends"] == FRIENDS and card["fields"]["family"] == FAMILY
    assert not job["outline"]["issues"]["card-04"]["errors"]
    tpl = templates.TEMPLATES["character-04"]
    shown = [s["key"] for s in templates.active_slots(job, "card-04")]
    assert shown == ["family_image_1", "family_image_2", "family_image_3"]  # 가족 이미지 자리만 보입니다
    assert templates.condition_met(tpl, card["fields"], "category=family") and not templates.condition_met(tpl, card["fields"], "category=friends")
    job = approve_all(client, job_id)
    spec = job["preview"]["cards"][3]["spec"]
    assert spec["template"] == "character-04" and spec["fields"]["category"] == "family" and len(spec["fields"]["family"]) == 3
    assert spec["fields"]["friends"] == FRIENDS


def test_hidden_list_is_not_required(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    job = edit(client, job_id, "card-04", {"category": "family", "friends": [], "family": FAMILY}).json()
    assert not job["outline"]["issues"]["card-04"]["errors"]
    r = edit(client, job_id, "card-04", {"category": "friends", "friends": FRIENDS[:1], "family": FAMILY})
    card = r.json()["outline"]["cards"][3]
    # 친구가 1명뿐이면 지어내지 않고, 채워진 가족 카테고리로 바꿉니다
    assert card["template"] == "character-04" and card["fields"]["category"] == "family"


def test_old_cards_without_category_show_friends(client):
    tpl = templates.TEMPLATES["character-04"]
    old = {"friends": FRIENDS}
    assert templates.condition_met(tpl, old, "category=friends")
    assert not templates.check_card({"role": "친구", "fields": old, "source": "출처: 공식"}, tpl)["errors"]
    assert templates.clean_fields(tpl, old)["category"] == "friends"


def test_mixed_friends_and_family_are_flagged_and_rewritten(client, fake, monkeypatch):
    mixed = {"category": "friends", "friends": [FRIENDS[0], {"name": "히로시", "relation": "아빠", "tmi": ""}], "family": []}
    fixed = {"category": "family", "friends": FRIENDS, "family": FAMILY}
    spy = PeopleFake(fake, card4=mixed, rewrite4=fixed)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    assert ("rewrite", ()) in spy.kinds  # 섞인 카드는 한 번 다시 쓰게 합니다
    card = job["outline"]["cards"][3]
    # 조사로 확인된 가족(히마와리)은 4명까지 더해 채웁니다
    assert card["fields"]["category"] == "family" and [p["name"] for p in card["fields"]["family"]] == ["히로시", "미사에", "시로", "히마와리"]
    assert not any("섞지 않아요" in w for w in job["outline"]["issues"]["card-04"]["warnings"])
    # 사용자가 섞어 넣으면 경고합니다
    job = edit(client, job_id, "card-04", mixed, role="친구").json()
    assert any("가족 캐릭터로 조사된 히로시" in w for w in job["outline"]["issues"]["card-04"]["warnings"])


def test_ai_picks_family_when_only_family_is_confirmed(client, fake, monkeypatch):
    only_family = [i for i in PEOPLE_ITEMS if i["key"] != "friends"]
    spy = PeopleFake(fake, card4={"category": "friends", "friends": [], "family": FAMILY}, items=only_family)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    card = job["outline"]["cards"][3]
    assert card["template"] == "character-04" and card["fields"]["category"] == "family"
    assert job["research"]["people"]["friends"] == []


# ---------- 캐릭터별 2차 조사 (친구·가족 TMI) ----------
EMPTY_FRIENDS = {"category": "friends", "friends": [{"name": n, "relation": "방범대 멤버", "tmi": ""} for n in ("철수", "유리", "훈이", "맹구")], "family": []}


def test_tmi_problem_rules():
    assert research.tmi_problem("철수", "방범대 멤버", "떡잎마을 방범대 멤버예요", group_words=("떡잎마을", "방범대"))
    assert research.tmi_problem("철수", "친구", "짱구의 친구예요")
    assert research.tmi_problem("철수", "친구", "가" * 61) == "60자 초과"
    seen = {research._norm("겁이 많아요")}
    assert research.tmi_problem("훈이", "친구", "겁이 많아요", seen) == "다른 캐릭터와 같은 내용"
    assert research.tmi_problem("맹구", "친구", "돌을 모으는 것이 취미예요.") == ""
    assert research.tmi_problem("훈이", "친구", "겁이 많고 잘 우는 편이에요.") == ""


def test_second_stage_finds_tmi_per_character_and_fills_the_card(client, fake, monkeypatch):
    spy = PeopleFake(fake, card4=EMPTY_FRIENDS, people=FRIEND_TMI)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    kinds = [k for k, _ in spy.kinds]
    assert kinds.index("research") < kinds.index("people")  # 1차 조사에서 확인된 캐릭터로 2차 조사
    assert ("people", ("WebSearch", "WebFetch")) in spy.kinds
    prompt = spy.prompts["people"]
    assert "철수 (친구, 유치원 친구)" in prompt and "시로 (가족, 반려견)" in prompt  # 친구·가족 각각을 조사
    detail = job["research"]["peopleResearch"]
    assert [p["name"] for p in detail["people"]] == ["철수", "유리", "훈이", "맹구"] and detail["queries"][0] == "짱구 등장인물"
    assert all(p["sourceIds"] == ["p1"] and p["quote"] for p in detail["people"])
    assert any(s["id"] == "p1" and s["verification"] == "fetched" for s in job["research"]["sources"])
    assert any("훈이(친구)" not in f["text"] and "훈이" in f["text"] and "TMI" in f["text"] for f in job["research"]["facts"])
    tmi_item = next(i for i in job["research"]["items"] if i["key"] == "tmi")
    assert tmi_item["state"] == "secondary" and "맹구: 돌을 모으는 것이 취미예요." in tmi_item["value"]
    # 조사 결과(캐릭터별) → 구성안 카드
    card = job["outline"]["cards"][3]
    assert [f["tmi"] for f in card["fields"]["friends"]] == [p["tmi"] for p in FRIEND_TMI]
    assert "p1" in card["sourceIds"]
    people = job["research"]["people"]["friends"]
    assert people[0]["tmi"] == FRIEND_TMI[0]["tmi"] and people[0]["sourceIds"] == ["p1"]
    assert not any("TMI를 확인하지 못한" in w for w in job["outline"]["issues"]["card-04"]["warnings"])


def test_second_stage_rejects_relation_repeats_duplicates_and_unread_sources(client, fake, monkeypatch):
    weak = [
        {"name": "철수", "tmi": "떡잎마을 방범대 멤버예요.", "quote": "방범대", "sourceIds": ["p1"]},
        {"name": "유리", "tmi": "소꿉놀이를 좋아해요.", "quote": "소꿉놀이", "sourceIds": ["p1"]},
        {"name": "훈이", "tmi": "소꿉놀이를 좋아해요.", "quote": "소꿉놀이", "sourceIds": ["p1"]},
        {"name": "맹구", "tmi": "돌을 모아요.", "quote": "돌", "sourceIds": ["p9"]},
        {"name": "없는캐릭터", "tmi": "지어낸 캐릭터예요.", "quote": "", "sourceIds": ["p1"]},
    ]
    spy = PeopleFake(fake, card4={**EMPTY_FRIENDS, "friends": [{**f, "tmi": "떡잎마을 방범대 멤버예요"} for f in EMPTY_FRIENDS["friends"]]}, people=weak)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    detail = job["research"]["peopleResearch"]
    assert [p["name"] for p in detail["people"]] == ["유리"]
    reasons = {r["name"]: r["reason"] for r in detail["rejected"]}
    assert reasons == {"철수": "관계·소속만 반복", "훈이": "다른 캐릭터와 같은 내용", "맹구": "읽은 페이지에서 확인되지 않음"}
    assert set(detail["missing"]) == {"철수", "훈이", "맹구", "히로시", "미사에", "히마와리", "시로"}
    assert any("출처에서 TMI를 찾지 못한 캐릭터" in m for m in job["research"]["missing"])
    # 카드: AI가 관계만 반복해 쓴 TMI는 지우고, 확인된 TMI만 넣습니다 (없는 내용은 만들지 않음)
    tmis = {f["name"]: f["tmi"] for f in job["outline"]["cards"][3]["fields"]["friends"]}
    assert tmis == {"철수": "", "유리": "소꿉놀이를 좋아해요.", "훈이": "", "맹구": ""}
    warnings = job["outline"]["issues"]["card-04"]["warnings"]
    assert any("TMI를 확인하지 못한 캐릭터: 철수, 훈이, 맹구" in w for w in warnings)


def test_second_stage_discovers_friends_missing_from_first_research(client, fake, monkeypatch):
    """1차 조사에서 친구 이름을 못 찾았으면 2차 조사가 등장인물 페이지에서 친구를 찾고 TMI까지 채웁니다 (출처가 있는 캐릭터만)."""
    only_family = [i for i in PEOPLE_ITEMS if i["key"] != "friends"]
    found = [{**p, "category": "friends", "relation": "유치원 친구"} for p in FRIEND_TMI] + [
        {"name": "떡잎마을 방범대", "category": "friends", "relation": "친구 모임", "tmi": "", "quote": "", "sourceIds": ["p1"]},
        {"name": "수지", "category": "friends", "relation": "친구", "tmi": "", "quote": "", "sourceIds": ["p9"]},  # 읽지 않은 출처
    ]
    items = only_family + [{"key": "relations", "value": "떡잎마을 방범대", "quote": "방범대", "sourceIds": ["s1"]}]
    spy = PeopleFake(fake, card4={"category": "family", "friends": [], "family": FAMILY}, items=items, people=found)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    assert "중심 캐릭터의 친구(friends) 4명까지" in spy.prompts["people"]
    detail = job["research"]["peopleResearch"]
    assert detail["discovered"]["friends"] == ["철수", "유리", "훈이", "맹구"]  # 그룹 이름·읽지 않은 출처의 캐릭터는 제외
    friends_item = next(i for i in job["research"]["items"] if i["key"] == "friends")
    assert friends_item["value"].startswith("철수(유치원 친구), 유리(유치원 친구)") and friends_item["sourceIds"] == ["p1"]
    people = job["research"]["people"]
    assert [p["name"] for p in people["friends"]] == ["철수", "유리", "훈이", "맹구"] and people["friends"][3]["tmi"] == FRIEND_TMI[3]["tmi"]
    card = job["outline"]["cards"][3]["fields"]
    assert [f["tmi"] for f in card["friends"]] == [p["tmi"] for p in FRIEND_TMI]  # 카드의 친구 목록도 조사 결과로 채움
    assert card["category"] == "family" and [f["name"] for f in card["family"]] == ["히로시", "미사에", "시로", "히마와리"]


def test_categories_with_two_people_still_look_for_more(client, fake, monkeypatch):
    """1차 조사에서 친구가 2명뿐이어도 4명이 되도록 더 찾습니다."""
    two_friends = [i if i["key"] != "friends" else {**i, "value": "맹구(친구), 훈이(친구)"} for i in PEOPLE_ITEMS]
    more = [{"name": "철수", "category": "friends", "relation": "친구", "tmi": "", "quote": "", "sourceIds": ["p1"]},
            {"name": "유리", "category": "friends", "relation": "친구", "tmi": "", "quote": "", "sourceIds": ["p1"]},
            {"name": "수지", "category": "friends", "relation": "친구", "tmi": "", "quote": "", "sourceIds": ["p1"]}]  # 4명을 넘는 인원은 받지 않음
    spy = PeopleFake(fake, card4={"category": "friends", "friends": [{"name": "맹구", "relation": "친구", "tmi": ""}, {"name": "훈이", "relation": "친구", "tmi": ""}], "family": []},
                     items=two_friends, people=more)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    assert "친구(friends) 2명까지" in spy.prompts["people"]
    assert [p["name"] for p in job["research"]["people"]["friends"]] == ["맹구", "훈이", "철수", "유리"]
    assert [f["name"] for f in job["outline"]["cards"][3]["fields"]["friends"]] == ["맹구", "훈이", "철수", "유리"]


def test_researched_tmi_wins_over_other_ai_sentences(client, fake, monkeypatch):
    """AI가 카드에 다른 사실로 TMI를 써도, 그 캐릭터의 조사된 TMI(근거 문장 있음)를 씁니다. 조사되지 않은 캐릭터의 AI 문장은 그대로."""
    card4 = {**EMPTY_FRIENDS, "friends": [{"name": "철수", "relation": "방범대 멤버", "tmi": "어머니가 엄격한 편이에요."},
                                         {"name": "유리", "relation": "방범대 멤버", "tmi": "토끼 인형을 아껴요."}]}
    spy = PeopleFake(fake, card4=card4, people=FRIEND_TMI[:1])
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    tmis = {f["name"]: f["tmi"] for f in job["outline"]["cards"][3]["fields"]["friends"]}
    assert tmis["철수"] == FRIEND_TMI[0]["tmi"] and tmis["유리"] == "토끼 인형을 아껴요."
    # 사용자가 직접 고친 TMI는 그대로 저장됩니다
    fields = {**job["outline"]["cards"][3]["fields"]}
    fields["friends"] = [{**f, "tmi": "직접 확인한 다른 사실이에요." if f["name"] == "철수" else f["tmi"]} for f in fields["friends"]]
    job = edit(client, job_id, "card-04", fields, role="친구").json()
    assert job["outline"]["cards"][3]["fields"]["friends"][0]["tmi"] == "직접 확인한 다른 사실이에요."


def test_second_round_searches_only_characters_still_missing(client, fake, monkeypatch):
    spy = PeopleFake(fake, card4=EMPTY_FRIENDS, people=FRIEND_TMI[:2])  # 1회차에 철수·유리만 찾음
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    rounds = spy.prompts["rounds"]
    assert len(rounds) == 2  # 못 찾은 캐릭터가 있으면 한 번 더 (그 이상은 하지 않음)
    assert "따로 검색" in rounds[1] and "- 훈이" in rounds[1] and "- 철수" not in rounds[1] and "- 유리" not in rounds[1]
    detail = job["research"]["peopleResearch"]
    assert detail["rounds"] == 2 and [p["name"] for p in detail["people"]] == ["철수", "유리"]
    assert "훈이" in detail["missing"] and "시로" in detail["missing"]
    assert sum(1 for k, _ in spy.kinds if k == "people") == 2


def test_second_stage_failure_keeps_first_research(client, fake, monkeypatch):
    spy = PeopleFake(fake, card4=EMPTY_FRIENDS, people_error="시간 초과")
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    assert job["state"] == "waiting_outline" and job["research"]["peopleResearch"]["error"] == "시간 초과"
    assert [p["name"] for p in job["research"]["people"]["friends"]] == ["철수", "유리", "훈이", "맹구"]


def test_saved_research_keeps_people_tmi_and_passes_it_to_the_outline(client, fake, monkeypatch):
    spy = PeopleFake(fake, card4=EMPTY_FRIENDS, people=FRIEND_TMI)
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = start_ai(client)
    version_id = wait(client, job_id, "waiting_outline")["researchVersion"]["id"]
    # 보관함: 캐릭터별 이름·관계·TMI·근거·출처가 함께 저장됩니다
    stored = json.loads(research_library._path(version_id).read_text(encoding="utf-8"))
    assert [p["tmi"] for p in stored["research"]["peopleResearch"]["people"]] == [p["tmi"] for p in FRIEND_TMI]
    detail = client.get(f"/api/research-library/{version_id}").json()
    first = detail["peopleDetails"]["friends"][0]
    assert first == {"name": "철수", "relation": "유치원 친구", "tmi": FRIEND_TMI[0]["tmi"], "quote": FRIEND_TMI[0]["quote"], "sourceIds": ["p1"], "state": "secondary"}
    assert any(s["id"] == "p1" for s in detail["sources"])
    # 저장된 자료 사용: 새 조사 없이 구성안을 쓰고, 빈 TMI는 저장된 캐릭터별 TMI로 채웁니다
    spy.kinds.clear()
    job_id2, _ = start_ai(client, researchMode="saved", researchVersion=version_id)
    job = wait(client, job_id2, "waiting_outline")
    assert [k for k, _ in spy.kinds] == ["compose"]
    card = job["outline"]["cards"][3]
    assert [f["tmi"] for f in card["fields"]["friends"]] == [p["tmi"] for p in FRIEND_TMI] and "p1" in card["sourceIds"]
    assert any("TMI: 공부를 잘하고" in f["text"] for f in job["research"]["facts"])  # 문구를 쓸 AI에게도 전달
