"""실제 AI 흐름 테스트. claude를 호출하지 않고 결과를 흉내 내어 검증합니다 (Pro 한도를 쓰지 않음)."""

import json
import os
import tempfile
import time

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, design, jobs
from app.ai_provider import canonical_url, verify_sources
from app.claude_cli import AIError, CliRun
from app.layout import LayoutError
from app.main import app

PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x03\x20\0\0\x03\x20" + b"\0" * 32
THEME = {"name": "복숭아 구름", "rationale": "말랑한 분위기", "displayFont": "Jua", "bodyFont": "Gowun Dodum",
         "palette": {"bgFrom": "#FFE9EF", "bgTo": "#FFF6E5", "ink": "#3A2433", "inkSoft": "#5C4152", "accent": "#FFB3C8", "accent2": "#BDE7DC", "accent3": "#FFE08A", "panel": "#FFFFFF"}}
WIKI = "https://ko.wikipedia.org/wiki/치이카와"
INPUT = {"topic": "치이카와 캐릭터 소개", "contentType": "character", "url": "", "mode": "ai"}


def research_result(url=WIKI, kind="secondary", status="ok"):
    cards = [{"frame": "card-01", "role": "표지", "title": "치이카와 친구들", "body": "귀여운 친구들을 만나 봐요.", "source": "", "sourceIds": []}]
    for i, name in enumerate(["치이카와", "하치와레", "우사기", "모몽가"], 2):
        cards.append({"frame": f"card-0{i}", "role": "캐릭터", "title": name, "body": f"'{name}'는 귀여운 친구예요.", "source": "출처: 위키백과", "sourceIds": ["s1"]})
    return {"status": status, "missing": ["공식 공지"] if status != "ok" else [], "facts": [{"text": "사실", "sourceIds": ["s1"]}],
            "sources": [{"id": "s1", "title": "위키백과", "url": url, "kind": kind}], "cards": cards}


def card_spec(frame, seed=0, image=None):
    elements = [{"type": "shape", "kind": "blob", "box": {"x": -60, "y": -60, "w": 300, "h": 300}, "color": "accent", "opacity": 0.5, "rotate": 0},
                {"type": "text", "role": "page", "box": {"x": 860, "y": 60, "w": 150, "h": 44}, "font": "body", "size": 26, "color": "inkSoft", "align": "right", "valign": "top"},
                {"type": "text", "role": "source", "box": {"x": 70, "y": 60, "w": 600, "h": 44}, "font": "body", "size": 26, "color": "inkSoft", "align": "left", "valign": "top"},
                {"type": "text", "role": "title", "box": {"x": 80, "y": 200 + seed * 110, "w": 900, "h": 150}, "font": "display", "size": 96, "color": "ink", "align": "left", "valign": "top"},
                {"type": "text", "role": "body", "box": {"x": 80, "y": 400 + seed * 110, "w": 900, "h": 260}, "font": "body", "size": 44, "color": "ink", "align": "left", "valign": "top"}]
    if image:
        elements.append({"type": "image", "imageRef": image, "box": {"x": 200, "y": 1000, "w": 600, "h": 300}, "radius": 30})
    return {"frame": frame, "layoutLabel": f"구성 {frame[-1]}-{seed}", "background": {"start": "bgFrom", "end": "bgTo", "angle": 120}, "elements": elements}


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.queue = []
        self.search_urls = [WIKI]

    def __call__(self, prompt, system, schema, *, tools=(), model="sonnet", effort="medium", timeout=300, budget_usd=1.0, disallowed=()):
        self.calls.append({"prompt": prompt, "tools": tools, "schema": schema, "disallowed": disallowed})
        if self.queue:
            item = self.queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return self._wrap(item, tools)
        return self._wrap(self._default(prompt, schema), tools)

    def _wrap(self, data, tools):
        run = CliRun(structured=data, model="claude-sonnet", turns=2, duration_ms=10, estimated_usd=0.01, five_hour_utilization=0.5)
        if tools:
            run.searches = [{"query": "치이카와", "results": [{"title": "t", "url": u} for u in self.search_urls]}]
        return run

    def _default(self, prompt, schema):
        props = schema["properties"]
        if "status" in props:
            return research_result()
        if "theme" in props:
            image = "img1" if "img1" in prompt else None
            return {"theme": THEME, "cards": [card_spec(f"card-0{i}", i - 1, image if i == 1 else None) for i in range(1, 6)]}
        if "elements" in json.dumps(props):
            frame = next(f"card-0{i}" for i in range(1, 6) if f"card-0{i}의 명세만" in prompt)
            return {"cards": [card_spec(frame, 3, "img1" if "img1" in prompt else None)]}
        frames = [f"card-0{i}" for i in range(1, 6) if f"card-0{i}" in prompt.split("다시 쓸 카드:")[-1]]
        return {"cards": [{"frame": f, "role": "새 역할", "title": "다시 쓴 제목", "body": "다시 쓴 본문이에요.", "source": "출처: 위키백과", "sourceIds": ["s1"]} for f in frames]}


