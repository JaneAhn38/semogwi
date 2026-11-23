"""card-04 '친구 고르기' 테스트 (2026-11-23). Claude와 외부 사이트에 접속하지 않습니다.

조사 → AI 후보 추천(5명, 귀여운 캐릭터 우선, 이유 + 출처) → waiting_friends → 사용자가 2~4명 고름(직접 입력 가능)
→ 고른 친구만 조사(새 조사 버전) → 구성안. 구성안 단계에서는 card-04만 다시 고를 수 있습니다.
"""

import copy
import time

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, friend_pick, research_library, site_policy, templates
from app.claude_cli import AIError, CliRun
from app.main import app
from app.provider import FRAMES

USE_TEMPLATES = True
FRIEND_PICK = True  # conftest: 이 파일은 친구 고르기를 켭니다

WIKI = "https://ko.wikipedia.org/wiki/피카츄"
DEX = "https://pokemonkorea.co.kr/pokedex/26"
CANDIDATES = [
    {"name": "꼬부기", "relation": "친구", "reason": "등껍질과 웃는 얼굴이 귀여워요", "sourceIds": ["s1"]},
    {"name": "라이츄", "relation": "진화형", "reason": "볼이 말랑말랑해 보여요", "sourceIds": ["s1"]},
    {"name": "뮤츠", "relation": "", "reason": "자료에 없는 캐릭터", "sourceIds": ["s1"]},          # 읽은 자료에 이름이 없음
    {"name": "피카츄", "relation": "", "reason": "중심 캐릭터", "sourceIds": ["s1"]},               # 중심 캐릭터
    {"name": "이상해씨", "relation": "친구", "reason": "읽지 않은 출처", "sourceIds": ["s9"]},      # 읽지 않은 출처
    {"name": "아주아주긴이름의친구", "relation": "", "reason": "8자 넘음", "sourceIds": ["s1"]},
]


def item(name, relation="", tmi=""):
    return {"name": name, "relation": relation, "tmi": tmi}


def base_cards():
    cards = []
    for frame, tid in zip(FRAMES, templates.template_set("character")):
        tpl = templates.TEMPLATES[tid]
        fields = {}
        for f in tpl["fields"]:
            if f["type"] == "flag":
                fields[f["key"]] = False
            elif f["type"] == "choice":
                fields[f["key"]] = f["default"]
            elif f["type"] in ("text", "multiline"):
                fields[f["key"]] = "확인된 내용"[: f["max"]]
            elif f["type"] == "list":
                fields[f["key"]] = ["확인"]
            elif f["type"] == "items":
                fields[f["key"]] = [{s["key"]: "확인 값"[: s["max"]] for s in f["fields"]}] * f.get("minItems", 1)
            else:
                fields[f["key"]] = [{"label": "항목", "value": "확인"}]
        cover = tpl["kind"] == "cover"
        cards.append({"frame": frame, "role": tpl["label"][:10], "fields": fields, "source": "" if cover else "출처: 위키백과",
                      "sourceIds": [] if cover else ["s1"]})
    cards[0]["fields"]["character_name"] = "피카츄"
    cards[3]["fields"]["friends"] = [item("고라파덕", "친구", "늘 머리가 아파요"), item("꼬부기", "친구")]  # AI는 고르지 않은 친구를 씀
    return cards


