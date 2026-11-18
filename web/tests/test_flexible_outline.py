"""유연한 구성안 테스트: card-01은 표지로 고정, card-02 ~ card-05는 확보된 자료에 맞춰 템플릿(자유 구성 포함)을 고릅니다.

필수 칸이 빈 전용 템플릿은 자유 구성으로 바뀌어 승인이 막히지 않고, 충돌·미확인 정보는 그대로 검증합니다.
Claude와 외부 사이트에 접속하지 않습니다.
"""

import json
import os
import tempfile
import time

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, jobs, site_policy, templates
from app.claude_cli import CliRun
from app.main import app
from app.provider import FRAMES

USE_TEMPLATES = True

SHOP = "https://glasses-mandu.example/shop/goods"
SOURCE = {"id": "s1", "title": "안경만두 공식 숍", "url": SHOP, "kind": "official"}
TOPIC = {"topic": "안경만두 상시판매 굿즈", "contentType": "goods", "url": SHOP, "mode": "ai"}


def item(key, value, ids=("s1",)):
    return {"key": key, "value": value, "quote": value, "sourceIds": list(ids)}


def card(frame, template, fields, role="카드", source="출처: 안경만두 공식 숍", ids=("s1",)):
    return {"frame": frame, "role": role, "template": template, "fields": fields, "source": "" if frame == "card-01" else source,
            "sourceIds": [] if frame == "card-01" else list(ids)}


COVER = card("card-01", "goods-01", {"character_name": "안경만두", "lineup_name": "상시판매 굿즈"}, role="표지")


class Fake:
    """조사(research) · 구성안 작성(compose) · 고쳐 쓰기(rewrite) 응답을 시나리오마다 정합니다."""

    def __init__(self):
        self.calls = []
        self.research = None
        self.compose = None
        self.rewrite = None

    def __call__(self, prompt, system, schema, *, tools=(), images=None, **kwargs):
        props = schema["properties"]
        run = CliRun(model="fake", turns=1)
        if "people" in props:
            self.calls.append({"kind": "people", "prompt": prompt, "tools": tools})
            run.structured = {"sources": [], "people": [], "missing": []}
            return run
        kind = "research" if "sources" in props else "compose" if "status" in props else "rewrite"
        self.calls.append({"kind": kind, "prompt": prompt, "tools": tools})
        if kind == "research":
            run.searches = [{"query": "안경만두", "results": [{"title": "공식 숍", "url": SHOP}]}]
            run.fetches = [{"url": SHOP, "code": 200}]
            run.structured = self.research
        elif kind == "compose":
            # 조사와 구성안이 나뉜 뒤: 시나리오가 구성안을 따로 정하지 않았으면 조사 응답에 적어 둔 카드를 구성안으로 씁니다
            fallback = {"status": "ok", "missing": [], "cards": (self.research or {}).get("cards", [])}
            run.structured = self.compose or fallback
        else:
            frames = [f for f in FRAMES if f in prompt.split("다시 쓸 카드:")[-1].split("\n")[0]]
            run.structured = {"cards": [c for c in (self.rewrite or []) if c["frame"] in frames]}
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


def run(client, fake, research):
    fake.research = research
    job_id = client.post("/api/jobs/draft").json()["id"]
    assert api(client, job_id, "POST", "/start", json=TOPIC).status_code == 200
    return job_id, wait(client, job_id, "waiting_outline", "waiting_material")


def errors_of(job):
    return {f: i["errors"] for f, i in job["outline"]["issues"].items() if i["errors"]}


def all_text(job):
    return " ".join(templates.card_text(c) for c in job["outline"]["cards"])