@pytest.fixture
def fake(monkeypatch):
    claude = FakeClaude()
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
    raise AssertionError(f"{states} 대기 실패: {job['state']} {job.get('error')}")


def outline(client, images=0):
    job_id = client.post("/api/jobs/draft").json()["id"]
    for i in range(images):
        api(client, job_id, "POST", "/assets", data={"rights": "허가됨", "source": "직접 촬영"}, files={"image": (f"p{i}.png", PNG, "image/png")})
    assert api(client, job_id, "POST", "/start", json=INPUT).status_code == 200
    wait(client, job_id, "waiting_outline", "failed")
    return job_id


def preview(client, images=0):
    job_id = outline(client, images)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    wait(client, job_id, "waiting_preview")
    return job_id


def text_of(card, role):
    return next((e["text"] for e in card["spec"]["elements"] if e.get("role") == role), None)


# ---------- CLI 출력 해석 ----------
def test_parse_stream_reads_real_tool_records():
    lines = [
        {"type": "system", "subtype": "init", "model": "m"},
        {"type": "user", "tool_use_result": {"query": "q", "results": [{"tool_use_id": "x", "content": [{"title": "A", "url": "https://a.example/x"}]}, "요약 텍스트"], "searchCount": 1}},
        {"type": "user", "tool_use_result": {"url": "https://a.example/x", "code": 200, "bytes": 1, "result": "본문"}},
        {"type": "user", "tool_use_result": "Structured output provided successfully"},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "resetsAt": 100, "unifiedWindows": {"five_hour": {"utilization": 0.47}}}},
        {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "structured_output": {"a": 1}, "total_cost_usd": 0.5, "duration_ms": 9},
    ]
    run = claude_cli.parse_stream("\n".join(json.dumps(x) for x in lines) + "\nnot json")
    assert run.structured == {"a": 1} and run.five_hour_utilization == 0.47
    assert run.searches == [{"query": "q", "results": [{"title": "A", "url": "https://a.example/x"}]}]
    assert run.fetches == [{"url": "https://a.example/x", "code": 200}]


@pytest.mark.parametrize("run, kind", [
    (CliRun(is_error=True, api_error_status=429, resets_at=1800000000), "limit"),
    (CliRun(is_error=True, result_text="You've hit your session limit"), "limit"),
    (CliRun(rate_status="rejected"), "limit"),
    (CliRun(is_error=True, result_text="Not logged in · Please run /login"), "auth"),
    (CliRun(is_error=True, api_error_status=401), "auth"),
    (CliRun(is_error=True, subtype="error_max_structured_output_retries"), "invalid"),
    (CliRun(is_error=True, subtype="error_during_execution"), "error"),
])
def test_errors_are_classified(run, kind):
    assert claude_cli._classify(run, "", 1).kind == kind


def test_cli_removes_api_billing_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-used")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "should-not-be-used")
    env = claude_cli._clean_env()
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env


