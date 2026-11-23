"""조사 결과 화면의 '추가 조사' 테스트: 초안 → 통합/버리기, 기존 자료 보존, 실패·중복·재시작 처리. Claude와 외부 사이트에 접속하지 않습니다."""

import json

import pytest

from app import claude_cli, jobs, research_library
from app.claude_cli import CliRun
from tests.test_research_library import (FRIEND_TMI, PeopleFake, approve_review, library, start_ai, start_saved)  # noqa: F401
from tests.test_templates import api, client, clear_cooldowns, fake, get, wait  # noqa: F401

USE_TEMPLATES = True
NEW_PAGE = "https://ko.wikipedia.org/wiki/짱구_생일"
# 추가 조사 결과: 비어 있던 생일은 새로 찾고, 성격은 기존 값(마이페이스)과 다른 값을 찾음
MORE_ITEMS = [
    {"key": "birthday", "value": "5월 5일", "quote": "생일은 5월 5일", "sourceIds": ["s1"]},
    {"key": "personality", "value": "장난꾸러기", "quote": "장난꾸러기", "sourceIds": ["s1"]},
]


class MoreFake(PeopleFake):
    """'추가 조사' 호출(<user_request>가 든 조사)에만 정해 둔 결과를 돌려주는 가짜 AI."""

    def __init__(self, base, **kwargs):
        super().__init__(base, **kwargs)
        self.more_items, self.more_error, self.more_prompts = MORE_ITEMS, None, []

    def __call__(self, prompt, system, schema, **kwargs):
        if "<user_request>" in prompt and "sources" in schema["properties"]:
            self.more_prompts.append(prompt)
            self.kinds.append(("more", tuple(kwargs.get("tools") or ())))
            if self.more_error:
                raise claude_cli.AIError("timeout", self.more_error)
            run = CliRun(model="fake", turns=1)
            run.searches = [{"query": "짱구 생일", "results": [{"title": "생일", "url": NEW_PAGE}]}]
            run.fetches = [{"url": NEW_PAGE, "code": 200}]
            run.structured = {"status": "ok", "missing": [], "items": self.more_items,
                              "sources": [{"id": "s1", "title": "짱구 생일 문서", "url": NEW_PAGE, "kind": "secondary"}],
                              "facts": [{"text": "짱구의 생일은 5월 5일이다", "sourceIds": ["s1"]}]}
            return run
        return super().__call__(prompt, system, schema, **kwargs)


@pytest.fixture(autouse=True)
def separate_library(tmp_path, monkeypatch):
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")


@pytest.fixture
def more_fake(fake, monkeypatch):
    spy = MoreFake(fake, people=FRIEND_TMI)  # 첫 조사에서 모든 캐릭터의 TMI를 찾음
    monkeypatch.setattr(claude_cli, "run", spy)
    return spy


def outline_job(client):
    job_id, r = start_ai(client)
    assert r.status_code == 200, r.text
    return job_id, wait(client, job_id, "waiting_outline")


def request_more(client, job_id, text="짱구의 생일과 성격을 더 찾아 줘"):
    r = api(client, job_id, "POST", "/research/more", json={"request": text})
    assert r.status_code == 202, r.text
    return wait(client, job_id, "waiting_outline", "waiting_research")


def items_of(research):
    return {i["key"]: i for i in research["items"]}


def test_more_research_makes_a_draft_without_touching_research_or_outline(client, more_fake):
    job_id, job = outline_job(client)
    before_research, before_outline = json.dumps(job["research"], sort_keys=True), json.dumps(job["outline"], sort_keys=True)
    more_fake.kinds.clear()
    job = request_more(client, job_id)
    # 웹 조사 1회만 (모든 캐릭터의 TMI가 있으므로 캐릭터별 조사를 다시 하지 않음), 구성안은 쓰지 않음
    assert [k for k, _ in more_fake.kinds] == ["more"] and more_fake.kinds[0][1] == ("WebSearch", "WebFetch")
    prompt = more_fake.more_prompts[0]
    assert "<user_request>짱구의 생일과 성격을 더 찾아 줘</user_request>" in prompt and "<saved_research>" in prompt and "마이페이스" in prompt
    assert "자동 접근 금지" in prompt  # 사이트 접근 제한 안내는 그대로
    # 지금 자료와 구성안은 그대로, 결과는 초안에만
    assert json.dumps(job["research"], sort_keys=True) == before_research
    assert json.dumps(job["outline"], sort_keys=True) == before_outline
    draft = job["researchDraft"]
    assert draft["round"] == 1 and draft["request"].startswith("짱구의 생일")
    items = items_of(draft["research"])
    assert items["birthday"]["value"] == "5월 5일" and items["birthday"]["moreResult"] == "added" and items["birthday"]["moreRound"] == 1
    # 다른 값은 덮어쓰지 않고 '다른 값'으로 붙여 선택을 받음
    personality = items["personality"]
    assert personality["value"] == "마이페이스" and personality["savedConflict"] and personality["moreResult"] == "conflicts"
    assert personality["alternatives"][-1] == {**personality["alternatives"][-1], "value": "장난꾸러기", "origin": "more", "round": 1}
    # 새 출처·사실에 회차 표시, 기존 출처 id와 겹치지 않음
    new_sources = [s for s in draft["research"]["sources"] if s.get("addedBy") == "more"]
    assert [s["url"] for s in new_sources] == [NEW_PAGE] and new_sources[0]["round"] == 1 and new_sources[0]["id"] != "s1"
    assert any(f.get("round") == 1 and "5월 5일" in f["text"] for f in draft["research"]["facts"])
    assert draft["summary"]["added"] == ["birthday"] and draft["summary"]["conflicts"] == ["personality"]
    # 기존 값은 그대로 (추가 조사에서 찾지 않은 항목도 유지)
    assert items["friends"]["value"].startswith("철수") and "moreRound" not in items["friends"]