# ---------- 1. 출시일이 없는 상시판매 상품 ----------
def test_always_on_sale_goods_without_release_date(client, fake):
    research = {
        "status": "ok", "missing": ["출시일", "판매 시작 시각"], "sources": [SOURCE], "facts": [],
        "items": [item("product_names", "안경만두 아크릴 키링"), item("price", "12,000원"), item("features", "양면 인쇄 아크릴"),
                  item("components", "키링 1개"), item("seller", "안경만두 공식 숍"), item("how_to_buy", "공식 숍 상시 판매")],
        "cards": [
            COVER,
            card("card-02", "goods-02", {"goods": [{"name": "아크릴 키링", "kind": "양면 아크릴", "price": "12,000원"}], "price_range": ""}, role="라인업"),
            card("card-03", "goods-03", {"featured_name": "안경만두 아크릴 키링", "featured_price": "", "size": "", "material": "", "components": "키링 1개"}, role="특징·구성"),
            # 판매 시작 시각이 없는데 구매 방법 템플릿을 고른 경우 → 서버가 자유 구성으로 바꿉니다
            card("card-04", "goods-04", {"sale_start": "", "seller": "안경만두 공식 숍", "delivery": ""}, role="가격·구매"),
            card("card-05", "goods-free", {"heading": "구매 전 참고 사항", "lead": "", "points": [{"label": "구매 방법", "value": "공식 숍 상시 판매"}], "notes": []}, role="참고 사항"),
        ]}
    job_id, job = run(client, fake, research)
    assert job["state"] == "waiting_outline"
    cards = job["outline"]["cards"]
    assert [c["template"] for c in cards] == ["goods-01", "goods-02", "goods-03", "goods-free", "goods-free"]
    assert job["templateSet"] == [c["template"] for c in cards]
    assert cards[3]["convertedFrom"] == "goods-04" and cards[3]["fields"]["points"] == [{"label": "판매처", "value": "안경만두 공식 숍"}]
    assert cards[3]["fields"]["heading"] == "가격·구매"
    assert not errors_of(job)  # 출시일·판매 시작이 없어도 승인이 막히지 않습니다
    assert any("자유 구성 카드로 만들었어요" in w for w in job["outline"]["issues"]["card-04"]["warnings"])
    assert "MM" not in all_text(job) and "[" not in all_text(job)  # 자리표시·지어낸 날짜 없음
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    job = wait(client, job_id, "waiting_preview")
    assert [c["spec"]["template"] for c in job["preview"]["cards"]] == job["templateSet"]
    assert job["preview"]["cards"][3]["spec"]["fields"]["points"][0]["value"] == "안경만두 공식 숍"
    prompt = fake.calls[0]["prompt"]
    assert "goods-free (자유 구성)" in prompt and "선택 정보가 없다는 이유로 status를 insufficient로 하지 않는다" in prompt


# ---------- 2. 가격 정보만 확인된 상품 ----------
def test_name_and_price_only_still_makes_five_cards(client, fake):
    research = {"status": "insufficient", "missing": ["특징", "구성품", "출시일"], "sources": [SOURCE], "facts": [], "cards": [],
                "items": [item("product_names", "안경만두 머그컵"), item("price", "15,000원")]}
    fake.compose = {"status": "ok", "missing": ["특징"], "cards": [
        COVER,
        card("card-02", "goods-02", {"goods": [{"name": "머그컵", "kind": "", "price": "15,000원"}], "price_range": "15,000원"}, role="라인업"),
        card("card-03", "goods-free", {"heading": "가격", "points": [{"label": "가격", "value": "15,000원"}]}, role="가격"),  # 같은 정보 반복
        card("card-04", "goods-free", {"heading": "구매 안내", "points": []}, role="구매"),  # 빈 카드
        card("card-05", "goods-free", {"heading": "구매 전 확인", "notes": ["자세한 안내는 공식 숍에서 확인해 주세요"]}, role="마무리"),
    ]}
    fake.rewrite = [
        card("card-03", "goods-free", {"heading": "어디서 사나요", "notes": ["안경만두 공식 숍 판매 상품이에요"]}, role="판매처"),
        card("card-04", "goods-free", {"heading": "구매 전 체크", "notes": ["재고는 공식 숍에서 확인해 주세요"]}, role="체크"),
    ]
    job_id, job = run(client, fake, research)
    assert job["state"] == "waiting_outline" and job["research"]["partial"] is True
    assert [c["kind"] for c in fake.calls] == ["research", "compose", "rewrite"]  # 빈 카드·반복은 한 번만 고쳐 씁니다
    rewrite = fake.calls[2]["prompt"]
    assert "앞 카드와 같은 정보를 반복했다" in rewrite and "이 카드에 담은 정보가 없다" in rewrite
    assert not errors_of(job) and len(job["outline"]["cards"]) == 5
    assert "출시" not in all_text(job)  # 확인되지 않은 날짜를 만들지 않음
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_price_without_product_name_asks_for_material(client, fake):
    research = {"status": "insufficient", "missing": ["상품명"], "sources": [SOURCE], "facts": [], "cards": [], "items": [item("price", "15,000원")]}
    job_id, job = run(client, fake, research)
    assert job["state"] == "waiting_material" and [c["kind"] for c in fake.calls] == ["research"]