def test_status_refuses_non_subscription_login(monkeypatch):
    class Done:
        stdout = json.dumps({"loggedIn": True, "authMethod": "console"})

    monkeypatch.setattr(claude_cli, "_executable", lambda: "claude")
    monkeypatch.setattr(claude_cli.subprocess, "run", lambda *a, **k: Done())
    assert claude_cli._read_status()["available"] is False


# ---------- 출처 검증 ----------
def test_canonical_url():
    assert canonical_url("https://www.Example.com/a/?utm_source=x#top") == canonical_url("http://example.com/a")
    assert canonical_url("javascript:alert(1)") == ""


def test_sources_verified_only_from_tool_records():
    parsed = CliRun(searches=[{"query": "q", "results": [{"title": "t", "url": "https://a.example/1"}]}], fetches=[{"url": "https://b.example/2", "code": 200}, {"url": "https://c.example/3", "code": 404}])
    result = verify_sources([{"id": "1", "url": "https://a.example/1/"}, {"id": "2", "url": "https://b.example/2"}, {"id": "3", "url": "https://c.example/3"},
                             {"id": "4", "url": "https://made-up.example"}, {"id": "5", "url": "javascript:alert(1)"}], parsed)
    assert [s["verification"] for s in result] == ["search_result", "fetched", "unverified", "unverified", "unverified"]
    assert result[4]["url"] == ""


def test_invented_url_is_not_marked_verified(client, fake):
    fake.queue = [research_result(url="https://made-up.example/page")]
    job = get(client, outline(client))
    assert job["research"]["sources"][0]["verification"] == "unverified"
    assert any("확인하지 못했어요" in w for w in job["outline"]["issues"]["card-02"]["warnings"])


def test_no_search_means_not_performed(client, fake, monkeypatch):
    original = fake._wrap

    def no_search(data, tools):
        run = original(data, tools)
        run.searches = []
        return run

    monkeypatch.setattr(fake, "_wrap", no_search)
    job = get(client, outline(client))
    assert job["research"]["searchPerformed"] is False and job["research"]["sources"][0]["verification"] == "unverified"


def test_goods_requires_verified_official_source_until_user_edits(client, fake):
    fake.queue = [research_result(url="https://made-up.example/page")]
    job_id = client.post("/api/jobs/draft").json()["id"]
    api(client, job_id, "POST", "/start", json={**INPUT, "contentType": "goods"})
    job = wait(client, job_id, "waiting_outline")
    assert job["outline"]["issues"]["card-02"]["errors"]
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


def test_character_rules_and_limits_are_sent_to_ai(client, fake):
    outline(client)
    call = fake.calls[0]
    assert set(call["tools"]) == {"WebSearch", "WebFetch"} and "치이카와 캐릭터 소개" in call["prompt"] and "캐릭터 한 명" in call["prompt"]


# ---------- 조사·구성안 ----------
def test_ai_outline_is_marked_real_and_keeps_sources(client, fake):
    job = get(client, outline(client))
    assert job["mode"] == "ai" and job["demo"] is False
    assert all(s["mode"] == "real" for s in job["steps"])
    assert job["outline"]["cards"][1]["sourceIds"] == ["s1"]
    assert job["research"]["searchPerformed"] and job["research"]["queries"] == ["치이카와"]
    assert job["aiCalls"][0]["kind"] == "research" and job["aiUsage"]["fiveHourUtilization"] == 0.5


def test_failure_never_falls_back_to_demo(client, fake):
    fake.queue = [AIError("limit", "Claude Pro 사용 한도에 도달했어요.")]
    job_id = outline(client)
    job = get(client, job_id)
    assert job["state"] == "failed" and "사용 한도" in job["error"] and job["outline"] is None
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409

    # 다시 시도하면 이어서 진행
    assert api(client, job_id, "POST", "/retry").status_code == 200
    assert wait(client, job_id, "waiting_outline")["outline"]["cards"][0]["title"] == "치이카와 친구들"


