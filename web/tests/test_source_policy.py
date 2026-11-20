"""출처 규칙 테스트: 나무위키는 캐릭터 소개의 보조 출처, 미러 사이트 제외, 참고 자료의 출처 종류. Claude와 외부 사이트에 접속하지 않습니다."""

import json

import pytest

from app import ai_provider, claude_cli, jobs, research, research_library, research_merge, site_policy
from app.ai_provider import verify_sources
from app.claude_cli import CliRun
import tests.test_templates as tt
from tests.test_templates import api, client, clear_cooldowns, fake, get, wait  # noqa: F401

USE_TEMPLATES = True
NAMU = "https://namu.wiki/w/%EC%A7%B1%EA%B5%AC"
MIRROR = "https://namu.moe/w/%EC%A7%B1%EA%B5%AC"
OFFICIAL = "https://www.shinchan.example/character"


@pytest.fixture(autouse=True)
def separate_library(tmp_path, monkeypatch):
    monkeypatch.setattr(research_library, "DIR", tmp_path / "research")


def run_with_fetches(*urls):
    return CliRun(fetches=[{"url": u, "code": 200} for u in urls])


def sources_for(content_type="character"):
    raw = [{"id": "s1", "url": OFFICIAL, "kind": "official", "title": "공식"},
           {"id": "s2", "url": NAMU, "kind": "official", "title": "짱구 - 나무위키"}]  # AI가 나무위키를 공식이라고 적어도
    return verify_sources(raw, run_with_fetches(OFFICIAL, NAMU), content_type)


def items_by_key(raw, sources, content_type="character"):
    return {i["key"]: i for i in research.verify_items(content_type, raw, sources)}


# ---------- 출처 분류 ----------
def test_namuwiki_is_auxiliary_secondary_and_mirror_never_counts():
    sources = {s["id"]: s for s in sources_for()}
    assert sources["s1"]["kind"] == "official" and "auxiliary" not in sources["s1"]
    namu = sources["s2"]
    assert namu["kind"] == "secondary" and namu["officialBasis"] is None and namu["verification"] == "fetched"
    assert namu["auxiliary"] == {"site": "namu.wiki", "name": "나무위키", "label": "나무위키(보조 출처)",
                                 "items": ["personality", "friends", "family", "relations", "tmi"]}
    mirror = verify_sources([{"id": "m", "url": MIRROR, "kind": "secondary"}], run_with_fetches(MIRROR), "character")[0]
    assert mirror["verification"] == "mirror" and mirror["auxiliary"]["site"] == "namu.wiki"
    # 굿즈 등 다른 유형에서는 어느 항목의 근거도 아님
    assert verify_sources([{"id": "g", "url": NAMU}], run_with_fetches(NAMU), "goods")[0]["auxiliary"]["items"] == []


def test_namuwiki_counts_only_for_personality_friends_family_tmi():
    sources = sources_for()
    items = items_by_key([
        {"key": "personality", "value": "장난꾸러기", "quote": "q", "sourceIds": ["s2"]},  # 나무위키만 → 2차 자료
        {"key": "birthday", "value": "5월 5일", "quote": "q", "sourceIds": ["s2"]},  # 생일은 나무위키로 인정하지 않음
        {"key": "series", "value": "짱구는 못말려", "quote": "q", "sourceIds": ["s1", "s2"]},  # 공식도 있으면 공식 확인
        {"key": "friends", "value": "철수(친구), 유리(친구)", "quote": "q", "sourceIds": ["s1", "s2"]},
    ], sources)
    assert items["personality"]["state"] == "secondary"
    assert items["birthday"]["state"] == "unverified"
    assert items["series"]["state"] == "verified" and items["friends"]["state"] == "verified"


def test_official_and_namuwiki_values_that_differ_go_to_review():
    sources = sources_for()
    items = items_by_key([
        {"key": "personality", "value": "마이페이스", "quote": "q", "sourceIds": ["s1"]},
        {"key": "personality", "value": "장난꾸러기", "quote": "q", "sourceIds": ["s2"]},
    ], sources)
    assert items["personality"]["state"] == "conflict" and items["personality"]["alternatives"][0]["sourceIds"] == ["s2"]
    # 추가 조사·보완 조사 통합에서도 덮어쓰지 않고 사용자 선택을 받음
    base = {"sources": [sources[0]], "items": research.verify_items("character", [
        {"key": "personality", "value": "마이페이스", "quote": "q", "sourceIds": ["s1"]}], [sources[0]]), "facts": []}
    new = {"sources": [sources[1]], "items": research.verify_items("character", [
        {"key": "personality", "value": "장난꾸러기", "quote": "q", "sourceIds": ["s2"]}], [sources[1]]), "facts": []}
    merged = research.apply_source_rules(research_merge.merge_more(base, new, "character"), "character")
    item = next(i for i in merged["items"] if i["key"] == "personality")
    assert item["value"] == "마이페이스" and item["savedConflict"] and item["state"] == "conflict"


