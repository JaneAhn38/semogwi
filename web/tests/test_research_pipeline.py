"""자료조사 1단계 기반: 조사와 구성안 분리, 항목 정의 통합, 빈 항목의 이유 구분, 충분성, 근거 기록. Claude·외부 사이트에 접속하지 않습니다."""

import json

import pytest

from app import claude_cli, jobs, research, research_library
from app.claude_cli import AIError
from tests.test_templates import OFFICIAL, api, client, clear_cooldowns, fake, get, start, wait  # noqa: F401

USE_TEMPLATES = True

SOURCES = [
    {"id": "off", "url": OFFICIAL, "title": "공식", "kind": "official", "verification": "fetched"},
    {"id": "list", "url": "https://shop.example/list", "title": "목록", "kind": "official", "verification": "search_result"},
]
LOG = {"searched": True, "fetches": [{"url": OFFICIAL, "code": 200}, {"url": "https://broken.example/a", "code": 404},
                                     {"url": "https://deny.example/a", "code": 403}],
       "searchFailures": [], "searchesWithResults": True, "coolingHosts": ["cool.example"], "at": "2026-11-18T10:00:00"}


def empty(key, outcome, urls=()):
    return {"key": key, "value": "", "quote": "", "sourceIds": [], "outcome": outcome, "coverage": "unknown", "coverageNote": "",
            "checkedUrls": list(urls)}


def states_of(raw, log=LOG, content_type="goods"):
    return {i["key"]: i["state"] for i in research.verify_items(content_type, raw, SOURCES, log)}


# ---------- 항목 정의 통합 ----------
def test_specs_define_every_item_with_importance_and_hints():
    for content_type, specs in research.SPECS.items():
        assert specs and all(s["importance"] in ("core", "high", "normal") and s.get("hint") for s in specs), content_type
        assert [k for k, _, _ in research.ITEMS[content_type]] == [s["key"] for s in specs]
        assert {k for group in research.CORE[content_type] for k in group} == {s["key"] for s in specs if s.get("core")}
        assert all(s["importance"] == "core" for s in specs if s.get("core"))
    # 시간이 지나면 바뀌는 정보와 여러 개가 나열되는 정보가 표시돼 있습니다
    goods = {s["key"]: s for s in research.SPECS["goods"]}
    assert goods["price"]["volatile"] and goods["sale_period"]["volatile"] and not goods.get("material", {}).get("volatile")
    assert goods["product_names"]["many"] and research.SPECS["character"][7]["key"] == "friends" and research.SPECS["character"][7]["many"]
    text = research.checklist_text("goods", report=True)
    assert "(핵심, 공식 출처 우선, 여러 개 나열)" in text and "outcome" in text and "coverage" in text and "카드를 쓰지 않는다" in text


# ---------- 빈 항목의 이유 ----------
@pytest.mark.parametrize("raw, state", [
    (empty("size", "not_found", [OFFICIAL]), "not_found"),                       # 페이지를 읽었는데 없음
    (empty("size", "not_found", ["https://broken.example/a"]), "failed"),       # 읽기 실패
    (empty("size", "not_found", ["https://deny.example/a"]), "blocked"),        # 사이트가 거절
    (empty("size", "not_found", ["https://chiikawamarket.jp/item/1"]), "blocked"),  # 자동 접근 금지 사이트
    (empty("size", "not_found", ["https://cool.example/x"]), "blocked"),        # 요청 대기 중인 사이트
    (empty("size", "not_searched"), "not_searched"),
    (empty("size", "not_found"), "not_found"),                                  # 검색은 했고 결과도 있었음
    (empty("size", "not_found", ["https://never-read.example/a"]), "not_found"),  # 조회 기록이 없는 주소는 근거로 삼지 않음
])
def test_empty_item_reasons(raw, state):
    assert states_of([raw])["size"] == state


def test_reasons_need_a_real_attempt():
    raw = [empty("size", "not_found")]
    # 이번 조사에서 검색·페이지 읽기가 전혀 없었다면 '자료 없음'이라고 하지 않습니다
    assert states_of(raw, {**LOG, "searched": False, "fetches": []})["size"] == "not_searched"
    # 검색 도구가 모두 실패했으면 '실패'
    failed_log = {**LOG, "searched": False, "fetches": [], "searchFailures": [{"query": "q", "reason": "검색 도구 오류"}]}
    assert states_of(raw, failed_log)["size"] == "failed"
    assert states_of(raw, {**LOG, "searchFailures": [{"query": "q", "reason": "x"}], "searchesWithResults": False})["size"] == "failed"
    # AI가 보고하지 않은 항목은 '미조사'
    assert states_of(raw)["material"] == "not_searched"


def test_old_format_keeps_missing_state():
    raw = [{"key": "size", "value": "", "quote": "", "sourceIds": []}]
    assert states_of(raw, None)["size"] == "missing"
    assert states_of(raw)["size"] == "missing"  # 조사 결과(outcome)를 적지 않은 예전 응답: 이유를 지어내지 않음


