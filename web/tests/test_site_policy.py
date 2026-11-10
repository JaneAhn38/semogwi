"""사이트 접근 정책과 출처 검증 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import json
import os
import tempfile
import time

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import ai_provider, claude_cli, jobs, site_policy
from app.ai_provider import card_source_state, material_text, verify_sources
from app.claude_cli import CliRun
from app.main import app

MARKET = "https://chiikawamarket.jp/ko/products/4571609414117"
OTHER = "https://brand-official.example/news/1"
BASE = {"topic": "코인 실린더", "contentType": "goods", "url": "", "mode": "ai"}
MATERIAL = {"name": "코인 실린더", "price": "¥440", "features": "작은 아크릴 파츠", "seller": "치이카와 마켓", "sourceUrl": MARKET, "pasted": ""}


def cards(source_ids, body="작은 파츠가 포인트예요.", source="출처: 브랜드 공식"):
    result = [{"frame": "card-01", "role": "표지", "title": "코인 실린더", "body": "굿즈를 소개해요.", "source": "", "sourceIds": []}]
    for i in range(2, 6):
        result.append({"frame": f"card-0{i}", "role": "소개", "title": f"포인트 {'가나다라'[i - 2]}", "body": body, "source": source, "sourceIds": source_ids})
    return result


def research_data(url=OTHER, kind="official", body="작은 파츠가 포인트예요.", fact="작은 파츠가 포인트"):
    return {"status": "ok", "missing": [], "sources": [{"id": "s1", "title": "브랜드", "url": url, "kind": kind}],
            "facts": [{"text": fact, "sourceIds": ["s1"]}], "cards": cards(["s1"], body=body)}


class Fake:
    def __init__(self):
        self.calls = []
        self.data = research_data()
        self.fetches = [{"url": OTHER, "code": 200}]
        self.searches = [{"query": "q", "results": [{"title": "t", "url": OTHER}]}]

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        self.calls.append({"prompt": prompt, "tools": tools, "disallowed": disallowed})
        run = CliRun(model="m")
        props = schema["properties"]
        if "sources" in props:
            run.structured = self.data
            run.fetches = list(self.fetches)
            run.searches = list(self.searches)
        elif "status" in props:
            run.structured = {"status": "ok", "missing": [], "cards": cards(["user1"], source="출처: 치이카와 마켓")}
        else:
            run.structured = {"cards": []}
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
    for _ in range(400):
        job = get(client, job_id)
        if job["state"] in states and not job.get("aiTask"):
            return job
        time.sleep(0.01)
    raise AssertionError(f"{states}: {job['state']} {job.get('error')} {job.get('aiError')}")


def start(client, **extra):
    job_id = client.post("/api/jobs/draft").json()["id"]
    assert api(client, job_id, "POST", "/start", json={**BASE, **extra}).status_code == 200
    return job_id


# ---------- 금지 사이트 ----------
@pytest.mark.parametrize("url, expected", [
    (MARKET, True), ("https://www.chiikawamarket.jp/x", True), ("https://shop.chiikawamarket.jp/x", True), ("HTTPS://ChiikawaMarket.JP/x", True),
    ("https://notchiikawamarket.jp/x", False), ("https://chiikawamarket.jp.evil.example/x", False), (OTHER, False), ("", False), ("not a url", False),
])
def test_restricted_host_matching(url, expected):
    assert bool(site_policy.restricted_site(url)) is expected


@pytest.mark.parametrize("url", ["https://shop.chiikawamarket.jp/p/1", "https://a.b.chiikawamarket.jp/x", "https://cdn.chiikawamarket.jp./img.png"])
def test_every_subdomain_goes_to_material(client, fake, url):
    job_id = start(client, url=url)
    assert fake.calls == [] and get(client, job_id)["state"] == "waiting_material"


def test_deny_rules_cover_domain_and_all_subdomains(monkeypatch):
    rules = site_policy.deny_rules()
    assert rules[:2] == ["WebFetch(domain:chiikawamarket.jp)", "WebFetch(domain:*.chiikawamarket.jp)"]
    monkeypatch.setattr(site_policy, "cooling_hosts", lambda: ["slow.example"])
    assert site_policy.deny_rules()[2:] == ["WebFetch(domain:slow.example)", "WebFetch(domain:*.slow.example)"]


def test_restricted_subdomain_page_never_counts_as_read():
    url = "https://shop.chiikawamarket.jp/p/1"
    result = verify_sources([{"id": "s", "url": url, "kind": "official"}], CliRun(fetches=[{"url": url, "code": 200}]))
    assert result[0]["verification"] == "restricted"


def test_restricted_url_goes_to_material_without_ai_call(client, fake):
    job_id = start(client, url=MARKET)
    job = get(client, job_id)
    assert fake.calls == []
    assert job["state"] == "waiting_material" and not job["error"]
    assert next(s for s in job["steps"] if s["key"] == "research")["status"] == "skipped"
    stop = job["research"]["policyStops"][0]
    assert stop["domain"] == "chiikawamarket.jp" and "자동화된 수단" in stop["reason"]
    assert job["research"]["searchPerformed"] is False and job["research"]["fetched"] == []


def test_restricted_url_continues_with_user_material_without_web_tools(client, fake):
    job_id = start(client, url=MARKET)
    assert api(client, job_id, "POST", "/material", json=MATERIAL).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == 1 and fake.calls[0]["tools"] == ()
    user = next(s for s in job["research"]["sources"] if s["origin"] == "user")
    assert user["verification"] == "user_provided" and user["url"] == MARKET
    assert job["outline"]["cards"][1]["source"] == "출처: 치이카와 마켓 (사용자 제공)"
    assert not any(i["errors"] for i in job["outline"]["issues"].values())


def test_demo_mode_is_not_affected(client, fake):
    job_id = start(client, url=MARKET, mode="demo")
    assert wait(client, job_id, "waiting_outline")["outline"]["cards"]
    assert fake.calls == []


def test_user_can_ask_for_other_sources_and_market_stays_denied(client, fake):
    job_id = start(client, url=MARKET)
    assert api(client, job_id, "POST", "/retry").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    call = fake.calls[0]
    assert "WebFetch(domain:chiikawamarket.jp)" in call["disallowed"] and "WebFetch(domain:*.chiikawamarket.jp)" in call["disallowed"]
    assert "읽지 않는다" in call["prompt"] and "먼저 한 번만 읽는다" not in call["prompt"]
    assert job["research"]["policyStops"] and job["research"]["sources"][0]["verification"] == "fetched"


def test_every_research_call_denies_restricted_sites(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    assert "WebFetch(domain:chiikawamarket.jp)" in fake.calls[0]["disallowed"] and "치이카와 마켓" in fake.calls[0]["prompt"]


def test_restricted_page_never_counts_as_read_even_if_recorded():
    parsed = CliRun(fetches=[{"url": MARKET, "code": 200}])
    result = verify_sources([{"id": "s", "title": "마켓", "url": MARKET, "kind": "official"}], parsed)
    assert result[0]["verification"] == "restricted"
    assert card_source_state({"sourceIds": ["s"]}, {"sources": result}) == "unverified"


def test_other_sites_keep_automatic_research(client, fake):
    job_id = start(client, url=OTHER)
    job = wait(client, job_id, "waiting_outline")
    assert set(fake.calls[0]["tools"]) == {"WebSearch", "WebFetch"} and "먼저 한 번만 읽는다" in fake.calls[0]["prompt"]
    assert not any(i["errors"] for i in job["outline"]["issues"].values())
    assert any("AI의 판단" in w for w in job["outline"]["issues"]["card-02"]["warnings"])


def test_cli_passes_deny_rules(monkeypatch, tmp_path):
    seen = {}

    class Done:
        returncode = 0
        stderr = ""
        stdout = json.dumps({"type": "result", "subtype": "success", "structured_output": {"a": 1}})

    def fake_run(args, **kwargs):
        seen["args"] = args
        return Done()

    monkeypatch.setattr(claude_cli, "status", lambda force=False: {"available": True, "reason": ""})
    monkeypatch.setattr(claude_cli, "_executable", lambda: "claude")
    monkeypatch.setattr(claude_cli, "WORK_DIR", tmp_path)
    monkeypatch.setattr(claude_cli.subprocess, "run", fake_run)
    claude_cli.run("p", "s", {}, tools=("WebFetch",), disallowed=("WebFetch(domain:a.example)", "WebFetch(domain:b.example)"))
    index = seen["args"].index("--disallowedTools")
    assert seen["args"][index + 1:index + 3] == ["WebFetch(domain:a.example)", "WebFetch(domain:b.example)"]


# ---------- 출처 구분 ----------
def test_search_listing_is_not_a_verified_source():
    parsed = CliRun(searches=[{"query": "q", "results": [{"title": "t", "url": OTHER}]}])
    sources = verify_sources([{"id": "s", "title": "t", "url": OTHER, "kind": "official"}], parsed)
    assert sources[0]["verification"] == "search_result"
    assert card_source_state({"sourceIds": ["s"]}, {"sources": sources}) == "listed"


def test_goods_card_with_only_search_listing_is_blocked(client, fake):
    fake.fetches = []
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    assert any("검색 목록에 주소만" in e for e in job["outline"]["issues"]["card-02"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


def test_character_card_with_only_search_listing_warns(client, fake):
    fake.fetches = []
    job_id = start(client, contentType="character")
    job = wait(client, job_id, "waiting_outline")
    issue = job["outline"]["issues"]["card-02"]
    assert not issue["errors"] and any("검색 목록에 주소만" in w for w in issue["warnings"])


def test_goods_card_with_read_secondary_source_is_blocked(client, fake):
    fake.data = research_data(kind="secondary")
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    assert any("공식 출처가 아니에요" in e for e in job["outline"]["issues"]["card-02"]["errors"])


def test_failed_page_is_not_read(client, fake):
    fake.fetches = [{"url": OTHER, "code": 404}]
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    assert job["research"]["sources"][0]["verification"] == "search_result"


def test_registered_official_is_marked_and_ai_claim_is_not(monkeypatch):
    monkeypatch.setitem(site_policy._policy, "official", [{"domain": "brand-official.example", "name": "브랜드", "checked": "확인"}])
    parsed = CliRun(fetches=[{"url": OTHER, "code": 200}, {"url": "https://ai-says.example", "code": 200}])
    result = verify_sources([{"id": "a", "url": OTHER, "kind": "secondary"}, {"id": "b", "url": "https://ai-says.example", "kind": "official"}], parsed)
    assert (result[0]["kind"], result[0]["officialBasis"]) == ("official", "registered")
    assert (result[1]["kind"], result[1]["officialBasis"]) == ("official", "ai")


def test_numbers_only_match_read_pages_and_user_material():
    research = {"sources": [{"id": "read", "verification": "fetched"}, {"id": "listed", "verification": "search_result"}],
                "facts": [{"text": "가격 440엔", "sourceIds": ["read"]}, {"text": "가격 999엔", "sourceIds": ["listed"]}]}
    text = material_text(research, {"price": "¥550", "submittedAt": "2026-11-06"})
    assert "440" in text and "550" in text and "999" not in text and "2026" not in text


def test_price_from_unread_page_is_blocked(client, fake):
    fake.fetches = []
    fake.data = research_data(body="가격은 999엔이에요.", fact="가격 999엔")
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    assert any("999" in e for e in job["outline"]["issues"]["card-02"]["errors"])


def test_compose_keeps_only_facts_from_read_pages(client, fake):
    fake.data = {"status": "insufficient", "missing": ["가격"], "cards": [],
                 "sources": [{"id": "read", "title": "읽음", "url": OTHER, "kind": "official"}, {"id": "listed", "title": "목록", "url": "https://listed.example/a", "kind": "official"}],
                 "facts": [{"text": "읽은 사실", "sourceIds": ["read"]}, {"text": "목록 사실", "sourceIds": ["listed"]}]}
    fake.searches = [{"query": "q", "results": [{"title": "t", "url": "https://listed.example/a"}]}]
    job_id = start(client)
    wait(client, job_id, "waiting_material")
    api(client, job_id, "POST", "/material", json=MATERIAL)
    job = wait(client, job_id, "waiting_outline")
    texts = [f["text"] for f in job["research"]["facts"]]
    assert "읽은 사실" in texts and "목록 사실" not in texts
    assert "목록 사실" not in fake.calls[-1]["prompt"]


# ---------- 접속 실패와 대기 ----------
@pytest.mark.parametrize("code, retry_after, blocked, cooldown, word", [
    (429, 60, True, site_policy.MIN_RATE_LIMIT_WAIT, "요청"),
    (429, 1800, True, 1800, "요청"),
    (429, None, True, site_policy.DEFAULT_RATE_LIMIT_WAIT, "요청"),
    (503, None, True, site_policy.DEFAULT_RATE_LIMIT_WAIT, "일시"),
    (403, None, True, site_policy.ACCESS_DENIED_WAIT, "허용"),
    (402, None, True, site_policy.ACCESS_DENIED_WAIT, "허용"),
    (404, None, False, 0, "없어요"),
    (500, None, False, site_policy.SERVER_ERROR_WAIT, "오류"),
    (0, None, False, site_policy.SERVER_ERROR_WAIT, "접속"),
])
def test_failure_classification(code, retry_after, blocked, cooldown, word):
    result = site_policy.classify_failure(code, retry_after)
    assert result["blocked"] is blocked and result["cooldown"] == cooldown and word in result["label"]


def test_real_429_format_reads_retry_after():
    # 세션 기록에 남은 실제 형식
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "WebFetch", "input": {"url": OTHER}}]}},
        {"type": "user", "tool_use_result": {"url": OTHER, "code": 429, "bytes": 0, "result": ""}, "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "The server returned HTTP 429 Too Many Requests. Retry-After: 60\n\nThe response body was not retrieved."}]}},
    ]
    assert claude_cli.parse_stream("\n".join(json.dumps(x) for x in lines)).fetches == [{"url": OTHER, "code": 429, "retryAfter": 60}]


def test_denied_fetch_is_not_reported_as_site_failure():
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t", "name": "WebFetch", "input": {"url": MARKET}}]}},
        # 2026-11-09 실제 호출(v2.1.319)에서 기록된 형식
        {"type": "user", "tool_use_result": "Error: WebFetch denied access to domain:shop.chiikawamarket.jp.", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "is_error": True, "content": "WebFetch denied access to domain:shop.chiikawamarket.jp."}]}},
    ]
    parsed = claude_cli.parse_stream("\n".join(json.dumps(x) for x in lines))
    assert parsed.fetches[0].get("denied") is True and ai_provider.fetch_failures(parsed) == []


def test_cooldown_is_shared_across_jobs(client, fake):
    fake.fetches = [{"url": OTHER, "code": 429, "retryAfter": 60}]
    fake.data = {"status": "insufficient", "missing": ["자료"], "sources": [], "facts": [], "cards": []}
    first = start(client, url=OTHER)
    wait(client, first, "waiting_material")
    assert site_policy.cooldown_seconds(OTHER) >= site_policy.MIN_RATE_LIMIT_WAIT - 5

    # 새 작업을 만들어도 그 사이트는 차단 규칙으로 막고 프롬프트에서 읽지 말라고 합니다
    fake.fetches = []
    second = start(client, url=OTHER)
    wait(client, second, "waiting_material")
    call = fake.calls[-1]
    assert "WebFetch(domain:brand-official.example)" in call["disallowed"] and "읽지 않는다" in call["prompt"]
    assert get(client, second)["research"]["retryAfter"] > time.time()

    # 재조사도 대기 중에는 거절
    r = api(client, second, "POST", "/retry")
    assert r.status_code == 409 and "기다리는 중" in r.json()["detail"]


def test_cooldown_expires_and_old_entries_are_dropped(client):
    site_policy.COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    site_policy.COOLDOWN_FILE.write_text(json.dumps({"old.example": {"until": 1, "code": 429}, "live.example": {"until": int(time.time()) + 99, "code": 429}}), encoding="utf-8")
    assert site_policy.cooling_hosts() == ["live.example"]
    assert site_policy.cooldown_seconds("https://old.example/a") == 0
    site_policy.record_failures([{"host": "new.example", "cooldown": 50, "code": 429}])
    stored = json.loads(site_policy.COOLDOWN_FILE.read_text(encoding="utf-8"))
    assert set(stored) == {"live.example", "new.example"}


def test_shorter_failure_does_not_shorten_cooldown():
    site_policy.record_failures([{"host": "a.example", "cooldown": 3600, "code": 403}])
    first = site_policy.cooldown_until("https://a.example")
    site_policy.record_failures([{"host": "a.example", "cooldown": 300, "code": 500}])
    assert site_policy.cooldown_until("https://a.example") == first


def test_broken_cooldown_file_is_ignored():
    site_policy.COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    site_policy.COOLDOWN_FILE.write_text("{broken", encoding="utf-8")
    assert site_policy.cooling_hosts() == [] and site_policy.cooldown_seconds(OTHER) == 0


def test_options_list_restricted_sites(client):
    sites = client.get("/api/options").json()["restrictedSites"]
    assert sites == [{"domain": "chiikawamarket.jp", "name": "치이카와 마켓"}]


def test_team_files_are_documented():
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "docs" / "site-access-policy.md").read_text(encoding="utf-8")
    assert "fetch_product.py" in text and "cardnews.md" in text and "상품 페이지상의 정보 취득" in text
