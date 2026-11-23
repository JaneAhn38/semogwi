"""자료가 부족해도 진행 + 공식 출처를 필수로 두지 않는 출처 기준.

- 부족 판단은 '실제로 필요한 정보가 있는지'로 합니다. 기사·위키·나무위키 같은 2차 자료와 값이 적힌 검색 결과도 자료로 인정합니다.
- 공식 확인 여부로는 막지 않고, 출처 종류·URL·원문 게시일·조사일은 계속 기록합니다.
- 출처 충돌·근거가 약한 정보는 경고, 출처가 없는 사실과 자료에 없는 숫자는 계속 막습니다.
Claude와 외부 사이트에 접속하지 않습니다.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ai_provider, claude_cli, jobs, research, site_policy
from app.main import app
from tests.test_flexible_outline import COVER, SHOP, SOURCE, TOPIC, Fake, api, card, clear_cooldowns, errors_of, get, item, wait  # noqa: F401
from tests.test_templates import upload

USE_TEMPLATES = True
NEWS = "https://news.example/mandu"
NEWS_SOURCE = {"id": "s9", "title": "기사", "url": NEWS, "kind": "secondary", "publishedAt": "2026-09-01"}


class NewsFake(Fake):
    """기사 페이지도 실제로 읽은 것으로 기록합니다 (공식이 아닌 2차 자료)."""

    def __call__(self, prompt, system, schema, *, tools=(), images=None, **kwargs):
        run = super().__call__(prompt, system, schema, tools=tools, images=images, **kwargs)
        if tools and "sources" in schema["properties"]:
            run.fetches = run.fetches + [{"url": NEWS, "code": 200}]
            run.searches = run.searches + [{"query": "안경만두 기사", "results": [{"title": "기사", "url": NEWS}]}]
        return run


@pytest.fixture
def fake(monkeypatch):
    claude = NewsFake()
    monkeypatch.setattr(claude_cli, "run", claude)
    monkeypatch.setattr(claude_cli, "status", lambda force=False: {"available": True, "reason": "", "plan": "pro"})
    return claude


@pytest.fixture
def client(fake):
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


# 상품명·출시일은 기사(2차 자료)에서 확인, 판매처는 출처끼리 다름, 가격·특징·구성품은 찾지 못함 → 실제로 정보가 부족함
INSUFFICIENT = {
    "status": "insufficient", "missing": ["가격과 상품 특징을 찾지 못했어요"], "sources": [SOURCE, NEWS_SOURCE],
    "facts": [{"text": "안경만두 파우치 12월 1일 발매 (기사)", "sourceIds": ["s9"]}],
    "items": [item("product_names", "안경만두 파우치", ("s9",)), item("release_date", "12월 1일", ("s9",)),
              item("seller", "공식 숍", ("s1",)), item("seller", "편의점", ("s9",))],
    "cards": [],
}
COVER_WITH_DATE = {**COVER, "fields": {**COVER["fields"], "release_date": "12월 1일"}}
CARDS = [COVER_WITH_DATE,
         card("card-02", "goods-02", {"goods": [{"name": "안경만두 파우치", "kind": "파우치"}]}, role="라인업", ids=("s9",)),
         card("card-03", "goods-free", {"heading": "구매 안내", "points": [{"label": "판매처", "value": "공식 숍"}]}, role="구매"),
         card("card-04", "goods-free", {"heading": "참고", "notes": ["재고는 매장마다 달라요"]}, role="참고"),
         card("card-05", "goods-free", {"heading": "마무리", "notes": ["공식 숍에서 만나요"]}, role="마무리")]


def start_insufficient(client, fake):
    fake.research = INSUFFICIENT
    job_id = client.post("/api/jobs/draft").json()["id"]
    assert api(client, job_id, "POST", "/start", json=TOPIC).status_code == 200
    return job_id, wait(client, job_id, "waiting_material")


def compose_now(client, fake, job_id, cards=CARDS, status="insufficient"):
    fake.compose = {"status": status, "missing": ["가격"], "cards": cards}
    assert api(client, job_id, "POST", "/research/compose-current").status_code == 200
    return wait(client, job_id, "waiting_outline")


# ---------- 부족 판단: 공식 확인이 아니라 실제로 정보가 있는지 ----------
def test_gap_report_counts_secondary_and_quoted_search_results_as_found():
    sources = [{**NEWS_SOURCE, "verification": "fetched"}, {"id": "q", "url": "https://q.example", "kind": "secondary", "verification": "search_result"}]
    items = research.verify_items("goods", [item("product_names", "파우치", ("s9",)), {"key": "price", "value": "¥440", "quote": "파우치 ¥440", "sourceIds": ["q"]},
                                            item("seller", "공식 숍", ("s9",)), {"key": "seller", "value": "편의점", "quote": "q", "sourceIds": ["q"]}], sources)
    gap = research.gap_report("goods", items, ["메모"])
    rows = {r["key"]: r for r in gap["rows"]}
    assert gap["ready"]  # 기사에서 상품명, 검색 결과(값이 적힘)에서 가격 → 핵심 정보가 있음
    assert "product_names" not in rows and "price" not in rows  # 공식 확인이 없다고 부족으로 보지 않음
    assert rows["seller"]["kind"] == "weak" and rows["seller"]["state"] == "conflict"
    assert rows["features"]["kind"] == "not_found" and rows["features"]["value"] == ""
    price = next(i for i in items if i["key"] == "price")
    assert price["state"] == "listed" and price["evidence"][0]["pageRead"] is False  # 원문을 읽지 못했다는 사실은 따로 남음


def test_insufficient_research_is_kept_and_explained(client, fake):
    _, job = start_insufficient(client, fake)
    assert job["outline"] is None and job["researchStage"]["done"] and job["researchStage"]["insufficient"]
    assert job["researchVersion"]  # 부족해도 조사 자료는 보관함에 새 버전으로 남습니다
    kinds = {r["key"]: r["kind"] for r in job["researchGap"]["rows"]}
    assert kinds["price"] == "not_found" and kinds["features"] == "not_found" and kinds["seller"] == "weak"
    assert "product_names" not in kinds  # 기사에서 찾았으므로 부족하지 않음


# ---------- '현재 자료로 구성안 작성' ----------
def test_compose_with_current_material_moves_on_without_searching_again(client, fake):
    job_id, _ = start_insufficient(client, fake)
    before = len(fake.calls)
    job = compose_now(client, fake, job_id)  # AI가 또 부족하다고 해도 카드가 있으면 진행
    new_calls = fake.calls[before:]
    assert [c["kind"] for c in new_calls] == ["compose"] and new_calls[0]["tools"] == ()  # 조사를 반복하지 않음
    prompt = new_calls[0]["prompt"]
    assert "[현재 자료로 작성]" in prompt and "만들지 않고 칸을 비운다" in prompt and "공식 확인 필요" not in prompt
    assert job["researchStage"]["forced"] and job["research"]["partial"]
    # 2차 자료(기사)로 쓴 칸은 공식 확인이 없어도 막지 않습니다. 출처 종류는 그대로 남습니다
    assert job["outline"]["fieldStates"]["card-02"]["goods"] == "secondary"
    assert not errors_of(job)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    assert api(client, job_id, "POST", "/research/compose-current").status_code == 409  # 이미 다음 단계


def test_invented_price_is_cleared_and_conflicts_warn(client, fake):
    job_id, _ = start_insufficient(client, fake)
    cards = [CARDS[0], card("card-02", "goods-02", {"goods": [{"name": "안경만두 파우치", "kind": "파우치"}], "price_range": "12,000원"}, role="라인업", ids=("s9",)),
             card("card-03", "goods-free", {"heading": "구매 안내", "points": [{"label": "판매처", "value": "편의점"}]}, role="구매")] + CARDS[3:]
    job = compose_now(client, fake, job_id, cards)
    c2 = job["outline"]["cards"][1]
    # 조사에 없는 가격(12,000원)은 AI가 지어낸 값이라 자동으로 비우고 알립니다 (제작은 멈추지 않음)
    assert c2["fields"]["price_range"] == "" and c2["cleared"] == [{"key": "price_range", "label": "가격대", "value": "12,000원"}]
    assert any("조사에서 찾지 못한 정보라 비웠어요: 가격대 ('12,000원')" in w for w in job["outline"]["issues"]["card-02"]["warnings"])
    assert any("출처마다 값이 달라요: 판매처" in w for w in job["outline"]["issues"]["card-03"]["warnings"])  # 충돌은 경고
    assert not errors_of(job)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_volatile_info_keeps_published_and_researched_dates(client, fake):
    job_id, _ = start_insufficient(client, fake)
    job = compose_now(client, fake, job_id)
    release = next(i for i in job["research"]["items"] if i["key"] == "release_date")
    assert release["evidence"][0]["publishedAt"] == "2026-09-01" and release["evidence"][0]["at"]  # 원문 게시일과 조사일을 따로
    assert next(s for s in job["research"]["sources"] if s["id"] == "s9")["publishedAt"] == "2026-09-01"
    published, researched = jobs.item_dates(release)
    assert published == "2026-09-01" and researched >= "2026-11-01"
    # 오래된 기사의 출시일: 구성안에서 최신 정보인지 확인하라고 알립니다 (막지 않음)
    assert any("원문 게시일 2026-09-01" in w for w in job["outline"]["issues"]["card-01"]["warnings"])
    texts = [w["text"] for w in job["outline"]["publishWarnings"]]
    assert any("발매일" in t and "원문 게시일 2026-09-01 · 조사일" in t for t in texts)  # 표지의 발매일 칸 (출시일 항목)
    assert any("자료가 부족한 상태" in t for t in texts)


def test_png_has_no_automatic_check_marks_and_saving_is_not_blocked(client, fake):
    job_id, _ = start_insufficient(client, fake)
    job = compose_now(client, fake, job_id)
    c2 = job["outline"]["cards"][1]
    # 예전 화면이 보내던 '확인 필요' 표시는 받기만 하고 쓰지 않습니다
    r = api(client, job_id, "PUT", "/outline/cards/card-02", json={"role": c2["role"], "fields": c2["fields"], "source": c2["source"], "checkMarks": ["goods"]})
    assert r.status_code == 200 and "checkMarks" not in r.json()["outline"]["cards"][1]
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    job = wait(client, job_id, "waiting_preview")
    assert all("checkMarks" not in c["spec"] for c in job["preview"]["cards"])
    renderer = (Path(__file__).resolve().parent.parent / "static" / "renderer.js").read_text(encoding="utf-8")
    assert "(확인 필요)" not in renderer and "checkMarks" not in renderer  # 카드 그림에 자동 문구를 넣지 않음
    asset = upload(client, job_id)
    api(client, job_id, "PUT", "/cards/card-01/slots/main_goods_image", json={"assetId": asset, "variant": "original"})
    assert api(client, job_id, "POST", "/preview/approve").status_code == 200  # 경고가 있어도 막지 않음
    assert wait(client, job_id, "done")["outline"]["publishWarnings"]


def test_compose_with_current_needs_some_material(client, fake):
    fake.research = {"status": "insufficient", "missing": ["아무것도 없음"], "sources": [], "facts": [], "items": [], "cards": []}
    job_id = client.post("/api/jobs/draft").json()["id"]
    api(client, job_id, "POST", "/start", json=TOPIC)
    wait(client, job_id, "waiting_material")
    r = api(client, job_id, "POST", "/research/compose-current")
    assert r.status_code == 409 and "조사된 자료가 없어" in r.json()["detail"]


def test_failed_forced_compose_retries_without_searching(client, fake):
    job_id, _ = start_insufficient(client, fake)
    fake.compose = {"status": "insufficient", "missing": ["특징"], "cards": []}  # 카드를 하나도 못 씀
    api(client, job_id, "POST", "/research/compose-current")
    job = wait(client, job_id, "failed")
    assert "카드를 만들지 못했어요" in job["error"]
    fake.compose = {"status": "ok", "missing": [], "cards": CARDS}
    before = len(fake.calls)
    assert api(client, job_id, "POST", "/retry").status_code == 200
    wait(client, job_id, "waiting_outline")
    assert [c["kind"] for c in fake.calls[before:]] == ["compose"]  # 조사를 다시 하지 않고 구성안만


# ---------- 자료 보완: 추가 조사 · 직접 입력 ----------
def test_more_research_is_available_while_waiting_for_material(client, fake):
    job_id, _ = start_insufficient(client, fake)
    r = api(client, job_id, "POST", "/research/more", json={"request": "가격과 상품 특징"})
    assert r.status_code == 202, r.text


def test_material_blocks_are_user_sources_never_official(client, fake):
    job_id, _ = start_insufficient(client, fake)
    fake.compose = {"status": "insufficient", "missing": ["특징"], "cards": CARDS}
    body = {"extra": "파우치는 지퍼형이에요", "sources": [
        {"url": SHOP, "kind": "official", "text": "안경만두 파우치 9,000원 세금 포함"},
        {"url": "https://namu.wiki/w/안경만두", "kind": "namuwiki", "text": "안경만두 파우치는 12월 1일 발매"},
        {"url": "", "kind": "other", "text": "매장 안내문: 1인 2개까지"}]}
    assert api(client, job_id, "POST", "/material", json=body).status_code == 200  # 굿즈에서도 사용자가 준 나무위키 자료를 받음
    job = wait(client, job_id, "waiting_outline")  # 자료를 낸 뒤에는 같은 부족 판단으로 다시 막지 않음
    users = {s["id"]: s for s in job["research"]["sources"] if s["origin"] == "user"}
    assert set(users) == {"user1", "user2", "user3", "user4"}
    assert all(s["kind"] == "user" and s["verification"] == "user_provided" for s in users.values())  # 공식으로 승격하지 않음
    assert "검증 안 됨" in users["user2"]["title"] and users["user3"]["auxiliary"]["site"] == "namu.wiki"
    assert "안경만두 파우치 9,000원 세금 포함" in fake.calls[-1]["prompt"]  # AI가 참고


def test_namuwiki_mirror_is_still_refused_and_auto_fetch_scope_is_unchanged(client, fake):
    job_id, _ = start_insufficient(client, fake)
    r = api(client, job_id, "POST", "/material", json={"sources": [{"url": "https://namu.moe/w/x", "text": "가격"}]})
    assert r.status_code == 409 and get(client, job_id)["userMaterial"] is None
    assert "WebFetch(domain:namu.wiki)" in site_policy.deny_rules("goods")  # 굿즈 조사에서 나무위키 자동 읽기는 그대로 막힘
    assert "WebFetch(domain:namu.wiki)" not in site_policy.deny_rules("character")
    assert "WebFetch(domain:chiikawamarket.jp)" in site_policy.deny_rules("goods")  # 자동 수집 금지 사이트 그대로


def test_user_material_sources_mark_namuwiki_as_auxiliary_for_any_type():
    for content_type in ("character", "goods", "popup", "collab"):
        sources, facts = ai_provider.user_material_sources({"sources": [{"url": "https://namu.wiki/w/x", "kind": "", "text": "내용"}]}, content_type)
        assert sources[0]["id"] == "user2" and sources[0]["auxiliary"]["site"] == "namu.wiki" and sources[0]["verification"] == "user_provided"
        assert facts[0]["sourceIds"] == ["user2"]