def test_accept_needs_a_choice_then_saves_new_version_and_keeps_outline(client, more_fake):
    job_id, job = outline_job(client)
    first_version = job["researchVersion"]
    stored_before = research_library._path(first_version["id"]).read_text(encoding="utf-8")
    outline_before = [c["fields"] for c in job["outline"]["cards"]]
    request_more(client, job_id)
    # 다른 값을 고르기 전에는 통합할 수 없음
    r = api(client, job_id, "POST", "/research/more/accept")
    assert r.status_code == 409 and "성격" in r.json()["detail"]
    job = api(client, job_id, "POST", "/research/more/items/personality/choose", json={"index": 1}).json()
    assert items_of(job["research"])["personality"]["value"] == "마이페이스"  # 고르는 것도 초안에서만
    chosen = items_of(job["researchDraft"]["research"])["personality"]
    assert chosen["value"] == "장난꾸러기" and chosen["moreChosen"] == "more" and chosen["dismissed"][0]["value"] == "마이페이스"
    job = api(client, job_id, "POST", "/research/more/accept").json()
    assert job["researchDraft"] is None and job["state"] == "waiting_outline"
    items = items_of(job["research"])
    assert items["birthday"]["value"] == "5월 5일" and items["personality"]["value"] == "장난꾸러기"
    history = job["research"]["moreResearch"]
    assert history[0]["round"] == 1 and history[0]["basedOn"]["id"] == first_version["id"] and history[0]["added"] == ["birthday"]
    # 구성안은 바꾸지 않고(사용자 카드 보존) 다시 생성 안내만 남김
    assert [c["fields"] for c in job["outline"]["cards"]] == outline_before
    assert job["outline"]["researchUpdated"]["round"] == 1 and not job["outline"]["approved"]
    # 새 버전 저장, 이전 버전은 그대로
    versions = library(client)
    assert [v["number"] for v in versions] == [2, 1] and versions[0]["basedOn"] == 1
    assert job["researchVersion"] == {**job["researchVersion"], "source": "more", "number": 2, "round": 1}
    assert research_library._path(first_version["id"]).read_text(encoding="utf-8") == stored_before
    saved = json.loads(research_library._path(job["researchVersion"]["id"]).read_text(encoding="utf-8"))["research"]
    assert saved["moreResearch"][0]["request"].startswith("짱구의 생일") and any(s.get("round") == 1 for s in saved["sources"])
    # 통합된 자료로 '구성안 다시 생성' (기존 regenerate_outline) → 안내가 사라짐
    assert api(client, job_id, "POST", "/outline/regenerate").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert "researchUpdated" not in job["outline"] and job["outline"]["version"] == 2
    # 다음 추가 조사는 2회차
    job = request_more(client, job_id)
    assert job["researchDraft"]["round"] == 2


def test_discard_keeps_research_and_next_round_number_moves_on(client, more_fake):
    job_id, job = outline_job(client)
    before = json.dumps(job["research"], sort_keys=True)
    request_more(client, job_id)
    job = api(client, job_id, "POST", "/research/more/discard").json()
    assert job["researchDraft"] is None and json.dumps(job["research"], sort_keys=True) == before
    assert job["moreResearchLog"][0]["result"] == "discarded" and len(library(client)) == 1
    assert api(client, job_id, "POST", "/research/more/discard").status_code == 409
    job = request_more(client, job_id)
    assert job["researchDraft"]["round"] == 2


def test_failure_keeps_research_and_outline(client, more_fake):
    job_id, job = outline_job(client)
    before = (json.dumps(job["research"], sort_keys=True), json.dumps(job["outline"], sort_keys=True))
    more_fake.more_error = "조사 시간이 초과됐어요"
    job = request_more(client, job_id)
    assert "시간이 초과" in job["aiError"] and job["researchDraft"] is None and job["state"] == "waiting_outline"
    assert (json.dumps(job["research"], sort_keys=True), json.dumps(job["outline"], sort_keys=True)) == before
    more_fake.more_error = None
    assert request_more(client, job_id)["researchDraft"]  # 다시 시도할 수 있음