def test_strict_types_block_namuwiki_and_number_check_ignores_it():
    assert "WebFetch(domain:namu.wiki)" in site_policy.deny_rules("goods")
    assert "WebFetch(domain:namu.wiki)" in site_policy.deny_rules("popup") and "WebFetch(domain:namu.wiki)" in site_policy.deny_rules("collab")
    character = site_policy.deny_rules("character")
    assert "WebFetch(domain:namu.wiki)" not in character and "WebFetch(domain:namu.moe)" in character  # 캐릭터는 지금처럼, 미러만 막음
    assert "나무위키 namu.wiki" in site_policy.ai_blocked_labels("goods") and "나무위키 namu.wiki" not in site_policy.ai_blocked_labels("character")
    # 가격 숫자 대조: 나무위키 근거의 숫자는 믿을 수 있는 근거가 아님
    sources = verify_sources([{"id": "s1", "url": NAMU}], run_with_fetches(NAMU), "goods")
    rec = {"sources": sources, "facts": [{"text": "가격 12,000원", "sourceIds": ["s1"]}]}
    assert "12,000" not in ai_provider.material_text(rec, None)
    price = items_by_key([{"key": "price", "value": "12,000원", "quote": "q", "sourceIds": ["s1"]}], sources, "goods")["price"]
    assert price["state"] == "unverified"


# ---------- 참고 자료 직접 입력의 출처 종류 ----------
def test_user_notes_kind_never_becomes_official():
    official = research.user_notes_source("official", "https://brand.example/notice", "goods")
    assert official["verification"] == "user_provided" and official["kind"] == "user" and "검증 안 됨" in official["title"]
    items = items_by_key([{"key": "price", "value": "1,500원", "quote": "q", "sourceIds": ["u1"]}], [official], "goods")
    assert items["price"]["state"] == "user"  # 공식 확인(verified)이 아님
    namu = research.user_notes_source("namuwiki", NAMU, "character")
    assert namu["auxiliary"]["site"] == "namu.wiki" and namu["userKind"] == "namuwiki"
    items = items_by_key([{"key": "personality", "value": "장난꾸러기", "quote": "q", "sourceIds": ["u1"]},
                          {"key": "birthday", "value": "5월 5일", "quote": "q", "sourceIds": ["u1"]}], [namu])
    assert items["personality"]["state"] == "secondary" and items["birthday"]["state"] == "unverified"
    goods = research.user_notes_source("namuwiki", NAMU, "goods")  # 굿즈 가격은 나무위키 자료로 인정하지 않음
    assert items_by_key([{"key": "price", "value": "1,500원", "quote": "q", "sourceIds": ["u1"]}], [goods], "goods")["price"]["state"] == "unverified"
    # 종류를 고르지 않아도 주소가 나무위키면 보조 출처
    assert research.user_notes_source("", NAMU, "character")["userKind"] == "namuwiki"


@pytest.fixture
def capture(fake, monkeypatch):
    """실제 AI 대신 Fake를 쓰고, 차단 규칙(disallowed)도 기록합니다."""
    seen = []

    def run(prompt, system, schema, **kwargs):
        seen.append({"prompt": prompt, "system": system, "disallowed": kwargs.get("disallowed", ())})
        return fake(prompt, system, schema, **kwargs)

    monkeypatch.setattr(claude_cli, "run", run)
    return seen


def start_ai(client, **extra):
    job_id = client.post("/api/jobs/draft").json()["id"]
    body = {"topic": "짱구", "contentType": "character", "url": "", "mode": "ai", **extra}
    return job_id, api(client, job_id, "POST", "/start", json=body)


def test_notes_source_is_validated_saved_and_passed_to_research(client, capture):
    _, r = start_ai(client, notes="짱구는 장난꾸러기예요", notesKind="namuwiki", notesUrl="https://brand.example/a")
    assert r.status_code == 400 and "namu.wiki" in r.json()["detail"]
    _, r = start_ai(client, notes="짱구는 장난꾸러기예요", notesKind="other", notesUrl=MIRROR)
    assert r.status_code == 400 and "미러" in r.json()["detail"]
    job_id, r = start_ai(client, notes="짱구는 장난꾸러기예요", notesKind="namuwiki", notesUrl=NAMU)
    assert r.status_code == 200, r.text
    job = wait(client, job_id, "waiting_outline", "waiting_material")
    assert job["notesKind"] == "namuwiki" and job["notesUrl"] == NAMU
    u1 = next(s for s in job["research"]["sources"] if s["id"] == "u1")
    assert u1["auxiliary"]["label"] == "나무위키(보조 출처)" and u1["verification"] == "user_provided" and u1["url"] == NAMU
    research_call = next(c for c in capture if "<user_notes>" in c["prompt"])
    assert "나무위키에서 옮긴 보조 자료" in research_call["prompt"] and "나무위키(namu.wiki)는 공식 출처가 아닌 보조 출처" in research_call["prompt"]
    assert "WebFetch(domain:namu.moe)" in research_call["disallowed"] and "WebFetch(domain:namu.wiki)" not in research_call["disallowed"]


