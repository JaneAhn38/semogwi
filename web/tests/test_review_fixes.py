"""최종 검토에서 찾은 문제 ①~⑤의 회귀 테스트. Claude와 외부 사이트에 접속하지 않습니다.

① 조사에 없는 값이 다른 칸의 출처 상태를 따라 '공식 확인'으로 보이던 문제 → '조사에서 찾지 못함', AI가 쓴 사실 칸은 자동으로 비움
② 구성안·PNG 저장 전 경고에서 공식/2차 구분이 안 보이던 문제
③ 원문을 읽지 못한 검색 결과의 사실 문장만으로 숫자가 근거로 통과하던 문제
④ 예전 형식 작업의 '현재 자료로 구성안 작성'
⑤ 문서의 '공식 출처만' 규칙
"""

from pathlib import Path

from app import ai_provider, jobs, research, templates
from tests.test_insufficient_flow import (CARDS, api, card, client, clear_cooldowns, compose_now, errors_of, fake,  # noqa: F401
                                          start_insufficient)

USE_TEMPLATES = True


# ---------- ① 조사에서 찾지 못한 정보 ----------
def test_value_missing_from_research_is_not_shown_as_official():
    sources = [{"id": "s1", "kind": "official", "verification": "fetched", "url": "https://a.example"}]
    items = research.verify_items("popup", [{"key": "popup_name", "value": "세모귀 팝업", "quote": "q", "sourceIds": ["s1"]}], sources)
    card_ = {"frame": "card-02", "template": "popup-02", "fields": {"place": "더현대 서울 5층", "period": "12.1~12.31"}, "sourceIds": ["s1"]}
    tpl = lambda frame: templates.TEMPLATES["popup-02"]  # noqa: E731
    # 재현했던 문제: 자료와 대조하지 않으면 다른 칸의 출처 상태(공식 확인)를 따라감
    assert research.field_states([card_], tpl, items, lambda c: "verified")["card-02"]["place"] == "verified"
    # 자료와 대조하면 '조사에서 찾지 못함'
    states = research.field_states([card_], tpl, items, lambda c: "verified", "세모귀 팝업 공식 공지")["card-02"]
    assert states["place"] == "absent" and states["period"] == "absent"
    # 조사 사실에 나오는 값은 그대로 (표기를 바꿔도 숫자·낱말로 맞춰 봄)
    states = research.field_states([card_], tpl, items, lambda c: "verified", "장소: 더현대서울 5F / 기간 2026년 12월 1일 ~ 12월 31일")["card-02"]
    assert states["place"] == "verified" and states["period"] == "verified"
    # 사용자가 고친 칸은 '사용자 작성'
    states = research.field_states([{**card_, "userFields": ["place"]}], tpl, items, lambda c: "verified", "")["card-02"]
    assert states["place"] == "user_written"


def test_supported_tolerates_reformatting_but_not_new_facts():
    material = research._norm("가격 440엔 (세금 포함)\n12월 1일 발매\n더현대서울 5F에서 열려요")
    for value in ("¥440", "12.1", "12월 1일", "더현대 서울 5층"):
        assert research.supported(value, material), value
    for value in ("성수동 팝업", "12월 25일", "1,500원", "9,900원"):
        assert not research.supported(value, material), value


def test_invented_fact_is_cleared_and_user_written_value_is_kept(client, fake):
    job_id, _ = start_insufficient(client, fake)
    cards = [CARDS[0], card("card-02", "goods-02", {"goods": [{"name": "안경만두 파우치", "kind": "파우치"}], "price_range": "12,000원"}, role="라인업", ids=("s9",))] + CARDS[2:]
    job = compose_now(client, fake, job_id, cards)
    c2 = job["outline"]["cards"][1]
    assert c2["fields"]["price_range"] == "" and c2["cleared"][0]["value"] == "12,000원"  # AI가 지어낸 가격은 비움
    assert not errors_of(job)  # 제작은 멈추지 않음
    # 사용자가 직접 확인해 넣은 값은 조사한 사실과 구분해 '사용자 작성'으로 남깁니다 (다시 비우지 않음)
    body = {"role": c2["role"], "fields": {**c2["fields"], "price_range": "12,000원"}, "source": c2["source"]}
    job = api(client, job_id, "PUT", "/outline/cards/card-02", json=body).json()
    c2 = job["outline"]["cards"][1]
    assert c2["fields"]["price_range"] == "12,000원" and c2["userFields"] == ["price_range"] and "cleared" not in c2
    assert job["outline"]["fieldStates"]["card-02"]["price_range"] == "user_written"
    issue = job["outline"]["issues"]["card-02"]
    assert not issue["errors"] and not any("조사에서 찾지 못한" in w for w in issue["warnings"])
    assert any(w["text"].startswith("가격대: 사용자 작성") for w in job["outline"]["publishWarnings"])
    # AI가 카드를 다시 쓰면 사용자 작성 기록은 지워지고 다시 대조합니다
    fake.rewrite = cards
    api(client, job_id, "POST", "/outline/cards/card-02/regenerate")
    from tests.test_flexible_outline import wait
    job = wait(client, job_id, "waiting_outline")
    c2 = job["outline"]["cards"][1]
    assert "userFields" not in c2 and c2["fields"]["price_range"] == ""


