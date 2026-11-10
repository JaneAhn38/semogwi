"""유형별 조사 항목, 근거 검증, 사용자 참고 자료 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import json

import pytest

from app import claude_cli, research, templates
from app.claude_cli import CliRun
from tests.test_templates import BASE, OFFICIAL, Fake, api, get, start, valid_cards, wait  # noqa: F401  (픽스처는 아래에서 다시 정의)

USE_TEMPLATES = True
WIKI = "https://ko.wikipedia.org/wiki/치이카와"
BLOG = "https://blog.example/post"


class ItemFake(Fake):
    """조사 항목(items)까지 돌려주는 가짜 Claude."""

    def __init__(self):
        super().__init__()
        self.items = []
        self.sources = [{"id": "s1", "title": "공식", "url": OFFICIAL, "kind": "official"}]
        self.fetches = [{"url": OFFICIAL, "code": 200}]

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        run = super().__call__(prompt, system, schema, tools=tools, disallowed=disallowed, **kwargs)
        if "items" in schema["properties"]:
            run.structured = {**run.structured, "items": self.items, "sources": self.sources}
            run.fetches = self.fetches
            run.searches = [{"query": "q", "results": [{"title": "블로그", "url": BLOG}]}]
        return run


@pytest.fixture
def fake(monkeypatch):
    claude = ItemFake()
    monkeypatch.setattr(claude_cli, "run", claude)
    monkeypatch.setattr(claude_cli, "status", lambda force=False: {"available": True, "reason": "", "plan": "pro"})
    return claude


@pytest.fixture
def client(fake):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


@pytest.fixture(autouse=True)
def clear_cooldowns():
    from app import site_policy
    site_policy.COOLDOWN_FILE.unlink(missing_ok=True)


# ---------- 항목 검증 ----------
SOURCES = [
    {"id": "off", "kind": "official", "verification": "fetched"},
    {"id": "wiki", "kind": "secondary", "verification": "fetched"},
    {"id": "list", "kind": "official", "verification": "search_result"},
    {"id": "ghost", "kind": "official", "verification": "unverified"},
    {"id": "u1", "kind": "user", "verification": "user_provided"},
]


def test_every_type_has_a_checklist_matching_the_request():
    assert {"official_name", "creator", "debut", "birthday", "friends", "relations", "tmi", "official_account"} <= set(research.keys_of("character"))
    assert {"release_date", "seller", "price", "size", "material", "components", "purchase_limit", "shipping"} <= set(research.keys_of("goods"))
    assert {"partners", "period", "place", "menu", "item_prices", "perks", "perk_conditions", "how_to_join"} <= set(research.keys_of("collab"))
    assert {"period", "hours", "place", "closed_days", "entry", "reservation", "goods_prices", "purchase_limit", "photozone", "perks", "notices"} <= set(research.keys_of("popup"))
    # 가격·일정·장소·특전은 공식 자료만
    strict = {key: s for key, _, s in research.ITEMS["goods"]}
    assert strict["price"] and strict["release_date"] and strict["seller"] and strict["size"]


def test_template_fields_point_to_known_items():
    for type_id in ("character", "goods", "collab", "popup"):
        mapped = {f["item"] for tid in templates.template_set(type_id) for f in templates.TEMPLATES[tid]["fields"] if f.get("item")}
        assert mapped <= set(research.keys_of(type_id)) and len(mapped) >= 5


@pytest.mark.parametrize("ids, state", [
    (["off"], "verified"), (["wiki"], "secondary"), (["list"], "listed"), (["ghost"], "unverified"), ([], "unverified"),
    (["u1"], "user"), (["off", "wiki"], "verified"), (["nope"], "unverified"),
])
def test_item_state_comes_from_the_tool_record(ids, state):
    items = research.verify_items("character", [{"key": "birthday", "value": "5월 1일", "quote": "생일은 5월 1일", "sourceIds": ids}], SOURCES)
    assert next(i for i in items if i["key"] == "birthday")["state"] == state


def test_items_are_deduplicated_and_conflicts_marked():
    raw = [
        {"key": "price", "value": "1,500원", "quote": "가격 1,500원", "sourceIds": ["off"]},
        {"key": "price", "value": "1, 500원", "quote": "", "sourceIds": ["wiki"]},  # 같은 값 → 합침
        {"key": "price", "value": "1,600원", "quote": "1,600원", "sourceIds": ["list"]},  # 다른 값 → 충돌
        {"key": "size", "value": "", "quote": "", "sourceIds": []},
        {"key": "unknown", "value": "x", "quote": "", "sourceIds": []},
    ]
    items = {i["key"]: i for i in research.verify_items("goods", raw, SOURCES)}
    assert items["price"]["state"] == "conflict" and items["price"]["sourceIds"] == ["off", "wiki"]
    assert [a["value"] for a in items["price"]["alternatives"]] == ["1,600원"]
    assert items["size"]["state"] == "missing" and items["material"]["state"] == "missing"
    assert len(items) == len(research.ITEMS["goods"])
    facts = research.facts_from_items(list(items.values()))
    assert {"가격: 1,500원", "가격: 1,600원"} <= {f["text"] for f in facts}


# ---------- 조사 흐름 ----------
def test_research_prompt_has_checklist_notes_and_bigger_budget(client, fake):
    job_id = start(client, mode="ai", notes="공식 계정 공지: 생일은 5월 1일")
    wait(client, job_id, "waiting_outline")
    call = fake.calls[0]
    assert "[조사 항목]" in call["prompt"] and "- birthday: 생일 등 공식 프로필" in call["prompt"]
    assert "<user_notes>공식 계정 공지: 생일은 5월 1일</user_notes>" in call["prompt"]
    assert "WebSearch를 최대 6회, WebFetch를 최대 5회" in call["system"]
    item_schema = call["schema"]["properties"]["items"]["items"]["properties"]["key"]["enum"]
    assert item_schema == research.keys_of("character")


def test_user_notes_are_user_provided_source(client, fake):
    fake.items = [{"key": "birthday", "value": "5월 1일", "quote": "생일은 5월 1일", "sourceIds": ["u1"]}]
    job_id = start(client, mode="ai", notes="생일은 5월 1일이에요")
    job = wait(client, job_id, "waiting_outline")
    source = next(s for s in job["research"]["sources"] if s["id"] == "u1")
    assert source["verification"] == "user_provided" and source["kind"] == "user"
    birthday = next(i for i in job["research"]["items"] if i["key"] == "birthday")
    assert birthday["state"] == "user"
    assert any(f["origin"] == "user" and "5월 1일" in f["text"] for f in job["research"]["facts"])


def test_numbers_from_user_notes_are_accepted(client, fake):
    fake.overrides = {"card-03": {"featured_price": "1,500원"}}
    job_id = start(client, mode="ai", contentType="goods", topic="세모귀 키링", notes="판매 페이지 안내: 가격 1,500원")
    job = wait(client, job_id, "waiting_outline")
    assert not any("1,500" in e for e in job["outline"]["issues"]["card-03"]["errors"])


def test_field_states_and_issues(client, fake):
    fake.sources = [{"id": "s1", "title": "공식", "url": OFFICIAL, "kind": "official"}, {"id": "b1", "title": "블로그", "url": BLOG, "kind": "secondary"}]
    fake.items = [
        {"key": "release_date", "value": "11.20", "quote": "11월 20일 발매", "sourceIds": ["s1"]},
        {"key": "seller", "value": "공식몰", "quote": "", "sourceIds": ["b1"]},  # 블로그는 검색 목록에만 있음
        {"key": "price", "value": "1,500원", "quote": "", "sourceIds": ["s1"]},
        {"key": "price", "value": "1,600원", "quote": "", "sourceIds": ["s1"]},  # 공식끼리도 값이 다름
    ]
    job_id = start(client, mode="ai", contentType="goods", topic="세모귀 키링")
    job = wait(client, job_id, "waiting_outline")
    states = job["outline"]["fieldStates"]
    assert states["card-01"]["release_date"] == "verified" and states["card-01"]["seller"] == "listed"
    assert states["card-02"]["price_range"] == "conflict"
    errors = job["outline"]["issues"]["card-01"]["errors"]
    assert any("공식 출처에서 확인하지 못한 정보예요: 판매처" in e for e in errors)
    assert any("출처마다 값이 달라요: 가격대 (1,500원 / 1,600원)" in e for e in job["outline"]["issues"]["card-02"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409

    # 사용자가 직접 확인해 고치면 경고로 바뀝니다
    card = job["outline"]["cards"][0]
    r = api(client, job_id, "PUT", "/outline/cards/card-01", json={"role": card["role"], "fields": {**card["fields"], "seller": "세모귀 공식몰"}, "source": ""})
    issue = r.json()["outline"]["issues"]["card-01"]
    assert not any("판매처" in e for e in issue["errors"]) and any("판매처" in w for w in issue["warnings"])


def test_character_secondary_sources_are_allowed_but_listed_ones_warn(client, fake):
    fake.sources = [{"id": "w1", "title": "위키", "url": WIKI, "kind": "secondary"}, {"id": "b1", "title": "블로그", "url": BLOG, "kind": "secondary"}]
    fake.fetches = [{"url": WIKI, "code": 200}]
    fake.items = [{"key": "birthday", "value": "확인된 내용", "quote": "", "sourceIds": ["w1"]},
                  {"key": "favorite", "value": "확인된 내용", "quote": "", "sourceIds": ["b1"]}]
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    states = job["outline"]["fieldStates"]["card-02"]
    assert states["birthday"] == "secondary" and states["favorite_things"] == "listed"
    issue = job["outline"]["issues"]["card-02"]
    assert not issue["errors"] and any("근거를 확인하지 못한 정보예요: 좋아하는 것" in w for w in issue["warnings"])


def test_missing_items_show_as_needing_input(client, fake):
    fake.overrides = {"card-02": {"birthday": "", "creator": ""}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    states = job["outline"]["fieldStates"]["card-02"]
    assert states["birthday"] == "missing" and states["creator"] == "missing"
    assert all(i["state"] == "missing" for i in job["research"]["items"])  # 가짜 응답에 항목이 없으면 모두 정보 확인 필요


def test_search_failures_are_recorded():
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "WebSearch", "input": {"query": "치이카와 생일"}}]}},
        {"type": "user", "tool_use_result": "Error", "message": {"content": [{"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "Search failed"}]}},
    ]
    parsed = claude_cli.parse_stream("\n".join(json.dumps(x) for x in lines))
    assert parsed.search_failures == [{"query": "치이카와 생일", "reason": "검색 도구 오류"}]


def test_empty_search_results_are_reported(client, fake):
    original = ItemFake.__call__

    def empty(self, *args, **kwargs):
        run = original(self, *args, **kwargs)
        run.searches = [{"query": "없는 주제", "results": []}]
        return run

    ItemFake.__call__ = empty
    try:
        job_id = start(client, mode="ai")
        job = wait(client, job_id, "waiting_outline")
    finally:
        ItemFake.__call__ = original
    assert {"query": "없는 주제", "reason": "검색 결과 없음"} in job["research"]["searchFailures"]


def test_notes_are_saved_with_input(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    r = api(client, job_id, "PATCH", "/input", json={**BASE, "notes": "  공식 공지 내용  "})
    assert r.status_code == 200 and r.json()["notes"] == "공식 공지 내용"
    assert api(client, job_id, "PATCH", "/input", json={**BASE, "notes": "가" * 4001}).status_code == 422


def test_restricted_site_still_makes_no_ai_call_with_notes(client, fake):
    job_id = start(client, mode="ai", url="https://chiikawamarket.jp/ko/products/1", notes="사용자가 본 내용")
    assert get(client, job_id)["state"] == "waiting_material" and fake.calls == []