def test_insufficient_official_info_waits_for_material(client, fake):
    fake.queue = [research_result(status="insufficient")]
    job_id = client.post("/api/jobs/draft").json()["id"]
    api(client, job_id, "POST", "/start", json=INPUT)
    job = wait(client, job_id, "waiting_material")
    assert job["research"]["missing"] == ["공식 공지"] and job["outline"] is None and not job["error"]


def test_long_title_gets_one_rewrite_without_search(client, fake):
    bad = research_result()
    bad["cards"][1]["title"] = "가" * 30
    fake.queue = [bad]
    job = get(client, outline(client))
    assert len(fake.calls) == 2 and fake.calls[1]["tools"] == ()
    assert job["outline"]["cards"][1]["title"] == "다시 쓴 제목"
    assert not job["outline"]["issues"]["card-02"]["errors"]


def test_regenerate_reuses_research_without_search(client, fake):
    job_id = outline(client)
    before = len(fake.calls)
    assert api(client, job_id, "POST", "/outline/cards/card-03/regenerate").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == before + 1 and fake.calls[-1]["tools"] == ()
    assert job["outline"]["cards"][2]["title"] == "다시 쓴 제목" and job["outline"]["cards"][1]["title"] == "치이카와"
    api(client, job_id, "POST", "/outline/regenerate")
    job = wait(client, job_id, "waiting_outline")
    assert job["outline"]["version"] == 2 and fake.calls[-1]["tools"] == ()


# ---------- 디자인 ----------
def test_design_is_ai_generated_with_server_text(client, fake):
    job = get(client, preview(client))
    assert job["designTheme"]["source"] == "ai" and job["designTheme"]["label"] == "복숭아 구름"
    cards = job["preview"]["cards"]
    assert text_of(cards[1], "title") == "치이카와" and text_of(cards[1], "body") == "'치이카와'는 귀여운 친구예요."
    assert text_of(cards[0], "source") is None  # 표지의 빈 출처는 넣지 않음
    assert len({design.layout_signature(c["spec"]) for c in cards}) == 5
    assert all(c["layoutName"].startswith("구성") for c in cards)


def test_user_edit_reaches_design_and_ai_cannot_change_text(client, fake):
    job_id = outline(client)
    edit = {"role": "내 역할", "title": "내가 쓴 제목", "body": "내가 쓴 본문이에요.", "source": "출처: 직접 확인"}
    api(client, job_id, "PUT", "/outline/cards/card-02", json=edit)
    api(client, job_id, "POST", "/outline/approve")
    card = wait(client, job_id, "waiting_preview")["preview"]["cards"][1]
    assert text_of(card, "title") == "내가 쓴 제목" and text_of(card, "source") == "출처: 직접 확인"
    assert "내가 쓴 제목" in fake.calls[-1]["prompt"]


def test_design_failure_shows_reason_and_can_retry(client, fake):
    job_id = outline(client)
    fake.queue = [AIError("timeout", "AI 응답이 끝나지 않았어요.")]
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "failed")
    assert "끝나지 않았어요" in job["error"] and job["preview"] is None
    api(client, job_id, "POST", "/retry")
    assert wait(client, job_id, "waiting_preview")["preview"]["cards"]


def test_invalid_card_is_retried_alone(client, fake):
    job_id = outline(client)
    bad = {"theme": THEME, "cards": [card_spec(f"card-0{i}", i) for i in range(1, 6)]}
    bad["cards"][2]["elements"][3]["box"] = dict(bad["cards"][2]["elements"][4]["box"])  # 제목과 본문 겹침
    fake.queue = [bad]
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview")
    assert "card-03의 명세만" in fake.calls[-1]["prompt"] and "겹칩니다" in fake.calls[-1]["prompt"]
    assert job["preview"]["cards"][2]["layoutName"] == "구성 3-3"