def test_required_field_is_not_cleared_but_warned():
    # 조사에서 상품명을 찾지 못했는데 AI가 꼭 필요한 칸(대표 상품명)에 이름을 썼으면: 비우면 카드가 깨지므로 남기고 경고로 안내
    sources = [{"id": "s1", "kind": "secondary", "verification": "fetched", "url": "https://news.example"}]
    items = research.verify_items("goods", [{"key": "price", "value": "1,500원", "quote": "q", "sourceIds": ["s1"]}], sources)
    c3 = {"frame": "card-03", "template": "goods-03", "role": "대표 상품", "edited": False, "sourceIds": ["s1"], "source": "출처: 기사",
          "fields": {"featured_name": "겨울 한정 키링", "featured_price": "1,500원", "size": "", "material": "", "components": ""}}
    job = {"id": "x" * 32, "mode": "ai", "contentType": "goods", "format": 3, "templateSet": ["goods-01", "goods-02", "goods-03", "goods-04", "goods-05"],
           "research": {"items": items, "sources": sources, "facts": [{"text": "키링 1,500원", "sourceIds": ["s1"]}]},
           "outline": {"cards": [c3]}, "userMaterial": None, "notes": ""}
    jobs.clear_unsupported(job)
    assert c3["fields"]["featured_name"] == "겨울 한정 키링" and "cleared" not in c3  # 꼭 필요한 칸은 비우지 않음
    assert jobs._field_states(job, [c3])["card-03"]["featured_name"] == "absent"
    issues = {"card-03": {"errors": [], "warnings": []}}
    jobs._check_fields_against_research(job, [c3], issues)
    assert any("조사에서 찾지 못한 정보예요: 대표 상품명" in w for w in issues["card-03"]["warnings"]) and not issues["card-03"]["errors"]


# ---------- ② 출처 종류 표시 ----------
def test_source_kind_is_shown_for_important_fields_without_blocking(client, fake):
    job_id, _ = start_insufficient(client, fake)
    job = compose_now(client, fake, job_id)
    assert job["outline"]["fieldStates"]["card-02"]["goods"] == "secondary"
    texts = [w["text"] for w in job["outline"]["publishWarnings"]]
    assert any(t.startswith("굿즈: 2차 자료") for t in texts)  # 기사에서만 확인한 상품명: 저장 전 경고에 출처 종류
    assert any(t.startswith("발매일: 2차 자료") and "원문 게시일 2026-09-01" in t for t in texts)
    assert research.FIELD_STATE_LABELS["listed"] == "검색 결과(원문 미확인)" and research.FIELD_STATE_LABELS["user"] == "사용자 제공"
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200  # 공식이 아니어도 막지 않음
    app_js = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "fieldSourceText" in app_js and '"2차 자료"' in app_js and '"공식 확인"' in app_js  # 구성안 목록·편집 화면 표시


# ---------- ③ 검색 결과 숫자 ----------
def test_search_result_fact_alone_is_not_number_evidence():
    rec = {"sources": [{"id": "q", "verification": "search_result"}], "facts": [{"text": "입장료 15,000원", "sourceIds": ["q"]}]}
    assert "15,000" not in ai_provider.material_text(rec, None)  # 재현했던 문제: 사실 문장만으로 통과하던 숫자
    rec["items"] = [{"key": "price", "value": "15,000원", "quote": "입장료 15,000원 (현장 결제)", "sourceIds": ["q"]}]
    assert "15,000원" in ai_provider.material_text(rec, None)  # 조사 항목 값과 근거 문장이 맞는 경우만
    rec["items"][0]["quote"] = "입장료는 공식 안내 참고"
    assert "15,000" not in ai_provider.material_text(rec, None)


