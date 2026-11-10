"""공식 사이트 접속 실패(429 등) 시 사용자 자료로 이어 가는 흐름 테스트. claude를 호출하지 않습니다."""

import json
import os
import tempfile
import time

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import ai_provider, claude_cli, jobs, site_policy
from app.claude_cli import AIError, CliRun
from app.main import app
from app.outline import unsupported_numbers

SHOP = "https://official-shop.example/ko/products/1"
INPUT = {"topic": "코인 실린더", "contentType": "goods", "url": SHOP, "mode": "ai"}
MATERIAL = {"name": "치이카와 코인 실린더", "price": "¥440 (세금 포함)", "features": "작은 아크릴 파츠가 포인트", "seller": "치이카와 마켓", "sourceUrl": SHOP, "pasted": ""}
THEME = {"name": "테마", "rationale": "이유", "displayFont": "Jua", "bodyFont": "Gowun Dodum",
         "palette": {"bgFrom": "#FFE9EF", "bgTo": "#FFF6E5", "ink": "#3A2433", "inkSoft": "#5C4152", "accent": "#FFB3C8", "accent2": "#BDE7DC", "accent3": "#FFE08A", "panel": "#FFFFFF"}}


def blocked_research():
    return {"status": "insufficient", "missing": ["상품명과 가격을 확인하지 못함"], "sources": [], "facts": [], "cards": []}


def composed_cards(body="작은 아크릴 파츠가 포인트예요.", source="출처: 치이카와 마켓"):
    cards = [{"frame": "card-01", "role": "표지", "title": "코인 실린더", "body": "귀여운 굿즈를 소개해요.", "source": "", "sourceIds": []}]
    for i in range(2, 6):
        cards.append({"frame": f"card-0{i}", "role": "소개", "title": f"포인트 {'가나다라'[i - 2]}", "body": body, "source": source, "sourceIds": ["user1"]})
    return cards


def design_card(frame):
    index = int(frame[-1])
    return {"frame": frame, "layoutLabel": f"구성 {index}", "background": {"start": "bgFrom", "end": "bgTo", "angle": 100}, "elements": [
        {"type": "text", "role": "page", "box": {"x": 860, "y": 60, "w": 150, "h": 44}, "font": "body", "size": 26, "color": "inkSoft", "align": "right", "valign": "top"},
        {"type": "text", "role": "source", "box": {"x": 70, "y": 60, "w": 700, "h": 44}, "font": "body", "size": 26, "color": "inkSoft", "align": "left", "valign": "top"},
        {"type": "text", "role": "title", "box": {"x": 80, "y": 120 + index * 100, "w": 900, "h": 150}, "font": "display", "size": 96, "color": "ink", "align": "left", "valign": "top"},
        {"type": "text", "role": "body", "box": {"x": 80, "y": 300 + index * 100, "w": 900, "h": 260}, "font": "body", "size": 44, "color": "ink", "align": "left", "valign": "top"}]}


class Fake:
    def __init__(self):
        self.calls = []
        self.queue = []
        self.fetches = [{"url": SHOP, "code": 429}, {"url": SHOP, "code": 429}]

    def __call__(self, prompt, system, schema, *, tools=(), **kwargs):
        self.calls.append({"prompt": prompt, "tools": tools, "system": system, "disallowed": kwargs.get("disallowed", ())})
        props = schema["properties"]
        run = CliRun(model="m", five_hour_utilization=0.5)
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            run.structured = item
        elif "sources" in props:
            run.structured = blocked_research()
        elif "theme" in props:
            run.structured = {"theme": THEME, "cards": [design_card(f"card-0{i}") for i in range(1, 6)]}
        elif "status" in props:
            run.structured = {"status": "ok", "missing": [], "cards": composed_cards()}
        else:
            run.structured = {"cards": composed_cards(body="다시 쓴 본문이에요.")[1:2]}
        if tools:
            run.fetches = self.fetches
            run.searches = [{"query": "코인 실린더", "results": [{"title": "x", "url": "https://other.example/a"}]}]
        return run


@pytest.fixture(autouse=True)
def clear_cooldowns():
    site_policy.COOLDOWN_FILE.unlink(missing_ok=True)


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
    for _ in range(500):
        job = get(client, job_id)
        if job["state"] in states and not job.get("aiTask"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"{states} 대기 실패: {job['state']} {job.get('error')} {job.get('aiError')}")