def test_duplicate_pending_and_state_rules(client, more_fake, monkeypatch):
    job_id, job = outline_job(client)
    assert api(client, job_id, "POST", "/research/more", json={"request": " "}).status_code in (409, 422)  # 빈 요청
    assert api(client, job_id, "POST", "/research/more", json={"request": "가"}).status_code == 409
    # AI 작업 중이면 같은 요청을 다시 받지 않음
    job = jobs._read(job_id)
    job["aiTask"] = {"kind": "research", "frame": None, "startedAt": "x"}
    jobs.save(job)
    monkeypatch.setitem(jobs._ai_tasks, job_id, object())
    assert api(client, job_id, "POST", "/research/more", json={"request": "생일"}).status_code == 409
    monkeypatch.delitem(jobs._ai_tasks, job_id)
    # 서버가 다시 시작돼 작업이 사라진 경우: 자료는 그대로이고 초안도 없음
    job = get(client, job_id)
    assert job["aiTask"] is None and "다시 시작" in job["aiError"] and job["researchDraft"] is None
    request_more(client, job_id)
    # 확인하지 않은 초안이 있으면 새 추가 조사·구성안 승인을 막음
    assert api(client, job_id, "POST", "/research/more", json={"request": "다른 것"}).status_code == 409
    r = api(client, job_id, "POST", "/outline/approve")
    assert r.status_code == 409 and "통합" in r.json()["detail"]
    api(client, job_id, "POST", "/research/more/discard")
    # 구성안 승인 뒤에는 추가 조사 불가
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    wait(client, job_id, "waiting_preview")
    r = api(client, job_id, "POST", "/research/more", json={"request": "생일"})
    assert r.status_code == 409


def test_demo_mode_cannot_use_more_research(client, more_fake):
    job_id, r = start_ai(client, mode="demo")
    wait(client, job_id, "waiting_outline")
    r = api(client, job_id, "POST", "/research/more", json={"request": "생일"})
    assert r.status_code == 409 and "실제 AI" in r.json()["detail"]


def test_accept_refuses_if_research_changed_meanwhile(client, more_fake):
    job_id, _ = outline_job(client)
    request_more(client, job_id)
    job = jobs._read(job_id)
    job["research"]["facts"].append({"text": "다른 경로로 바뀐 자료", "sourceIds": []})
    jobs.save(job)
    api(client, job_id, "POST", "/research/more/items/personality/choose", json={"index": 0})
    r = api(client, job_id, "POST", "/research/more/accept")
    assert r.status_code == 409 and "바뀌었어요" in r.json()["detail"]
    assert get(client, job_id)["research"]["facts"][-1]["text"] == "다른 경로로 바뀐 자료"


def test_character_people_round_runs_only_when_tmi_is_missing(client, fake, monkeypatch):
    spy = MoreFake(fake)  # 첫 조사에서 캐릭터별 TMI를 찾지 못함 → 철수 말고는 TMI가 없음
    monkeypatch.setattr(claude_cli, "run", spy)
    job_id, _ = outline_job(client)
    spy.kinds.clear()
    spy.people = FRIEND_TMI
    job = request_more(client, job_id, "친구들 TMI를 더 찾아 줘")
    kinds = [k for k, _ in spy.kinds]
    assert kinds[0] == "more" and "people" in kinds
    prompt = spy.prompts["rounds"][-1]
    assert "- 유리" in prompt.split("조사할 캐릭터:")[1].split("\n추가로")[0]  # TMI가 없는 캐릭터를 찾음
    people = {p["name"]: p for p in job["researchDraft"]["research"]["peopleResearch"]["people"]}
    assert people["유리"]["round"] == 1 and "유리" in job["researchDraft"]["summary"]["people"]
    assert all(not p.get("tmi") or p["name"] == "철수" for p in job["research"]["people"]["friends"])


def test_waiting_research_review_integrates_and_saves_one_version_on_approve(client, more_fake):
    job_id, job = outline_job(client)
    version_id = job["researchVersion"]["id"]
    more_fake.items = [{"key": "official_name", "value": "짱구", "quote": "짱구", "sourceIds": ["s1"]}]
    job_id2, job = start_saved(client, version_id)
    review_before = json.dumps(job["research"], sort_keys=True)
    more_fake.more_items = [MORE_ITEMS[0]]
    job = request_more(client, job_id2, "생일")
    assert job["state"] == "waiting_research" and json.dumps(job["research"], sort_keys=True) == review_before
    # 초안이 있는 동안은 검토 단계의 수정·승인을 막음 (자료가 엇갈리지 않게)
    assert api(client, job_id2, "POST", "/research/approve").status_code == 409
    job = api(client, job_id2, "POST", "/research/more/accept").json()
    assert job["state"] == "waiting_research" and items_of(job["research"])["birthday"]["value"] == "5월 5일"
    assert job["research"]["supplement"]["moreRounds"] == [1] and len(library(client)) == 1  # 버전은 승인할 때 한 번만
    job = approve_review(client, job_id2)
    versions = library(client)
    assert len(versions) == 2 and job["researchVersion"]["source"] == "supplement"
    saved = json.loads(research_library._path(versions[0]["id"]).read_text(encoding="utf-8"))["research"]
    assert saved["moreResearch"][0]["round"] == 1 and {i["key"]: i["value"] for i in saved["items"]}["birthday"] == "5월 5일"