def test_goods_research_blocks_namuwiki_fetch(client, capture):
    job_id, r = start_ai(client, topic="치이카와 키링", contentType="goods")
    assert r.status_code == 200, r.text
    wait(client, job_id, "waiting_outline", "waiting_material")
    call = capture[0]
    assert "WebFetch(domain:namu.wiki)" in call["disallowed"] and "나무위키 namu.wiki" in call["prompt"]


def test_card_with_namuwiki_source_gets_a_warning(client, capture, monkeypatch):
    monkeypatch.setattr(tt, "OFFICIAL", NAMU)  # 가짜 AI가 읽은 페이지가 나무위키인 경우
    job_id, _ = start_ai(client)
    job = wait(client, job_id, "waiting_outline")
    source = next(s for s in job["research"]["sources"] if s["url"] == NAMU)
    assert source["kind"] == "secondary" and source["auxiliary"]
    warnings = [w for issue in job["outline"]["issues"].values() for w in issue["warnings"]]
    assert any("나무위키(보조 출처) 내용이 들어 있어요" in w for w in warnings)


def test_material_from_namuwiki_is_refused_for_goods(client, fake):
    job_id = client.post("/api/jobs/draft").json()["id"]
    job = jobs._read(job_id)
    job.update(state="waiting_material", mode="ai", contentType="goods", topic="치이카와 키링")
    jobs.save(job)
    body = {"name": "키링", "features": "귀여운 키링", "price": "1,500원", "sourceUrl": NAMU}
    r = api(client, job_id, "POST", "/material", json=body)
    assert r.status_code == 409 and "근거로 쓸 수 없어요" in r.json()["detail"]


# ---------- 자료 보관함: 예전에 저장된 자료에도 같은 규칙 ----------
def test_saved_research_gets_the_same_rules_without_changing_the_file():
    old_sources = [{"id": "s1", "url": NAMU, "title": "나무위키", "kind": "secondary", "verification": "fetched", "origin": "ai"},
                   {"id": "s2", "url": MIRROR, "title": "미러", "kind": "secondary", "verification": "fetched", "origin": "ai"}]
    old_items = research.verify_items("character", [
        {"key": "birthday", "value": "5월 5일", "quote": "q", "sourceIds": ["s1"]},
        {"key": "personality", "value": "장난꾸러기", "quote": "q", "sourceIds": ["s1"]},
        {"key": "favorite", "value": "초코비", "quote": "q", "sourceIds": ["s2"]}], old_sources)  # 예전 규칙으로 저장된 상태
    assert {i["key"]: i["state"] for i in old_items}["birthday"] == "secondary"
    summary = research_library.save({"id": "j" * 32, "topic": "짱구", "contentType": "character"},
                                    {"sources": old_sources, "items": old_items, "facts": [], "pipeline": 2})
    before = research_library._path(summary["id"]).read_text(encoding="utf-8")
    found = research_library.research_for_job(research_library.get(summary["id"]), "짱구는 장난꾸러기", "official", "https://brand.example/a")
    states = {i["key"]: i["state"] for i in found["items"]}
    assert states["birthday"] == "unverified" and states["personality"] == "secondary" and states["favorite"] == "unverified"
    by_id = {s["id"]: s for s in found["sources"]}
    assert by_id["s1"]["auxiliary"] and by_id["s2"]["verification"] == "mirror"
    assert by_id["u1"]["userKind"] == "official" and by_id["u1"]["verification"] == "user_provided"
    assert research_library._path(summary["id"]).read_text(encoding="utf-8") == before  # 저장된 버전은 그대로


def test_material_from_namuwiki_is_auxiliary_for_character_and_mirror_is_refused(client, fake):
    job_id = client.post("/api/jobs/draft").json()["id"]
    job = jobs._read(job_id)
    job.update(state="waiting_material", mode="ai", topic="짱구")
    jobs._apply_type(job, "character", "user")
    jobs.save(job)
    body = {"name": "짱구", "features": "장난꾸러기 다섯 살", "sourceUrl": MIRROR}
    r = api(client, job_id, "POST", "/material", json=body)
    assert r.status_code == 409 and "미러" in r.json()["detail"]
    r = api(client, job_id, "POST", "/material", json={**body, "sourceUrl": NAMU})
    assert r.status_code == 200, r.text
    job = wait(client, job_id, "waiting_outline", "waiting_material")
    user1 = next(s for s in job["research"]["sources"] if s["id"] == "user1")
    assert user1["verification"] == "user_provided" and user1["auxiliary"]["label"] == "나무위키(보조 출처)"