def blocked_job(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    assert api(client, job_id, "POST", "/start", json=INPUT).status_code == 200
    wait(client, job_id, "waiting_material", "failed", "waiting_outline")
    return job_id


def composed_job(client):
    job_id = blocked_job(client)
    assert api(client, job_id, "POST", "/material", json=MATERIAL).status_code == 200
    wait(client, job_id, "waiting_outline")
    return job_id


def test_failed_fetch_error_format_is_recorded():
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "WebFetch", "input": {"url": SHOP}}]}},
        {"type": "user", "tool_use_result": "Error: Request failed with status code 429", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True, "content": "Request failed with status code 429"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t2", "name": "WebFetch", "input": {"url": "https://ok.example"}}]}},
        {"type": "user", "tool_use_result": {"url": "https://ok.example", "code": 200, "result": "body"}, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t2", "content": "body 500 words"}]}},
    ]
    run = claude_cli.parse_stream("\n".join(json.dumps(x) for x in lines))
    assert run.fetches == [{"url": SHOP, "code": 429}, {"url": "https://ok.example", "code": 200}]


def test_429_does_not_end_job_and_keeps_record(client):
    job = get(client, blocked_job(client))
    assert job["state"] == "waiting_material" and not job["error"]
    failure = job["research"]["fetchFailures"][0]
    assert failure["code"] == 429 and failure["attempts"] == 2 and failure["blocked"] and failure["host"] == "official-shop.example"
    assert job["research"]["queries"] == ["코인 실린더"] and job["research"]["missing"]
    assert job["research"]["retryAfter"] > time.time() + 500
    assert site_policy.cooldown_seconds(SHOP) > 500
    assert job["aiCalls"][0]["kind"] == "research"


def test_research_prompt_forbids_repeated_requests():
    assert "다시 요청하지 않는다" in ai_provider.RESEARCH_SYSTEM


def test_auto_research_is_held_during_cooldown_then_allowed(client, fake):
    job_id = blocked_job(client)
    calls = len(fake.calls)
    r = api(client, job_id, "POST", "/retry")
    assert r.status_code == 409 and "뒤에 다시" in r.json()["detail"]
    assert len(fake.calls) == calls

    site_policy.COOLDOWN_FILE.unlink()
    assert api(client, job_id, "POST", "/retry").status_code == 200
    wait(client, job_id, "waiting_material")
    assert len(fake.calls) == calls + 1


def test_material_is_composed_without_web_tools(client, fake):
    job_id = composed_job(client)
    assert fake.calls[-1]["tools"] == ()
    assert "치이카와 코인 실린더" in fake.calls[-1]["prompt"] and "¥440" in fake.calls[-1]["prompt"]
    job = get(client, job_id)
    assert job["state"] == "waiting_outline" and len(job["outline"]["cards"]) == 5
    assert job["userMaterial"]["price"] == "¥440 (세금 포함)" and job["userMaterial"]["submittedAt"]


def test_each_ai_call_is_recorded_once(client, fake):
    job = get(client, composed_job(client))
    assert [c["kind"] for c in job["aiCalls"]] == ["research", "compose"] and len(fake.calls) == 2


def test_user_material_is_separated_and_never_marked_verified(client):
    job = get(client, composed_job(client))
    research = job["research"]
    user = next(s for s in research["sources"] if s["id"] == "user1")
    assert user["verification"] == "user_provided" and user["origin"] == "user" and user["kind"] == "user" and user["url"] == SHOP
    assert {f["origin"] for f in research["facts"]} == {"user"}
    # 쇼핑몰 주소를 입력해도 AI가 확인한 것으로 바뀌지 않음
    assert research["fetchFailures"][0]["code"] == 429
    assert research["searchPerformed"] is True
    assert ai_provider.card_source_state(job["outline"]["cards"][1], research) == "user_provided"


def test_card_source_text_says_user_provided(client):
    card = get(client, composed_job(client))["outline"]["cards"][1]
    assert card["source"] == "출처: 치이카와 마켓 (사용자 제공)"


def test_user_material_warns_but_allows_approval(client):
    job_id = composed_job(client)
    issues = get(client, job_id)["outline"]["issues"]
    assert not issues["card-02"]["errors"] and any("사용자가 제공한" in w for w in issues["card-02"]["warnings"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_invented_price_is_rewritten_then_blocked(client, fake):
    job_id = blocked_job(client)
    invented = {"status": "ok", "missing": [], "cards": composed_cards(body="가격은 3,300엔이에요.")}
    still = {"cards": composed_cards(body="가격은 3,300엔이에요.")[1:]}
    fake.queue = [invented, still]
    api(client, job_id, "POST", "/material", json={**MATERIAL, "price": ""})
    job = wait(client, job_id, "waiting_outline")
    assert fake.calls[-1]["tools"] == () and "자료에 없는 숫자" in fake.calls[-1]["prompt"]
    assert any("3,300" in e for e in job["outline"]["issues"]["card-02"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409

    # 사용자가 직접 고치면 승인 가능
    for frame in ("card-02", "card-03", "card-04", "card-05"):
        edit = {"role": "소개", "title": "포인트", "body": "아크릴 파츠가 귀여워요.", "source": "출처: 치이카와 마켓 (사용자 제공)"}
        api(client, job_id, "PUT", f"/outline/cards/{frame}", json=edit)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_price_from_material_is_allowed(client, fake):
    job_id = blocked_job(client)
    fake.queue = [{"status": "ok", "missing": [], "cards": composed_cards(body="가격은 ¥440 (세금 포함)이에요.")}]
    api(client, job_id, "POST", "/material", json=MATERIAL)
    job = wait(client, job_id, "waiting_outline")
    assert not any(i["errors"] for i in job["outline"]["issues"].values())


def test_numbers_helper():
    assert unsupported_numbers("3,300엔이고 42mm", "가격 3300엔, 크기 42mm") == []
    assert unsupported_numbers("9,900엔", "가격 3300엔") == ["9,900"]
    assert unsupported_numbers("40엔", "가격 ¥440") == ["40"]
    assert unsupported_numbers("440엔이에요.", "가격 ¥440.") == []


def test_ai_marking_user_url_verified_is_impossible(client, fake):
    job_id = blocked_job(client)
    api(client, job_id, "POST", "/material", json=MATERIAL)
    job = wait(client, job_id, "waiting_outline")
    assert all(s["verification"] != "fetched" for s in job["research"]["sources"] if s["origin"] == "user")


@pytest.mark.parametrize("body, status", [
    ({"name": "이름만"}, 400),
    ({"features": "특징만"}, 400),
    ({"pasted": "짧음"}, 400),
    ({**MATERIAL, "sourceUrl": "javascript:alert(1)"}, 400),
    ({"pasted": "가" * 8001}, 422),
    ({"unknown": "x", **MATERIAL}, 422),
])
def test_material_validation(client, body, status):
    job_id = blocked_job(client)
    assert api(client, job_id, "POST", "/material", json=body).status_code == status
    assert get(client, job_id)["userMaterial"] is None


def test_pasted_text_alone_is_enough(client, fake):
    job_id = blocked_job(client)
    r = api(client, job_id, "POST", "/material", json={"pasted": "치이카와 코인 실린더 ¥440 작은 아크릴 파츠가 포인트!"})
    assert r.status_code == 200
    wait(client, job_id, "waiting_outline")
    assert "<user_material>치이카와 코인 실린더" in fake.calls[-1]["prompt"]


def test_still_insufficient_stays_waiting_for_material(client, fake):
    job_id = blocked_job(client)
    fake.queue = [{"status": "insufficient", "missing": ["판매처가 필요해요"], "cards": []}]
    api(client, job_id, "POST", "/material", json=MATERIAL)
    job = wait(client, job_id, "waiting_material")
    assert job["research"]["missing"] == ["판매처가 필요해요"] and job["userMaterial"]["name"] == MATERIAL["name"]


def test_claude_failure_keeps_material_and_shows_reason(client, fake):
    job_id = blocked_job(client)
    fake.queue = [AIError("limit", "Claude Pro 사용 한도에 도달했어요.")]
    api(client, job_id, "POST", "/material", json=MATERIAL)
    job = wait(client, job_id, "waiting_material")
    assert "사용 한도" in job["aiError"] and job["userMaterial"]["name"] == MATERIAL["name"] and job["outline"] is None


def test_old_failed_job_can_continue_with_material(client, fake):
    job_id = client.post("/api/jobs/draft").json()["id"]
    fake.queue = [AIError("insufficient", "공식 자료가 부족해요")]
    api(client, job_id, "POST", "/start", json=INPUT)
    assert wait(client, job_id, "failed")["research"] is None
    assert api(client, job_id, "POST", "/material", json=MATERIAL).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert job["research"]["searchPerformed"] is False
    assert all(s["verification"] == "user_provided" for s in job["research"]["sources"])


def test_flow_continues_to_png_stage(client, fake):
    job_id = composed_job(client)
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview")
    card = job["preview"]["cards"][1]
    source = next(e["text"] for e in card["spec"]["elements"] if e.get("role") == "source")
    assert "사용자 제공" in source
    assert all(c["tools"] == () for c in fake.calls[1:])
    api(client, job_id, "POST", "/preview/approve")
    assert wait(client, job_id, "done")["preview"]["approved"]


def test_rewrite_keeps_user_label_and_does_not_search(client, fake):
    job_id = composed_job(client)
    api(client, job_id, "POST", "/outline/cards/card-02/regenerate")
    job = wait(client, job_id, "waiting_outline")
    assert fake.calls[-1]["tools"] == ()
    assert job["outline"]["cards"][1]["source"] == "출처: 치이카와 마켓 (사용자 제공)"


def test_material_refused_after_outline_approval(client):
    job_id = composed_job(client)
    api(client, job_id, "POST", "/outline/approve")
    wait(client, job_id, "waiting_preview")
    assert api(client, job_id, "POST", "/material", json=MATERIAL).status_code == 409


def test_demo_job_refuses_material(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    api(client, job_id, "POST", "/start", json={**INPUT, "mode": "demo"})
    wait(client, job_id, "waiting_outline")
    assert api(client, job_id, "POST", "/material", json=MATERIAL).status_code == 409