# ---------- 3. 상품명·가격·특징이 확인된 상품 ----------
def test_name_price_features_flexible_cards(client, fake):
    research = {
        "status": "ok", "missing": [], "sources": [SOURCE], "facts": [],
        "items": [item("product_names", "안경만두 인형"), item("price", "25,000원"), item("features", "부드러운 극세사 원단"), item("size", "약 20cm")],
        "cards": [
            COVER,
            card("card-02", "goods-02", {"goods": [{"name": "안경만두 인형", "kind": "인형", "price": "25,000원"}]}, role="라인업"),
            card("card-03", "goods-03", {"featured_name": "안경만두 인형", "featured_price": "25,000원", "size": "약 20cm"}, role="특징"),
            card("card-04", "goods-free", {"heading": "이런 점이 좋아요", "lead": "부드러운 극세사 원단으로 만들었어요"}, role="특징"),
            # card-01에 자유 구성을 적어도 표지는 바뀌지 않습니다
            card("card-05", "goods-free", {"heading": "가격과 구매", "points": [{"label": "판매처", "value": "안경만두 공식 숍"}]}, role="구매"),
        ]}
    research["cards"][0] = {**COVER, "template": "goods-free"}
    job_id, job = run(client, fake, research)
    assert job["templateSet"] == ["goods-01", "goods-02", "goods-03", "goods-free", "goods-free"]
    assert not errors_of(job)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