# ---------- ④ 예전 형식 작업 ----------
def test_compose_with_current_is_refused_for_old_format_jobs(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    job = jobs._read(job_id)
    job.update(state="waiting_material", mode="ai", contentType="goods", topic="예전 작업", templateSet=None,
               research={"facts": [{"text": "키링", "sourceIds": ["s1"]}], "sources": [], "items": []})
    jobs.save(job)
    r = api(client, job_id, "POST", "/research/compose-current")
    assert r.status_code == 409 and "자료를 입력해서" in r.json()["detail"]
    app_js = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    assert "예전 형식으로 만든 작업이라" in app_js  # 화면에서는 버튼을 끄고 이유를 안내


# ---------- ⑤ 문서 ----------
def test_pipeline_doc_uses_official_first_rule():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "research-pipeline.md").read_text(encoding="utf-8")
    assert "공식 출처만 근거로 인정" not in doc and "공식 출처 우선" in doc and "2차 자료도 근거로 인정" in doc


# ---------- 카드 출처 문구: AI가 쓰지 않고 실제 출처 이름만 ----------
def test_card_source_line_is_written_from_cited_sources_only():
    research_ = {"sources": [
        {"id": "s1", "title": "공식 숍", "url": "https://shop.example/a", "kind": "official", "verification": "fetched"},
        {"id": "s2", "title": "아주 긴 기사 제목이 들어간 뉴스 페이지", "url": "https://www.news.example/b", "kind": "secondary", "verification": "fetched"},
        {"id": "s3", "title": "지어낸 출처", "url": "https://ghost.example", "kind": "official", "verification": "unverified"},
        {"id": "user1", "title": "사용자가 입력한 자료", "url": "https://namu.wiki/w/x", "kind": "user", "verification": "user_provided"},
        {"id": "img1", "title": "상세 이미지 1", "url": "", "kind": "official", "verification": "image"}]}
    cards = {
        "card-01": {"frame": "card-01", "template": "goods-01", "source": "출처: AI가 쓴 문구", "sourceIds": ["s1"]},
        "card-02": {"frame": "card-02", "template": "goods-02", "source": "출처: 공식 홈페이지에서 확인", "sourceIds": ["s1", "s2", "s3"]},
        "card-03": {"frame": "card-03", "template": "goods-03", "source": "출처: 공식", "sourceIds": ["user1", "img1"]},
        "card-04": {"frame": "card-04", "template": "goods-04", "source": "출처: 공식 사이트", "sourceIds": ["s3"]},
        "card-05": {"frame": "card-05", "template": "goods-05", "source": "", "sourceIds": ["s1", "s2", "user1", "img1"]},
    }
    ai_provider._label_user_sources(cards, research_)
    assert cards["card-01"]["source"] == "출처: AI가 쓴 문구"  # 표지는 건드리지 않음 (출처를 표시하지 않는 카드)
    assert cards["card-02"]["source"] == "출처: 공식 숍 · news.example"  # 긴 제목은 사이트 주소로, 근거 없는 출처는 뺌
    assert cards["card-03"]["source"] == "출처: 사용자 제공 · namu.wiki 외 1곳"  # 30자에 맞춰 줄임
    assert cards["card-04"]["source"] == ""  # 실제로 확인된 출처가 없으면 지어내지 않고 비움 (구성안에서 '출처가 비어 있어요' 경고)
    assert cards["card-05"]["source"].endswith("외 2곳") and len(cards["card-05"]["source"]) <= 30
    long_only = {"card-02": {"frame": "card-02", "template": "goods-02", "source": "", "sourceIds": ["x"]}}
    host = "very-long-subdomain-name.example-news-site.com"
    ai_provider._label_user_sources(long_only, {"sources": [{"id": "x", "title": "x" * 40, "url": f"https://{host}/a", "kind": "secondary", "verification": "fetched"}]})
    line = long_only["card-02"]["source"]
    assert line.startswith("출처: very-long") and len(line) == 30  # 이름 하나가 30자를 넘어도 빈칸이 되지 않고 줄여서 적음