def test_design_invalid_twice_fails_without_demo(client, fake):
    job_id = outline(client)
    bad = card_spec("card-03", 3)
    bad["elements"][3]["box"] = dict(bad["elements"][4]["box"])
    fake.queue = [{"theme": THEME, "cards": [card_spec(f"card-0{i}", i) if i != 3 else bad for i in range(1, 6)]}, {"cards": [bad]}]
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "failed")
    assert "검증을 통과하지 못했어요" in job["error"] and job["preview"] is None


def test_redesign_changes_only_that_card_and_records_request(client, fake):
    job_id = preview(client)
    before = get(client, job_id)["preview"]["cards"]
    r = api(client, job_id, "POST", "/preview/cards/card-03/ai-redesign", json={"text": "제목을 위쪽으로 이동해 줘."})
    assert r.status_code == 200
    job = wait(client, job_id, "waiting_preview")
    assert "제목을 위쪽으로" in fake.calls[-1]["prompt"] and fake.calls[-1]["tools"] == ()
    after = job["preview"]["cards"]
    assert after[2]["spec"] != before[2]["spec"] and text_of(after[2], "title") == text_of(before[2], "title")
    assert after[0] == before[0] and after[1] == before[1] and after[3] == before[3] and after[4] == before[4]
    assert job["designRequests"]["card-03"][0]["status"] == "반영됨"
    assert after[2]["previous"]["spec"] == before[2]["spec"]

    restored = api(client, job_id, "POST", "/preview/cards/card-03/restore").json()
    assert restored["preview"]["cards"][2]["spec"] == before[2]["spec"]


def test_redesign_failure_keeps_current_card(client, fake):
    job_id = preview(client)
    before = get(client, job_id)["preview"]["cards"]
    fake.queue = [AIError("limit", "Claude Pro 사용 한도에 도달했어요.")]
    api(client, job_id, "POST", "/preview/cards/card-02/ai-redesign", json={"text": "장식을 줄여 줘."})
    job = wait(client, job_id, "waiting_preview")
    assert job["preview"]["cards"] == before and "사용 한도" in job["aiError"]
    assert job["designRequests"]["card-02"][0]["status"] == "실패"


def test_cover_can_be_redesigned_in_ai_mode(client, fake):
    job_id = preview(client)
    assert api(client, job_id, "POST", "/preview/cards/card-01/regenerate").status_code == 200
    assert wait(client, job_id, "waiting_preview")["preview"]["cards"][0]["layoutName"] == "구성 1-3"


def test_approvals_and_no_ai_call_after_final_approval(client, fake):
    job_id = preview(client)
    api(client, job_id, "POST", "/preview/approve")
    job = wait(client, job_id, "done")
    assert job["preview"]["approved"] and job["preview"]["approvalHash"]
    calls = len(fake.calls)
    for _ in range(3):
        get(client, job_id)
    assert len(fake.calls) == calls and get(client, job_id)["preview"]["cards"] == job["preview"]["cards"]

    # 디자인 변경: 디자인 승인만 해제
    api(client, job_id, "POST", "/preview/cards/card-02/ai-redesign", json={"text": "본문 가독성을 높여 줘."})
    job = wait(client, job_id, "waiting_preview")
    assert not job["preview"]["approved"] and job["outline"]["approved"]
    api(client, job_id, "POST", "/preview/approve")
    wait(client, job_id, "done")

    # 구성안 변경: 둘 다 해제, 레이아웃에 들어가면 AI를 다시 부르지 않음
    calls = len(fake.calls)
    edit = {"role": "소개", "title": "고친 제목", "body": "고친 본문이에요.", "source": "출처: 위키백과"}
    job = api(client, job_id, "PUT", "/outline/cards/card-04", json=edit).json()
    assert job["state"] == "waiting_outline" and not job["outline"]["approved"] and not job["preview"]["approved"]
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview")
    assert len(fake.calls) == calls and text_of(job["preview"]["cards"][3], "title") == "고친 제목"