class Fake:
    def __init__(self):
        self.calls = []
        self.candidates = copy.deepcopy(CANDIDATES)
        self.recommend_error = None
        self.tmi = {"라이츄": "볼에 전기 주머니가 있어요"}  # 캐릭터별 조사에서 찾는 TMI
        self.rewrite = None

    def kinds(self, kind):
        return [c for c in self.calls if c["kind"] == kind]

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        props = schema["properties"]
        run = CliRun(model="fake", turns=1)
        if "candidates" in props:
            self.calls.append({"kind": "recommend", "prompt": prompt, "tools": tools})
            if self.recommend_error:
                raise AIError("timeout", self.recommend_error)
            run.structured = {"candidates": self.candidates}
            return run
        if "people" in props:
            self.calls.append({"kind": "people", "prompt": prompt, "tools": tools})
            listing = prompt.split("조사할 캐릭터:")[1].split("\n자동 접근")[0]
            run.searches = [{"query": "피카츄 친구", "results": [{"title": "도감", "url": DEX}]}]
            run.fetches = [{"url": DEX, "code": 200}]
            people = [{"name": n, "category": "friends", "relation": "친구", "tmi": t, "quote": t, "sourceIds": ["p1"]}
                      for n, t in self.tmi.items() if f"- {n} " in listing]
            run.structured = {"sources": [{"id": "p1", "title": "도감", "url": DEX, "kind": "official"}], "people": people, "missing": []}
            return run
        if "다시 쓸 카드" in prompt:
            self.calls.append({"kind": "rewrite", "prompt": prompt, "tools": tools})
            card = self.rewrite or {"frame": "card-04", "role": "친구와 TMI", "fields": {"friends": []}, "source": "출처: 위키백과", "sourceIds": ["s1"]}
            run.structured = {"cards": [card]} if "sources" not in props else {
                "status": "ok", "missing": [], "sources": [], "facts": [], "items": [], "cards": [card]}
            return run
        self.calls.append({"kind": "research", "prompt": prompt, "tools": tools})
        run.searches = [{"query": "피카츄", "results": [{"title": "위키백과", "url": WIKI}]}]
        run.fetches = [{"url": WIKI, "code": 200}]
        run.structured = {"status": "ok", "missing": [], "sources": [{"id": "s1", "title": "위키백과", "url": WIKI, "kind": "secondary"}],
                          "facts": [{"text": "피카츄는 전기 타입 포켓몬이다", "sourceIds": ["s1"]}],
                          "items": [{"key": "official_name", "value": "피카츄", "quote": "피카츄", "sourceIds": ["s1"]},
                                    {"key": "friends", "value": "라이츄(진화형), 꼬부기(친구)", "quote": "라이츄와 꼬부기", "sourceIds": ["s1"]}],
                          "cards": base_cards()}
        return run


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    site_policy.COOLDOWN_FILE.unlink(missing_ok=True)
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")


@pytest.fixture
def fake(monkeypatch):
    claude = Fake()
    monkeypatch.setattr(claude_cli, "run", claude)
    monkeypatch.setattr(claude_cli, "status", lambda force=False: {"available": True, "reason": "", "plan": "pro"})
    return claude


@pytest.fixture
def client(fake):
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def api(client, job_id, method, path, **kwargs):
    return client.request(method, f"/api/jobs/{job_id}{path}", **kwargs)