def test_reverify_keeps_reasons_and_coverage():
    first = research.verify_items("goods", [empty("size", "not_found", [OFFICIAL])], SOURCES, LOG)
    again = {i["key"]: i for i in research.verify_items("goods", [], SOURCES, previous=first)}
    assert again["size"]["state"] == "not_found" and again["size"]["attempts"]["checked"][0]["result"] == "read"


# ---------- 충분성 ----------
def found(key, coverage, note="", value="값", ids=("off",)):
    return {"key": key, "value": value, "quote": value, "sourceIds": list(ids), "outcome": "found", "coverage": coverage,
            "coverageNote": note, "checkedUrls": [OFFICIAL]}


def test_coverage_marks_partial_lists_for_review_without_counting():
    items = {i["key"]: i for i in research.verify_items("goods", [
        found("product_names", "partial", "목록 일부만 읽음"), found("components", "complete"), found("features", "unknown"),
        found("seller", "unknown"), found("price", "partial", "1종 가격만")], SOURCES, LOG)}
    assert items["product_names"]["coverage"] == {"level": "partial", "note": "목록 일부만 읽음", "review": True}
    assert items["components"]["coverage"]["review"] is False
    assert items["features"]["coverage"]["review"] is True          # 여러 개 나열 항목인데 전체 규모를 모름 → 검토
    assert items["seller"]["coverage"] == {"level": "n/a", "note": "", "review": False}  # 값이 하나인 항목은 따지지 않음
    assert items["price"]["coverage"]["level"] == "partial"
    assert "coverage" not in items["size"]  # 값이 없는 항목에는 충분성을 붙이지 않음


def test_relation_word_alone_is_not_a_character():
    # 실제 조사에서 '봉미선(엄마), 신짱아(동생), 아빠'처럼 이름 없이 관계만 적힌 적이 있습니다 (친구 목록에도 같은 규칙)
    item = {"key": "friends", "value": "철수(친구), 유리(친구), 친구", "state": "secondary", "strict": False}
    assert [p["name"] for p in research.people_of([item])["friends"]] == ["철수", "유리"]


def test_people_partial_coverage_is_reviewed():
    items = {i["key"]: i for i in research.verify_items("character", [
        found("friends", "partial", "등장인물 목록 일부만 확인", "철수(친구), 유리(친구)")], SOURCES, LOG)}
    assert items["friends"]["coverage"]["review"] and items["friends"]["state"] == "verified"
    report = research.research_report({"items": list(items.values())}, "character")
    assert "friends" in report["review"]


# ---------- 근거 기록 ----------
def test_evidence_separates_page_read_from_quote_check():
    items = {i["key"]: i for i in research.verify_items("goods", [found("seller", "unknown", value="공식 스토어"),
                                                                 found("release_date", "unknown", value="12월 1일", ids=("list",))], SOURCES, LOG)}
    evidence = items["seller"]["evidence"][0]
    assert evidence == {"sourceId": "off", "url": OFFICIAL, "title": "공식", "kind": "official", "verification": "fetched",
                        "pageRead": True, "publishedAt": "", "quote": "공식 스토어", "quoteCheck": "not_checked", "at": "2026-11-18T10:00:00"}
    listed = items["release_date"]["evidence"][0]
    # 검색 결과의 값도 참고 자료로 쓰지만, 원문 페이지를 읽지 못했다는 사실은 따로 남습니다
    assert listed["pageRead"] is False and items["release_date"]["state"] == "listed"
    assert items["seller"]["attempts"] == {"outcome": "found", "checked": [{"url": OFFICIAL, "result": "read"}]}


# ---------- 조사와 구성안 분리 ----------
def items_for_research(prompt):
    return [found("official_name", "unknown", value="치이카와", ids=("s1",)), found("personality", "unknown", value="겁이 많아요", ids=("s1",)),
            empty("birthday", "not_found", [OFFICIAL])]


class StagedFake:
    """test_templates.Fake에 항목별 조사 결과를 더하고, 구성안 단계 실패를 흉내 낼 수 있게 합니다."""

    def __init__(self, base):
        self.base, self.kinds, self.fail_compose = base, [], 0

    def __call__(self, prompt, system, schema, **kwargs):
        props = schema["properties"]
        kind = "people" if "people" in props else "research" if "sources" in props else "compose" if "status" in props else "other"
        self.kinds.append((kind, tuple(kwargs.get("tools") or ())))
        if kind == "compose" and self.fail_compose:
            self.fail_compose -= 1
            raise AIError("timeout", "구성안 작성 시간이 초과됐어요")
        run = self.base(prompt, system, schema, **kwargs)
        if kind == "research":
            run.structured["items"] = items_for_research(prompt)
        return run


@pytest.fixture
def staged(fake, monkeypatch):
    spy = StagedFake(fake)
    monkeypatch.setattr(claude_cli, "run", spy)
    return spy