def test_changed_text_that_does_not_fit_redesigns_only_that_card(client, fake):
    job_id = preview(client)
    calls = len(fake.calls)
    edit = {"role": "소개", "title": "가나다라마바사아자차카타파하가나다라마바", "body": "가" * 80, "source": "출처: 위키백과"}
    api(client, job_id, "PUT", "/outline/cards/card-04", json=edit)
    # 제목 칸이 작은 명세로 바꿔 넘치게 합니다
    job = get(client, job_id)
    for el in job["preview"]["cards"][3]["spec"]["elements"]:
        if el.get("role") == "title":
            el["box"].update(h=90, w=300)
    jobs.save(job)
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview", "failed")
    assert job["state"] == "waiting_preview" and len(fake.calls) == calls + 1 and "card-04의 명세만" in fake.calls[-1]["prompt"]


def test_images_are_passed_and_user_choice_is_respected(client, fake):
    job_id = preview(client, 1)
    job = get(client, job_id)
    asset = job["assets"][0]["id"]
    assert job["cardImages"]["card-01"] == {"assetId": asset, "variant": "original"} and job["cardImages"]["card-02"] is None
    assert '"imageRef": "img1"' in fake.calls[-1]["prompt"] and '"width": 800' in fake.calls[-1]["prompt"]

    before = job["preview"]["cards"][0]["spec"]
    calls = len(fake.calls)
    # 이미지 빼기: 이 카드만 AI가 글 중심으로 다시 구성
    api(client, job_id, "PUT", "/preview/cards/card-01/image", json={"assetId": None})
    job = wait(client, job_id, "waiting_preview")
    assert len(fake.calls) == calls + 1 and job["cardImages"]["card-01"] is None
    assert not [e for e in job["preview"]["cards"][0]["spec"]["elements"] if e["type"] == "image"]
    assert job["preview"]["cards"][0]["previous"]["spec"] == before

    # 이미지 넣기
    api(client, job_id, "PUT", "/preview/cards/card-02/image", json={"assetId": asset, "variant": "original"})
    job = wait(client, job_id, "waiting_preview")
    assert job["cardImages"]["card-02"]["assetId"] == asset
    assert [e for e in job["preview"]["cards"][1]["spec"]["elements"] if e["type"] == "image"][0]["assetId"] == asset


def test_blocked_while_ai_task_runs(client, fake):
    job_id = preview(client)
    job = get(client, job_id)
    job["aiTask"] = {"kind": "redesign", "frame": "card-02", "startedAt": "x"}
    jobs.save(job)
    jobs._ai_tasks[job_id] = object()
    try:
        assert api(client, job_id, "POST", "/preview/approve").status_code == 409
    finally:
        jobs._ai_tasks.pop(job_id)
    # 서버가 다시 켜진 경우: 작업 표시를 지우고 알림
    job = get(client, job_id)
    assert job["aiTask"] is None and "중단" in job["aiError"]


def test_start_refuses_ai_when_not_logged_in(client, monkeypatch):
    monkeypatch.setattr(claude_cli, "status", lambda force=False: {"available": False, "reason": "로그인되어 있지 않아요."})
    job_id = client.post("/api/jobs/draft").json()["id"]
    r = api(client, job_id, "POST", "/start", json=INPUT)
    assert r.status_code == 409 and "로그인" in r.json()["detail"]
    assert get(client, job_id)["state"] == "draft"


# ---------- 디자인 검증 ----------
CARD = {"frame": "card-02", "role": "소개", "title": "치이카와", "body": "본문 문장이에요.", "source": "출처: 위키백과"}


def theme():
    return design.clean_theme(THEME)


def finalize(raw, card=CARD):
    return design.finalize_card(raw, card, theme())


def test_low_contrast_ink_is_fixed():
    fixed = design.clean_theme({**THEME, "palette": {**THEME["palette"], "ink": "#FFC0D0", "inkSoft": "#FFD0E0"}})
    for key in ("ink", "inkSoft"):
        for surface in ("bgFrom", "bgTo", "panel"):
            assert design.contrast(design._rgb(fixed["palette"][key]), design._rgb(fixed["palette"][surface])) >= 4.5