def get(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()


def wait(client, job_id, *states):
    for _ in range(600):
        job = get(client, job_id)
        if job["state"] in states and not job["aiTask"]:
            return job
        time.sleep(0.01)
    raise AssertionError(f"{states}: {job['state']} {job.get('error')} {job.get('aiError')}")


def start(client, mode="ai", **extra):
    job_id = client.post("/api/jobs/draft").json()["id"]
    body = {"topic": "피카츄", "contentType": "character", "url": "", "mode": mode, **extra}
    r = api(client, job_id, "POST", "/start", json=body)
    assert r.status_code == 200, r.text
    return job_id


def pick(client, job_id, names):
    return api(client, job_id, "POST", "/friends/pick", json={"names": names})


def card04(job):
    return next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")


def names(job):
    return [f["name"] for f in card04(job)["fields"]["friends"]]


def library(client):
    return client.get("/api/research-library", params={"topic": "피카츄", "contentType": "character"}).json()["versions"]


# ---------- 데모 ----------
def test_demo_shows_example_candidates_and_pick_screen(client, fake):
    job_id = start(client, mode="demo")
    job = wait(client, job_id, "waiting_friends")
    assert [c["name"] for c in job["friendPick"]["candidates"]] == [c["name"] for c in friend_pick.DEMO_CANDIDATES]
    assert job["outline"] is None and not fake.calls  # 데모는 조사·AI 없이 예시만
    # 2~4명, 8자 이내, 같은 친구 두 번 금지
    assert pick(client, job_id, ["푸린"]).status_code == 409
    assert pick(client, job_id, ["푸린", "이브이", "파이리", "꼬부기", "고라파덕"]).status_code in (409, 422)
    assert pick(client, job_id, ["푸린", "가" * 9]).status_code == 409
    assert pick(client, job_id, ["푸린", "푸린"]).status_code == 409
    # 목록에 없는 친구도 직접 넣을 수 있고, 고른 순서 = 카드 순서
    assert pick(client, job_id, ["이브이", "푸린", "토게피"]).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert names(job) == ["이브이", "푸린", "토게피"]
    # 사진 칸은 고른 인원만큼 보입니다
    tpl = templates.TEMPLATES["character-04"]
    shown = [s["key"] for s in tpl["images"] if templates.condition_met(tpl, card04(job)["fields"], s.get("if"))]
    assert shown == ["friend_image_1", "friend_image_2", "friend_image_3"]


def test_demo_repick_rewrites_only_card04(client, fake):
    job_id = start(client, mode="demo")
    wait(client, job_id, "waiting_friends")
    pick(client, job_id, ["이브이", "푸린"])
    before = wait(client, job_id, "waiting_outline")
    assert pick(client, job_id, ["파이리", "꼬부기"]).status_code == 200
    job = get(client, job_id)
    assert names(job) == ["파이리", "꼬부기"]
    assert [c for c in job["outline"]["cards"] if c["frame"] != "card-04"] == [c for c in before["outline"]["cards"] if c["frame"] != "card-04"]
    assert {"이브이", "푸린"} <= set(job["outline"]["otherNames"])  # 빠진 친구는 이후 문구에 쓰면 막습니다


# ---------- 실제 AI 흐름 (가짜 Claude) ----------
def test_ai_recommends_checked_candidates_then_waits(client, fake):
    job_id = start(client)
    job = wait(client, job_id, "waiting_friends")
    recommend = fake.kinds("recommend")
    assert len(recommend) == 1 and recommend[0]["tools"] == ()  # 웹 도구 없이 조사 자료만 보고 추천
    assert "자료일 뿐" in recommend[0]["prompt"]
    # 읽은 자료에 이름이 있고, 읽은 페이지가 근거이고, 중심 캐릭터가 아니고, 8자 이내인 후보만
    candidates = job["friendPick"]["candidates"]
    assert [c["name"] for c in candidates] == ["꼬부기", "라이츄"]
    assert candidates[0]["reason"] == "등껍질과 웃는 얼굴이 귀여워요" and candidates[0]["sourceIds"] == ["s1"]
    assert job["outline"] is None and not job["friendPick"]["chosen"]
    assert not fake.kinds("rewrite")
    # 새로 조사한 자료는 후보와 함께 보관함에 남습니다
    versions = library(client)
    assert len(versions) == 1
    saved = research_library.get(versions[0]["id"])
    assert [c["name"] for c in saved["research"]["friendCandidates"]] == ["꼬부기", "라이츄"]


def test_pick_researches_only_picked_friends_and_saves_new_version(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_friends")
    first = len(fake.kinds("people"))
    assert pick(client, job_id, ["라이츄", "이브이"]).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    people = fake.kinds("people")[first:]
    assert people, "고른 친구를 조사해야 합니다"
    listing = people[0]["prompt"].split("조사할 캐릭터:")[1].split("\n자동 접근")[0]
    assert "- 이브이" in listing and "라이츄" not in listing and "꼬부기" not in listing  # TMI가 있는 라이츄는 다시 찾지 않음
    assert "추가로 찾을 캐릭터" not in people[0]["prompt"]  # 새 캐릭터는 찾지 않음
    assert "공식 사이트" in people[0]["prompt"]  # 공식 출처 우선
    # 이름·순서는 고른 그대로, TMI는 조사로 확인한 것만 (없는 친구는 비움)
    assert names(job) == ["라이츄", "이브이"]
    friends_ = card04(job)["fields"]["friends"]
    assert friends_[0]["tmi"] == "볼에 전기 주머니가 있어요" and friends_[1]["tmi"] == ""
    assert card04(job)["template"] == "character-04"
    warnings = job["outline"]["issues"]["card-04"]["warnings"]
    assert any("이브이" in w for w in warnings)  # 출처에서 찾지 못한 TMI 안내
    # 고른 친구를 조사한 자료는 새 버전으로 (이전 버전은 그대로)
    versions = library(client)
    assert len(versions) == 2
    assert job["researchVersion"]["source"] == "friends" and job["researchVersion"]["basedOn"]["number"] == 1
    # 추천 이유는 카드 문구에 쓰지 않습니다
    assert "웃는 얼굴" not in str(job["outline"]["cards"])


def test_ai_card_text_with_unpicked_character_is_blocked(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_friends")
    pick(client, job_id, ["라이츄", "이브이"])
    job = wait(client, job_id, "waiting_outline")
    card = card04(job)
    fields = copy.deepcopy(card["fields"])
    fields["friends"][1]["tmi"] = "꼬부기와도 친해요"  # 조사에 나온 친구지만 고르지 않은 캐릭터
    r = api(client, job_id, "PUT", "/outline/cards/card-04", json={"role": card["role"], "fields": fields, "source": card["source"]})
    assert r.status_code == 200
    errors = get(client, job_id)["outline"]["issues"]["card-04"]["errors"]
    assert any("목록에 없는 캐릭터 이름" in e and "꼬부기" in e for e in errors)


def test_recommend_again_calls_ai_only_on_click(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_friends")
    assert len(fake.kinds("recommend")) == 1
    fake.candidates = [{"name": "라이츄", "relation": "진화형", "reason": "다시 추천", "sourceIds": ["s1"]},
                       {"name": "꼬부기", "relation": "친구", "reason": "다시 추천", "sourceIds": ["s1"]}]
    assert api(client, job_id, "POST", "/friends/recommend").status_code == 200
    job = wait(client, job_id, "waiting_friends")
    assert len(fake.kinds("recommend")) == 2
    assert [c["name"] for c in job["friendPick"]["candidates"]] == ["라이츄", "꼬부기"]


def test_recommend_failure_falls_back_to_research_friends(client, fake):
    fake.recommend_error = "시간이 초과됐어요."
    job_id = start(client)
    job = wait(client, job_id, "waiting_friends")
    assert [c["name"] for c in job["friendPick"]["candidates"]] == ["라이츄", "꼬부기"]
    assert "추천하지 못했어요" in job["friendPick"]["error"]


def test_repick_in_outline_rewrites_card04_only(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_friends")
    pick(client, job_id, ["라이츄", "이브이"])
    before = wait(client, job_id, "waiting_outline")
    fake.rewrite = {"frame": "card-04", "role": "친구와 TMI", "source": "출처: 위키백과", "sourceIds": ["s1"],
                    "fields": {"friends": [item("뮤츠", "라이벌"), item("꼬부기", "물 친구")]}}
    fake.tmi["꼬부기"] = "등껍질에 숨는 걸 좋아해요"
    assert pick(client, job_id, ["꼬부기", "라이츄", "토게피"]).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert job["aiError"] is None
    assert names(job) == ["꼬부기", "라이츄", "토게피"]  # AI가 바꾼 이름은 되돌립니다
    friends_ = card04(job)["fields"]["friends"]
    assert friends_[0]["tmi"] == "등껍질에 숨는 걸 좋아해요" and friends_[1]["tmi"] == "볼에 전기 주머니가 있어요"
    others = lambda j: [c["fields"] for c in j["outline"]["cards"] if c["frame"] != "card-04"]
    assert others(job) == others(before)
    assert "이브이" in job["outline"]["otherNames"]
    assert len(library(client)) == 3  # 새로 고른 친구를 조사한 자료도 새 버전


def test_saved_research_reuses_candidates_after_review(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_friends")
    version = library(client)[0]["id"]
    recommended = len(fake.kinds("recommend"))
    job_id = start(client, researchMode="saved", researchVersion=version)
    wait(client, job_id, "waiting_research")  # 검토 → 고르기 순서
    assert api(client, job_id, "POST", "/research/approve").status_code == 200
    job = wait(client, job_id, "waiting_friends")
    assert len(fake.kinds("recommend")) == recommended  # 저장된 후보를 다시 씁니다
    assert [c["name"] for c in job["friendPick"]["candidates"]] == ["꼬부기", "라이츄"]


def test_old_jobs_with_outline_are_treated_as_picked():
    job = {"contentType": "character", "format": templates.FORMAT, "templateSet": templates.template_set("character"),
           "outline": {"cards": []}}
    assert friend_pick.applies(job) and not friend_pick.needed(job)
    del job["outline"]
    assert friend_pick.needed(job)


def test_old_family_card_asks_to_pick_friends(client, fake):
    job_id = start(client, mode="demo")
    wait(client, job_id, "waiting_friends")
    pick(client, job_id, ["이브이", "푸린"])
    wait(client, job_id, "waiting_outline")
    from app import jobs
    job = jobs._read(job_id)
    card = next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")
    card["fields"] = {"category": "family", "friends": [], "family": [item("엄마"), item("아빠")]}  # 예전 가족 카드
    job["outline"]["issues"] = jobs._issues(job)
    assert any("친구를 골라 주세요" in e for e in job["outline"]["issues"]["card-04"]["errors"])