def test_research_and_compose_are_separate_calls(client, staged):
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    kinds = [k for k, _ in staged.kinds]
    assert kinds[0] == "research" and kinds[-1] == "compose" and kinds.count("research") == 1
    assert dict(staged.kinds)["compose"] == ()  # 구성안 단계에는 웹 도구를 주지 않음
    calls = staged.base.calls
    research_call = next(c for c in calls if "sources" in c["schema"]["properties"] and "people" not in c["schema"]["properties"])
    assert "cards" not in research_call["schema"]["properties"] and "카드 문구는 쓰지 않는다" in research_call["prompt"]
    item_schema = research_call["schema"]["properties"]["items"]["items"]["properties"]
    assert {"outcome", "coverage", "coverageNote", "checkedUrls"} <= set(item_schema)
    compose_call = calls[-1]
    assert "확인되지 않은 항목(문구로 채우지 않고 칸을 비운다):" in compose_call["prompt"]
    assert "생일 등 공식 프로필(자료 없음)" in compose_call["prompt"] and "제작자(미조사)" in compose_call["prompt"]
    r = job["research"]
    assert r["pipeline"] == 2 and r["researchedAtTime"] and job["researchStage"]["done"] is True
    states = {i["key"]: i["state"] for i in r["items"]}
    assert states["official_name"] == "verified" and states["birthday"] == "not_found" and states["creator"] == "not_searched"
    assert len(job["outline"]["cards"]) == 5


def test_research_is_saved_before_compose_and_retry_only_composes(client, staged):
    staged.fail_compose = 1
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "failed")
    # 구성안 작성이 실패해도 조사 결과는 작업에 남아 있습니다
    assert job["research"]["pipeline"] == 2 and job["researchStage"]["done"] and job["outline"] is None
    assert "구성안 작성 시간이 초과" in job["error"]
    steps = {s["key"]: s["status"] for s in job["steps"]}
    assert steps["research"] == "done"
    staged.kinds.clear()
    assert api(client, job_id, "POST", "/retry").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert [k for k, _ in staged.kinds] == ["compose"]  # 다시 조사하지 않음
    assert len(job["outline"]["cards"]) == 5


def test_new_research_is_stored_in_library_with_new_fields(client, staged, tmp_path, monkeypatch):
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")
    job_id = start(client, mode="ai", topic="파이프라인 확인")
    job = wait(client, job_id, "waiting_outline")
    stored = json.loads(research_library._path(job["researchVersion"]["id"]).read_text(encoding="utf-8"))
    assert stored["research"]["pipeline"] == 2
    birthday = next(i for i in stored["research"]["items"] if i["key"] == "birthday")
    assert birthday["state"] == "not_found" and birthday["attempts"]["checked"][0]["result"] == "read"
    name = next(i for i in stored["research"]["items"] if i["key"] == "official_name")
    assert name["evidence"][0]["pageRead"] is True and name["evidence"][0]["quoteCheck"] == "not_checked"


def test_old_library_versions_still_open_and_compare(tmp_path, monkeypatch):
    """예전 형식 보관함 자료(빈 이유·근거 기록 없음)도 열리고 요약·비교할 수 있습니다."""
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")
    research_library.DIR.mkdir(parents=True)
    old_items = [{"key": "official_name", "label": "캐릭터 이름·공식 표기", "strict": False, "value": "치이카와", "quote": "", "sourceIds": ["s1"],
                  "alternatives": [], "state": "secondary", "unclear": []},
                 {"key": "birthday", "label": "생일 등 공식 프로필", "strict": False, "value": "", "quote": "", "sourceIds": [],
                  "alternatives": [], "state": "missing", "unclear": []}]
    record = {"id": "a" * 32, "number": 1, "topicKey": research_library.topic_key("character", "치이카와"), "topic": "치이카와",
              "contentType": "character", "createdAt": "2026-11-10T10:00:00", "researchedAt": "2026-11-10",
              "research": {"sources": [{"id": "s1", "url": OFFICIAL, "title": "위키", "kind": "secondary", "verification": "fetched"}],
                           "facts": [], "items": old_items, "missing": []}}
    research_library._path(record["id"]).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    version = research_library.get(record["id"])
    assert version["itemStates"] == {"secondary": 1, "missing": 1}
    for_job = research_library.research_for_job(version)
    assert for_job["pipeline"] == 1 and for_job["items"][1]["state"] == "missing"
    report = research.research_report(for_job, "character")
    assert report["pipeline"] == 1 and report["found"] == 1 and report["states"] == {"secondary": 1, "missing": 1}


def test_compare_tool_runs(tmp_path, capsys):
    from tools import compare_research
    a = {"topic": "A", "contentType": "goods", "research": {"items": research.verify_items("goods", [empty("size", "not_found", [OFFICIAL])], SOURCES, LOG),
                                                           "pipeline": 2}}
    b = {"topic": "B", "contentType": "goods", "research": {"items": research.verify_items("goods", [], SOURCES), "pipeline": 1}}
    (tmp_path / "a.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
    import sys
    monkey_argv = ["compare", str(tmp_path / "a.json"), str(tmp_path / "b.json"), "--data", str(tmp_path)]
    old, sys.argv = sys.argv, monkey_argv
    try:
        compare_research.main()
    finally:
        sys.argv = old
    out = capsys.readouterr().out
    assert "자료 없음" in out and "정보 확인 필요" in out and "pipeline" in out