def test_bad_palette_rejected():
    with pytest.raises(LayoutError):
        design.clean_theme({**THEME, "palette": {**THEME["palette"], "ink": "red"}})


def test_unknown_font_uses_allowed_font():
    assert design.clean_theme({**THEME, "displayFont": "Comic Sans"})["fonts"]["display"] in design.DISPLAY_FONTS


def test_small_text_and_margins_are_fixed():
    raw = card_spec("card-02")
    raw["elements"][4]["size"] = 12
    raw["elements"][3]["box"]["x"] = 0
    spec = finalize(raw)
    by_role = {e["role"]: e for e in spec["elements"] if e["type"] == "text"}
    assert by_role["body"]["size"] >= design.MIN_BODY and by_role["title"]["box"]["x"] >= design.SAFE_MARGIN


def test_text_is_always_from_approved_card():
    raw = card_spec("card-02")
    raw["elements"][3]["text"] = "AI가 바꾼 제목"
    spec = finalize(raw)
    assert next(e for e in spec["elements"] if e.get("role") == "title")["text"] == "치이카와"


def test_overlap_is_rejected():
    raw = card_spec("card-02")
    raw["elements"][3]["box"] = dict(raw["elements"][4]["box"])
    with pytest.raises(LayoutError):
        finalize(raw)


def test_text_that_cannot_fit_is_rejected():
    raw = card_spec("card-02")
    raw["elements"][3]["box"] = {"x": 80, "y": 200, "w": 200, "h": 60}
    raw["elements"][4]["box"]["y"] = 270
    with pytest.raises(LayoutError):
        finalize(raw, {**CARD, "title": "가" * 20})


def test_box_grows_into_free_space_instead_of_failing():
    raw = card_spec("card-02")
    raw["elements"][4]["box"]["h"] = 50
    spec = finalize(raw, {**CARD, "body": "가나다라마바 " * 10})
    body = next(e for e in spec["elements"] if e.get("role") == "body")
    assert body["box"]["h"] > 50 and body["box"]["y"] + body["box"]["h"] <= 1350 - design.SAFE_MARGIN


def test_missing_required_text_is_rejected():
    raw = card_spec("card-02")
    raw["elements"] = [e for e in raw["elements"] if e.get("role") != "body"]
    with pytest.raises(LayoutError):
        finalize(raw)


def test_decoration_over_text_is_softened_and_drawn_below():
    raw = card_spec("card-02")
    raw["elements"].append({"type": "shape", "kind": "circle", "box": {"x": 80, "y": 200, "w": 300, "h": 200}, "color": "accent", "opacity": 1.0, "rotate": 700})
    raw["palette"] = None
    t = design.clean_theme({**THEME, "palette": {**THEME["palette"], "accent": "#3A2433"}})
    spec = design.finalize_card(raw, CARD, t)
    types = [e["type"] for e in spec["elements"]]
    assert types.index("text") > max(i for i, k in enumerate(types) if k == "shape")
    assert next(e for e in spec["elements"] if e["type"] == "shape" and e["box"]["x"] == 80)["opacity"] < 1.0


def test_unreadable_background_is_reset():
    raw = card_spec("card-02")
    t = design.clean_theme({**THEME, "palette": {**THEME["palette"], "accent": "#3A2433"}})
    raw["background"] = {"start": "accent", "end": "accent", "angle": 0}
    assert design.finalize_card(raw, CARD, t)["background"]["start"] == "bgFrom"


def test_unknown_image_ref_is_rejected():
    raw = card_spec("card-02", image="img9")
    with pytest.raises(LayoutError):
        design.finalize_card(raw, CARD, theme(), refs={})


def test_estimate_is_not_smaller_than_simple_wrap():
    assert design.estimate_lines("가" * 20, 100, 500) == 4
    assert design.estimate_lines("한 줄\n두 줄", 50, 900) == 2