# ---------- 4. 일부 정보가 충돌하는 상품 (자유 구성 카드에도 적용) ----------
def test_conflict_inside_free_card_still_blocks(client, fake):
    other = {"id": "s2", "title": "공식 SNS", "url": "https://sns.example/mandu", "kind": "official"}
    research = {
        "status": "ok", "missing": [], "sources": [SOURCE, other], "facts": [],
        "items": [item("product_names", "안경만두 파우치"), item("price", "9,000원", ("s1",)), item("price", "9,900원", ("s2",))],
        "cards": [
            COVER,
            card("card-02", "goods-02", {"goods": [{"name": "안경만두 파우치", "kind": "파우치"}]}, role="라인업"),
            card("card-03", "goods-free", {"heading": "가격", "points": [{"label": "가격", "value": "9,900원"}]}, role="가격"),
            card("card-04", "goods-free", {"heading": "구매처", "points": [{"label": "판매처", "value": "공식 숍"}]}, role="구매"),
            card("card-05", "goods-free", {"heading": "마무리", "notes": ["공식 숍에서 만나요"]}, role="마무리"),
        ]}
    fake.research = research
    job_id = client.post("/api/jobs/draft").json()["id"]
    api(client, job_id, "POST", "/start", json=TOPIC)
    job = wait(client, job_id, "waiting_outline")
    assert any("출처마다 값이 달라요" in e for e in job["outline"]["issues"]["card-03"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409  # 자동으로 하나를 고르지 않습니다
    # 사용자가 확인해 직접 고치면 경고로 바뀌어 승인할 수 있습니다
    c3 = job["outline"]["cards"][2]
    body = {"role": c3["role"], "fields": {**c3["fields"], "points": [{"label": "가격", "value": "9,000원"}]}, "source": c3["source"]}
    assert api(client, job_id, "PUT", "/outline/cards/card-03", json=body).status_code == 200
    job = get(client, job_id)
    assert not errors_of(job) and any("출처마다 값이 달라요" in w for w in job["outline"]["issues"]["card-03"]["warnings"])


def test_unverified_value_in_free_card_is_flagged(client, fake):
    research = {
        "status": "ok", "missing": [], "sources": [SOURCE, {"id": "s9", "title": "블로그", "url": "https://blog.example/x", "kind": "secondary"}],
        "facts": [], "items": [item("product_names", "안경만두 컵"), item("release_date", "12월 1일", ("s9",))],
        "cards": [COVER] + [card(f, "goods-free", {"heading": "안내", "points": [{"label": "상품", "value": f"안경만두 컵 {f}"}]}) for f in FRAMES[1:4]]
        + [card("card-05", "goods-free", {"heading": "출시", "points": [{"label": "출시일", "value": "12월 1일"}]}, ids=("s1",))]}
    _, job = run(client, fake, research)
    # 블로그 주소는 조회 기록이 없어 '근거 없음' → 자유 구성 카드 안의 같은 값도 공식 확인 전에는 승인을 막습니다
    assert any("확인하지 못한 정보예요: 출시일" in e for e in errors_of(job)["card-05"])


# ---------- 5. 실제로 확인된 정보가 거의 없는 상품 ----------
def test_almost_nothing_verified_asks_for_material(client, fake):
    research = {"status": "insufficient", "missing": ["상품명", "가격"], "sources": [], "facts": [], "cards": [], "items": []}
    job_id, job = run(client, fake, research)
    assert job["state"] == "waiting_material" and job["outline"] is None
    assert [c["kind"] for c in fake.calls] == ["research"]


# ---------- 6. 사용자 수정과 카드 구성 바꾸기 ----------
def test_user_can_switch_card_template_and_edit(client, fake):
    research = {
        "status": "ok", "missing": [], "sources": [SOURCE], "facts": [],
        "items": [item("product_names", "안경만두 키링"), item("price", "12,000원"), item("seller", "공식 숍")],
        "cards": [COVER,
                  card("card-02", "goods-02", {"goods": [{"name": "안경만두 키링", "kind": "키링", "price": "12,000원"}]}, role="라인업"),
                  card("card-03", "goods-03", {"featured_name": "안경만두 키링", "featured_price": "12,000원"}, role="주목"),
                  card("card-04", "goods-free", {"heading": "구매처", "points": [{"label": "판매처", "value": "공식 숍"}]}, role="구매"),
                  card("card-05", "goods-free", {"heading": "마무리", "notes": ["공식 숍에서 만나요"]}, role="마무리")]}
    job_id, job = run(client, fake, research)
    # 전용 템플릿 → 자유 구성: 있는 값만 정보 줄로 옮깁니다
    job = api(client, job_id, "PUT", "/outline/cards/card-03/template", json={"template": "goods-free"}).json()
    c3 = job["outline"]["cards"][2]
    assert c3["template"] == "goods-free" and {"label": "가격", "value": "12,000원"} in c3["fields"]["points"] and c3["edited"]
    assert job["templateSet"][2] == "goods-free"
    # 필수 정보(판매 시작)가 없는 구성으로는 바꿀 수 없습니다 (빈 칸을 만들지 않음)
    r = api(client, job_id, "PUT", "/outline/cards/card-04/template", json={"template": "goods-04"})
    assert r.status_code == 409 and "판매 시작" in r.json()["detail"]
    assert api(client, job_id, "PUT", "/outline/cards/card-01/template", json={"template": "goods-free"}).status_code == 409
    # 자유 구성 → 전용 템플릿: 같은 이름의 정보 줄을 옮깁니다 (판매처 → seller)
    job = api(client, job_id, "PUT", "/outline/cards/card-05/template", json={"template": "goods-05"})
    assert job.status_code == 409  # 발매일이 없음
    # 전용 템플릿에서 필수 칸을 지워 저장하면 막지 않고 자유 구성으로 바꿉니다
    c2 = get(client, job_id)["outline"]["cards"][1]
    edit = {"role": "라인업", "fields": {"goods": [], "price_range": "12,000원"}, "source": c2["source"]}
    assert api(client, job_id, "PUT", "/outline/cards/card-02", json=edit).status_code == 200
    job = get(client, job_id)
    assert job["outline"]["cards"][1]["template"] == "goods-02"  # goods-02에는 필수 칸이 없어 그대로
    # 자유 구성 → 원래 전용 템플릿: 정보 줄의 '대표 상품명'·'가격'이 같은 이름의 필드로 돌아갑니다
    job = api(client, job_id, "PUT", "/outline/cards/card-03/template", json={"template": "goods-03"}).json()
    c3 = job["outline"]["cards"][2]
    assert c3["template"] == "goods-03" and c3["fields"]["featured_name"] == "안경만두 키링" and c3["fields"]["featured_price"] == "12,000원"
    assert not errors_of(job)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_slot_images_follow_template_change(client, fake):
    research = {"status": "ok", "missing": [], "sources": [SOURCE], "facts": [],
                "items": [item("product_names", "안경만두 키링"), item("price", "12,000원")],
                "cards": [COVER,
                          card("card-02", "goods-02", {"goods": [{"name": "안경만두 키링", "kind": "키링", "price": "12,000원"}]}, role="라인업"),
                          card("card-03", "goods-03", {"featured_name": "안경만두 키링", "featured_price": "12,000원"}, role="주목"),
                          card("card-04", "goods-free", {"heading": "구매", "points": [{"label": "판매처", "value": "공식 숍"}]}),
                          card("card-05", "goods-free", {"heading": "마무리", "notes": ["또 만나요"]})]}
    job_id, job = run(client, fake, research)
    png = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x03\x20\0\0\x03\x20" + b"\0" * 32
    asset = api(client, job_id, "POST", "/assets", files={"image": ("k.png", png, "image/png")}, data={"rights": "허가됨", "source": "직접 촬영"}).json()["assets"][-1]["id"]
    slot = templates.slots_of(job, "card-03")[0]["key"]
    api(client, job_id, "PUT", f"/cards/card-03/slots/{slot}", json={"assetId": asset, "variant": "original"})
    job = api(client, job_id, "PUT", "/outline/cards/card-03/template", json={"template": "goods-free"}).json()
    assert job["slotImages"]["card-03"] == {"free_image": job["slotImages"]["card-03"]["free_image"]}
    assert job["slotImages"]["card-03"]["free_image"]["assetId"] == asset  # 이미지를 잃지 않습니다


def test_free_templates_load_with_same_design_tokens():
    for type_id in ("goods", "character", "popup", "collab"):
        free = templates.TEMPLATES[f"{type_id}-free"]
        base = templates.TEMPLATES[f"{type_id}-02"]
        assert free["palette"] == templates.TEMPLATES[f"{type_id}-05"]["palette"] and free["fonts"] == base["fonts"]
        assert templates.body_choices(type_id)[-1] == f"{type_id}-free"
        schema = templates.ai_card_schema(type_id, templates.template_set(type_id))
        assert {"heading", "points", "notes"} <= set(schema["properties"]["fields"]["properties"]) and "template" in schema["required"]


def test_legacy_jobs_keep_fixed_cards():
    job = {"format": 3, "contentType": "character", "templateSet": None}
    assert not templates.is_flexible(job)
    raw = {"frame": "card-02", "template": "character-free", "role": "x", "fields": {}, "source": "", "sourceIds": []}
    assert templates.clean_card(job, raw, set())["template"] == "character-body"


def test_empty_optional_info_boxes_are_hidden():
    """값이 없는 선택 항목의 상자는 그리지 않습니다 (실제 렌더링에서 빈 흰 상자가 남는 것을 확인해 고침)."""
    expected = {"goods-01": ["release_date", "seller"], "goods-03": ["size", "material", "components"], "collab-04": ["stores", "purchase_condition"]}
    for tid, fields in expected.items():
        hidden = {el.get("if") for el in templates.TEMPLATES[tid]["elements"] if el["type"] == "rect"}
        assert set(fields) <= hidden, tid
