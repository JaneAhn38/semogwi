"""고정 템플릿(작업 형식 3, 유형별 5장) 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

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

USE_TEMPLATES = True  # conftest: 이 파일은 템플릿 형식을 켭니다

TYPES = ["character", "goods", "collab", "popup"]
PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x03\x20\0\0\x03\x20" + b"\0" * 32
WIKI = "https://ko.wikipedia.org/wiki/치이카와"
OFFICIAL = "https://brand-official.example/news/1"
BASE = {"topic": "치이카와 친구들", "contentType": "character", "url": "", "mode": "demo"}


def _value(field: dict):
    """규칙을 지키는 값. 숫자를 넣지 않아 자료 대조에 걸리지 않습니다."""
    kind = field["type"]
    if kind == "flag":
        return False
    if kind in ("text", "multiline"):
        return "확인된 내용"[: field["max"]]
    if kind == "list":
        return ["확인"]
    return [{sub["key"]: "확인 값"[: sub["max"]] for sub in field["fields"]}]


def valid_cards(type_id: str, source="출처: 공식 사이트", source_ids=("s1",), overrides=None):
    cards = []
    for frame, tid in zip(FRAMES, templates.template_set(type_id)):
        tpl = templates.TEMPLATES[tid]
        fields = {f["key"]: _value(f) for f in tpl["fields"]}
        fields.update((overrides or {}).get(frame, {}))
        cover = tpl["kind"] == "cover"
        cards.append({"frame": frame, "role": tpl["label"][:10], "fields": fields, "source": "" if cover else source,
                      "sourceIds": [] if cover else list(source_ids)})
    return cards


def type_of_schema(schema: dict) -> str:
    props = schema["properties"]["cards"]["items"]["properties"]["fields"]["properties"]
    for type_id, key in (("goods", "lineup_name"), ("collab", "brand_name"), ("popup", "start_date")):
        if key in props:
            return type_id
    return "character"


class Fake:
    def __init__(self):
        self.calls = []
        self.overrides = None
        self.rewrite_overrides = None
        self.classified = "popup"
        self.fetched = True

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "tools": tools})
        run = CliRun(model="fake", turns=1)
        props = schema["properties"]
        if "contentType" in props:
            run.structured = {"contentType": self.classified, "reason": "기간과 장소가 있는 행사"}
            return run
        if "theme" in props or "elements" in json.dumps(props):
            raise AssertionError("고정 템플릿 작업은 디자인 AI를 부르면 안 돼요")
        type_id = type_of_schema(schema)
        if "sources" in props:
            run.searches = [{"query": "q", "results": [{"title": "공식", "url": OFFICIAL}]}]
            run.fetches = [{"url": OFFICIAL, "code": 200}] if self.fetched else []
            run.structured = {"status": "ok", "missing": [], "sources": [{"id": "s1", "title": "공식", "url": OFFICIAL, "kind": "official"}],
                              "facts": [{"text": "확인된 사실", "sourceIds": ["s1"]}], "cards": valid_cards(type_id, overrides=self.overrides)}
        elif "status" in props:
            run.structured = {"status": "ok", "missing": [], "cards": valid_cards(type_id, "출처: 공식 계정", ("user1",))}
        else:
            frames = [f for f in FRAMES if f in prompt.split("다시 쓸 카드:")[-1]]
            cards = valid_cards(type_id, overrides=self.rewrite_overrides)
            run.structured = {"cards": [c for c in cards if c["frame"] in frames]}
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
    raise AssertionError(f"{states}: {job['state']} {job.get('error')} {job.get('aiError')}")


def start(client, **extra):
    job_id = client.post("/api/jobs/draft").json()["id"]
    r = api(client, job_id, "POST", "/start", json={**BASE, **extra})
    assert r.status_code == 200, r.text
    return job_id


def upload(client, job_id, rights="허가됨"):
    r = api(client, job_id, "POST", "/assets", files={"image": ("pic.png", PNG, "image/png")}, data={"rights": rights, "source": "세모귀 팀"})
    assert r.status_code == 201, r.text
    return r.json()["assets"][-1]["id"]


def edit(client, job_id, frame, fields, role="카드", source="출처: 공식 계정"):
    return api(client, job_id, "PUT", f"/outline/cards/{frame}", json={"role": role, "fields": fields, "source": source})


def approve_all(client, job_id):
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    wait(client, job_id, "waiting_preview")
    assert api(client, job_id, "POST", "/preview/approve").status_code == 200
    return wait(client, job_id, "done")


# ---------- 템플릿 파일 ----------
def test_twenty_templates_load_in_four_sets():
    for type_id in TYPES:
        ids = templates.template_set(type_id)
        assert ids == [f"{type_id}-0{i}" for i in range(1, 6)] and templates.enabled(type_id)
        assert [templates.TEMPLATES[i]["kind"] for i in ids] == ["cover"] + ["body"] * 4
        for tid in ids:
            tpl = templates.TEMPLATES[tid]
            assert (templates.TEMPLATE_DIR / tpl["reference"]).is_file(), tid
            assert "sample" in tpl  # 참고 PNG와 비교할 때 쓰는 자리표시 예시
    assert {templates.TEMPLATES[t]["palette"]["accent"] for t in ("character-01", "goods-01", "collab-01", "popup-01")} == {"#F7C6D3", "#FDE7A6", "#C9D8F5", "#BFE6D5"}


@pytest.mark.parametrize("tid, label, field", [
    ("character-05", "공식 계정", "official_account"), ("goods-05", "판매처", "seller"), ("collab-05", "핵심 혜택", "key_benefit"),
    ("popup-05", "추천 시간", "recommended_time"), ("popup-02", "휴무", "closed_days"), ("collab-02", "기간", "period"), ("goods-03", "소재", "material"),
])
def test_labels_of_optional_fields_hide_with_value(tid, label, field):
    """선택 필드가 비면 그 줄의 이름표와 체크 아이콘도 그리지 않습니다 (실제 실행에서 "공식 계정" 이름만 남았던 문제)."""
    elements = templates.TEMPLATES[tid]["elements"]
    assert next(e for e in elements if e.get("text") == label).get("if") == field
    value = next(e for e in elements if e.get("field") == field)
    checks = [e for e in elements if e["type"] == "check" and abs(e["cy"] - (value["box"]["y"] + value["box"]["h"] / 2)) < 30]
    assert all(c.get("if") == field for c in checks)


def test_requested_character_profile_fields():
    keys = {f["key"] for f in templates.TEMPLATES["character-02"]["fields"]}
    assert {"character_name", "birthday", "favorite_things", "creator", "feature_tags", "debut_year", "debut_work"} <= keys
    assert templates.TEMPLATES["character-02"]["images"][0]["key"] == "character_image"
    assert templates.TEMPLATES["goods-02"]["fields"][0]["maxItems"] == 4 and len(templates.TEMPLATES["goods-02"]["images"]) == 4


def test_bad_templates_are_rejected(tmp_path):
    good = json.loads((templates.TEMPLATE_DIR / "character-03.json").read_text(encoding="utf-8"))
    broken_cases = [
        {**good, "elements": good["elements"] + [{"type": "text", "field": "nope", "box": {}}]},
        {**good, "elements": good["elements"] + [{"type": "text", "field": "traits.5.keyword", "box": {}}]},
        {**good, "elements": good["elements"] + [{"type": "text", "field": "traits.0.color", "box": {}}]},
        {**good, "elements": good["elements"] + [{"type": "text", "text": "[캐릭터 이름]", "box": {}}]},
        {**good, "elements": good["elements"] + [{"type": "text", "text": "{unknown}", "box": {}}]},
        {**good, "elements": good["elements"] + [{"type": "image", "slot": "other", "box": {}}]},
        {**good, "fields": good["fields"] + [{"key": "x", "label": "x", "type": "color"}]},
        {**good, "inherit": ["traits"]},
    ]
    for broken in broken_cases:
        (tmp_path / "t.json").write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(templates.TemplateError):
            templates.load_all(tmp_path)


def test_options_send_templates_without_reference_data(client):
    options = client.get("/api/options").json()
    assert len([t for t in options["templates"] if t[-3] == "-"]) == 20
    assert options["templateTypes"] == sorted(TYPES)
    assert "reference" not in options["templates"]["goods-02"] and "sample" not in options["templates"]["goods-02"]
    assert {t["label"] for t in options["contentTypes"]} == {"캐릭터 소개", "굿즈 판매", "콜라보", "팝업스토어"}


def test_static_files_are_revalidated(client):
    # 옛 renderer.js를 캐시에서 꺼내 새 app.js와 섞어 쓰지 않도록 매번 확인합니다 (renderTemplate is not a function)
    for path in ("/", "/renderer.js", "/app.js"):
        assert client.get(path).headers["cache-control"] == "no-cache"
    assert "cache-control" not in client.get("/api/options").headers
    html = client.get("/").text
    assert "/renderer.js?v=" in html and "/app.js?v=" in html


# ---------- 필드 검사 ----------
@pytest.mark.parametrize("tid, fields, message", [
    ("character-02", {"character_name": ""}, "꼭 필요한 항목"),
    ("character-02", {"character_name": "가" * 13}, "12자 이내"),
    ("character-02", {"character_name": "치이", "feature_tags": ["하나", "둘", "셋", "넷"]}, "3개까지"),
    ("character-02", {"character_name": "치이", "birthday": "MM월 DD일"}, "자리표시"),
    ("character-03", {"traits": [{"label": "공식 설정", "keyword": "", "description": "설명"}]}, "특징 키워드: 꼭 필요한"),
    ("character-03", {"traits": [{"keyword": "울보"}] * 3}, "2개까지"),
    ("goods-02", {"goods": [{"name": "[굿즈 이름]", "kind": "", "price": ""}]}, "자리표시"),
    ("goods-02", {"goods": [{"name": "키링", "kind": "", "price": "1,500원원원원원원"}]}, "9자 이내"),
])
def test_field_rules(tid, fields, message):
    tpl = templates.TEMPLATES[tid]
    errors = templates.check_fields(tpl, templates.clean_fields(tpl, fields))["errors"]
    assert any(message in e for e in errors), errors


def test_clean_fields_normalizes_values():
    tpl = templates.TEMPLATES["goods-01"]
    cleaned = templates.clean_fields(tpl, {"character_name": " 치이 \n카와 ", "is_new": "true", "release_date": 3})
    assert cleaned["character_name"] == "치이 카와" and cleaned["is_new"] is False and cleaned["release_date"] == "3"
    assert templates.clean_fields(tpl, {"is_new": True})["is_new"] is True
    items = templates.clean_fields(templates.TEMPLATES["character-03"], {"traits": [{"keyword": " 울보 "}, {}, "x"]})["traits"]
    assert items == [{"label": "", "keyword": "울보", "description": ""}]
    with pytest.raises(ValueError):
        templates.clean_fields(tpl, {"color": "red"}, strict=True)


# ---------- 데모 흐름: 유형마다 5장 ----------
@pytest.mark.parametrize("type_id", TYPES)
def test_demo_flow_makes_five_cards_per_type(client, fake, type_id):
    job_id = start(client, contentType=type_id)
    job = wait(client, job_id, "waiting_outline")
    assert job["format"] == templates.FORMAT and job["templateSet"] == templates.template_set(type_id)
    assert [c["template"] for c in job["outline"]["cards"]] == job["templateSet"]
    assert not any(i["errors"] for i in job["outline"]["issues"].values()), job["outline"]["issues"]
    texts = templates.card_text({"fields": {k: v for c in job["outline"]["cards"] for k, v in c["fields"].items()}})
    assert not templates.PLACEHOLDER_RE.search(texts)
    job = approve_all(client, job_id)
    specs = [c["spec"] for c in job["preview"]["cards"]]
    assert [s["template"] for s in specs] == job["templateSet"] and [s["page"] for s in specs] == [1, 2, 3, 4, 5]
    assert fake.calls == []


def test_goods_new_badge_is_off_in_demo_and_editable(client):
    job_id = start(client, contentType="goods")
    job = wait(client, job_id, "waiting_outline")
    fields = job["outline"]["cards"][0]["fields"]
    assert fields["is_new"] is False  # 신상품이라고 주장하지 않습니다
    assert edit(client, job_id, "card-01", {**fields, "is_new": True}, role="표지", source="").status_code == 200
    assert get(client, job_id)["outline"]["cards"][0]["fields"]["is_new"] is True
    assert edit(client, job_id, "card-01", {**fields, "is_new": "true"}, role="표지", source="").status_code == 200
    assert get(client, job_id)["outline"]["cards"][0]["fields"]["is_new"] is False  # 문자열은 참으로 보지 않습니다


def test_collab_cards_inherit_brand_from_cover(client):
    job_id = start(client, contentType="collab")
    wait(client, job_id, "waiting_outline")
    cover = {"brand_name": "세모카페", "character_name": "세모귀", "summary": "한정 음료가 나와요", "period": ""}
    assert edit(client, job_id, "card-01", cover, role="표지", source="").status_code == 200
    job = approve_all(client, job_id)
    spec = job["preview"]["cards"][1]["spec"]
    assert spec["fields"]["brand_name"] == "세모카페" and spec["fields"]["character_name"] == "세모귀"
    assert "brand_name" not in job["outline"]["cards"][1]["fields"]  # 본문 카드에는 저장하지 않습니다
    r = edit(client, job_id, "card-02", {**job["outline"]["cards"][1]["fields"], "brand_name": "x"})
    assert r.status_code == 409 and "알 수 없는 항목" in r.json()["detail"]


def slot(image, variant="original", **extra):
    return {"assetId": image, "variant": variant, "keepOriginal": False, "scale": 1.0, "dx": 0.0, "dy": 0.0, **extra}


def test_multi_slot_images(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    ids = [upload(client, job_id) for _ in range(3)]
    api(client, job_id, "POST", "/start", json={**BASE, "contentType": "goods"})
    job = wait(client, job_id, "waiting_outline")
    # 추천은 제안만 하고 카드에는 넣지 않습니다
    assert all(image is None for slots in job["slotImages"].values() for image in slots.values())
    assert job["slotSuggestions"]["card-01"] == {"main_goods_image": {"assetId": ids[0], "variant": "original"}}
    assert job["slotSuggestions"]["card-02"]["goods_image_1"]["assetId"] == ids[1]
    job = api(client, job_id, "POST", "/slot-suggestions/apply", json={"frame": "card-01", "slot": "main_goods_image"}).json()
    assert job["slotImages"]["card-01"] == {"main_goods_image": slot(ids[0])}
    assert job["slotImages"]["card-02"]["goods_image_1"] is None and job["slotSuggestions"]["card-02"]["goods_image_1"]["assetId"] == ids[1]
    job = api(client, job_id, "POST", "/slot-suggestions/apply", json={}).json()
    assert job["slotImages"]["card-02"]["goods_image_1"]["assetId"] == ids[1] and job["slotImages"]["card-02"]["goods_image_2"]["assetId"] == ids[2]
    assert job["slotImages"]["card-02"]["goods_image_3"] is None and job["slotSuggestions"] == {}
    assert api(client, job_id, "POST", "/slot-suggestions/apply", json={}).status_code == 409
    assert api(client, job_id, "PUT", "/cards/card-02/slots/goods_image_4", json={"assetId": ids[0], "variant": "original"}).status_code == 200
    assert api(client, job_id, "PUT", "/cards/card-02/slots/main_goods_image", json={"assetId": ids[0]}).status_code == 409
    job = approve_all(client, job_id)
    assert job["preview"]["cards"][1]["spec"]["images"]["goods_image_4"]["assetId"] == ids[0]
    assert api(client, job_id, "PUT", "/cards/card-02/slots/goods_image_4", json={"assetId": None}).status_code == 200
    assert get(client, job_id)["state"] == "waiting_preview"


CUTOUT_STATS = {"format": "PNG", "mode": "RGBA", "width": 800, "height": 800, "transparent": 0.6, "opaque": 0.3, "bbox": [200, 100, 600, 700], "holes": 0.0}


def fake_cutout(monkeypatch):
    def run(source, target, model):
        target.write_bytes(PNG + b"cutout")
        return {**CUTOUT_STATS, "model": "isnet-general-use", "tried": []}

    monkeypatch.setattr(jobs.cutout, "run_cutout", run)
    monkeypatch.setattr(jobs.cutout, "status", lambda: {"available": True, "models": [{"id": "auto", "label": "x"}], "reason": ""})


def run_cutout(client, job_id, asset_id):
    assert api(client, job_id, "POST", f"/assets/{asset_id}/cutout", json={"model": "auto"}).status_code == 202
    for _ in range(300):
        job = get(client, job_id)
        if next(a for a in job["assets"] if a["id"] == asset_id)["cutout"]["status"] != "processing":
            return job
        time.sleep(0.01)
    raise AssertionError("누끼가 끝나지 않음")


def test_cutout_result_goes_to_slots_but_keeps_explicit_original(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    a, b = upload(client, job_id), upload(client, job_id)
    api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": a, "variant": "original"})
    api(client, job_id, "PUT", "/cards/card-02/slots/character_image", json={"assetId": a, "variant": "original"})
    approve_all(client, job_id)
    # 누끼가 끝나면 그 이미지를 쓰는 자리에 반영하고, 디자인 승인은 다시 받습니다
    job = run_cutout(client, job_id, a)
    asset = next(x for x in job["assets"] if x["id"] == a)
    assert asset["useVariant"] == "cutout" and asset["cutout"]["stats"]["bbox"] == CUTOUT_STATS["bbox"]
    assert job["slotImages"]["card-01"]["character_image"]["variant"] == "cutout"
    assert job["slotImages"]["card-02"]["character_image"]["variant"] == "cutout"
    assert job["preview"]["cards"][0]["spec"]["images"]["character_image"]["variant"] == "cutout"
    assert job["state"] == "waiting_preview" and not job["preview"]["approved"]
    # card-02에서 원본을 직접 고르면, 다시 누끼를 만들어도 원본을 유지합니다
    job = api(client, job_id, "PUT", "/cards/card-02/slots/character_image", json={"assetId": a, "variant": "original"}).json()
    assert job["slotImages"]["card-02"]["character_image"]["keepOriginal"] is True
    job = run_cutout(client, job_id, a)
    assert job["slotImages"]["card-01"]["character_image"]["variant"] == "cutout"
    assert job["slotImages"]["card-02"]["character_image"]["variant"] == "original"
    # 배경 제거 OFF: 자리마다 원본으로. 다시 ON이면 직접 원본을 고른 자리는 그대로
    job = api(client, job_id, "PATCH", f"/assets/{a}", json={"useVariant": "original"}).json()
    assert job["slotImages"]["card-01"]["character_image"]["variant"] == "original"
    job = api(client, job_id, "PATCH", f"/assets/{a}", json={"useVariant": "cutout"}).json()
    assert job["slotImages"]["card-01"]["character_image"]["variant"] == "cutout"
    assert job["slotImages"]["card-02"]["character_image"]["variant"] == "original"
    # 누끼가 없는 이미지는 자리에서 원본을 골라도 '직접 선택'이 아닙니다 (누끼가 끝나면 반영)
    job = api(client, job_id, "PUT", "/cards/card-03/slots/trait_image_1", json={"assetId": b, "variant": "original"}).json()
    assert job["slotImages"]["card-03"]["trait_image_1"]["keepOriginal"] is False
    job = run_cutout(client, job_id, b)
    assert job["slotImages"]["card-03"]["trait_image_1"]["variant"] == "cutout"


def test_slot_adjust_restore_and_saved_values(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    a, b = upload(client, job_id), upload(client, job_id)
    assert api(client, job_id, "PUT", "/cards/card-01/slots/character_image/adjust", json={"scale": 1.2, "dx": 0, "dy": 0}).status_code == 409
    api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": a, "variant": "original"})
    run_cutout(client, job_id, a)
    job = api(client, job_id, "PUT", "/cards/card-01/slots/character_image/adjust", json={"scale": 1.4, "dx": 0.1, "dy": -0.25}).json()
    assert job["slotImages"]["card-01"]["character_image"] == slot(a, "cutout", scale=1.4, dx=0.1, dy=-0.25)
    assert jobs.load(job_id)["slotImages"]["card-01"]["character_image"]["scale"] == 1.4  # 작업 데이터에 저장
    for bad in ({"scale": 5, "dx": 0, "dy": 0}, {"scale": 1, "dx": 2, "dy": 0}, {"scale": 1, "dx": 0}):
        assert api(client, job_id, "PUT", "/cards/card-01/slots/character_image/adjust", json=bad).status_code in (400, 422)
    # 같은 이미지에서 원본/누끼만 바꾸면 조정값을 유지하고, 다른 이미지로 바꾸면 초기화합니다
    job = api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": a, "variant": "original"}).json()
    assert job["slotImages"]["card-01"]["character_image"]["scale"] == 1.4
    job = api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": a, "variant": "cutout"}).json()
    assert job["slotImages"]["card-01"]["character_image"]["keepOriginal"] is False
    # 원본 복원: 원본으로, 조정 초기화, 이후 누끼를 다시 만들어도 원본 유지
    job = api(client, job_id, "POST", "/cards/card-01/slots/character_image/restore").json()
    assert job["slotImages"]["card-01"]["character_image"] == slot(a, keepOriginal=True)
    assert run_cutout(client, job_id, a)["slotImages"]["card-01"]["character_image"]["variant"] == "original"
    job = api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": b, "variant": "original"}).json()
    assert job["slotImages"]["card-01"]["character_image"] == slot(b)
    job = approve_all(client, job_id)
    assert job["preview"]["cards"][0]["spec"]["images"]["character_image"]["assetId"] == b


def test_upload_into_card_slot_from_outline(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    path = "/cards/card-03/slots/trait_image_1/upload"
    files = {"image": ("plush.png", PNG, "image/png")}
    r = api(client, job_id, "POST", path, files=files, data={"rights": "허가됨", "source": "직접 촬영"})
    assert r.status_code == 201, r.text
    job = r.json()
    new_id = job["assets"][-1]["id"]
    assert job["slotImages"]["card-03"]["trait_image_1"] == slot(new_id)
    # 교체
    job = api(client, job_id, "POST", path, files=files, data={"rights": "허가됨", "source": "직접 촬영"}).json()
    assert job["slotImages"]["card-03"]["trait_image_1"]["assetId"] == job["assets"][-1]["id"] != new_id
    before = len(job["assets"])
    assert api(client, job_id, "POST", path, files=files, data={"rights": "확인 필요", "source": ""}).status_code == 400
    assert api(client, job_id, "POST", path, files=files, data={"rights": "허가됨", "source": ""}).status_code == 400
    assert api(client, job_id, "POST", "/cards/card-05/slots/nothing/upload", files=files, data={"rights": "허가됨", "source": "x"}).status_code == 409
    assert len(get(client, job_id)["assets"]) == before  # 거절된 업로드는 저장하지 않습니다


def test_character_card_labels():
    assert templates.TEMPLATES["character-03"]["label"] == "성격과 특징"
    assert templates.TEMPLATES["character-04"]["label"] == "친구와 TMI"


def test_cards_are_kept_in_frame_order(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    approve_all(client, job_id)
    stored = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    stored["outline"]["cards"].reverse()
    stored["preview"]["cards"] = [stored["preview"]["cards"][i] for i in (2, 0, 4, 1, 3)]
    jobs._path(job_id).write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    assert [c["frame"] for c in job["outline"]["cards"]] == FRAMES == [c["frame"] for c in job["preview"]["cards"]]


def test_renderer_has_no_mascot_placeholder_for_empty_slot():
    source = (jobs.Path(__file__).resolve().parents[1] / "static" / "renderer.js").read_text(encoding="utf-8")
    body = source[source.index("async function drawSlot"):source.index("const CUTOUT_FILL")]
    empty = body[body.index("if (!image)"):body.index("return true;")]
    assert "drawLogo(" not in empty and "fillText(" not in empty


def test_edit_validation_and_preview_rebuild(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    fields = {"character_name": "하치와레", "birthday": "", "favorite_things": "", "creator": "", "feature_tags": ["다정함"], "debut_year": "", "debut_work": "", "profile_no": ""}
    r = edit(client, job_id, "card-02", {**fields, "debut_work": "[작품]"})
    assert r.status_code == 409 and "자리표시" in r.json()["detail"]
    assert edit(client, job_id, "card-02", fields).status_code == 200
    job = approve_all(client, job_id)
    assert job["preview"]["cards"][1]["spec"]["fields"]["character_name"] == "하치와레"
    assert edit(client, job_id, "card-02", {**fields, "character_name": "우사기"}).status_code == 200
    assert get(client, job_id)["state"] == "waiting_outline"


@pytest.mark.parametrize("path, method", [
    ("/preview/regenerate", "POST"), ("/preview/cards/card-02/regenerate", "POST"), ("/preview/cards/card-02/ai-redesign", "POST"),
    ("/preview/cards/card-02/restore", "POST"), ("/preview/cards/card-02/design-requests", "POST"), ("/preview/cards/card-02/image", "PUT"),
])
def test_layout_tools_are_closed_for_templates(client, path, method):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    api(client, job_id, "POST", "/outline/approve")
    wait(client, job_id, "waiting_preview")
    body = {"text": "크게"} if "requests" in path or "redesign" in path else {"assetId": None}
    r = api(client, job_id, method, path, json=body)
    assert r.status_code == 409 and "고정 템플릿" in r.json()["detail"]


# ---------- 유형 자동 판단과 변경 ----------
@pytest.mark.parametrize("topic, expected", [("치이카와 팝업스토어", "popup"), ("세모카페 콜라보", "collab"), ("먼작귀 키링 발매", "goods"), ("하치와레 소개", "character")])
def test_demo_auto_type_uses_keywords(client, fake, topic, expected):
    job_id = start(client, topic=topic, contentType="auto")
    job = wait(client, job_id, "waiting_outline")
    assert (job["contentType"], job["typeSource"]) == (expected, "keyword") and fake.calls == []


def test_ai_auto_type_classifies_without_web_then_researches(client, fake):
    job_id = start(client, topic="세모귀 팝업", contentType="auto", mode="ai")
    job = wait(client, job_id, "waiting_outline")
    assert (job["contentType"], job["typeSource"], job["typeReason"]) == ("popup", "ai", "기간과 장소가 있는 행사")
    assert fake.calls[0]["tools"] == () and "contentType" in fake.calls[0]["schema"]["properties"]
    assert type_of_schema(fake.calls[1]["schema"]) == "popup" and fake.calls[1]["tools"] == ("WebSearch", "WebFetch")
    assert job["aiCalls"][0]["kind"] == "classify"


def test_auto_type_on_restricted_site_makes_no_ai_call(client, fake):
    job_id = start(client, topic="치이카와 키링", contentType="auto", mode="ai", url="https://chiikawamarket.jp/ko/products/1")
    job = get(client, job_id)
    assert job["state"] == "waiting_material" and (job["contentType"], job["typeSource"]) == ("goods", "keyword") and fake.calls == []


def test_demo_type_change_rebuilds_outline(client):
    job_id = client.post("/api/jobs/draft").json()["id"]
    upload(client, job_id)
    api(client, job_id, "POST", "/start", json=BASE)
    wait(client, job_id, "waiting_outline")
    approve_all(client, job_id)
    r = api(client, job_id, "PUT", "/content-type", json={"contentType": "popup"})
    job = r.json()
    assert r.status_code == 200 and job["state"] == "waiting_outline" and not job["outline"]["approved"]
    assert job["templateSet"] == templates.template_set("popup") and [c["template"] for c in job["outline"]["cards"]] == job["templateSet"]
    assert job["preview"] is None and job["typeSource"] == "user" and "poster_image" in job["slotImages"]["card-01"]
    assert api(client, job_id, "PUT", "/content-type", json={"contentType": "auto"}).status_code == 400


def test_ai_type_change_rewrites_from_saved_research(client, fake):
    job_id = start(client, mode="ai")
    wait(client, job_id, "waiting_outline")
    count = len(fake.calls)
    assert api(client, job_id, "PUT", "/content-type", json={"contentType": "goods"}).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    call = fake.calls[count]
    assert call["tools"] == () and type_of_schema(call["schema"]) == "goods" and "유형이 바뀌었다" in call["prompt"]
    assert job["contentType"] == "goods" and [c["template"] for c in job["outline"]["cards"]] == templates.template_set("goods")
    assert job["outline"]["version"] == 2 and len(fake.calls) == count + 1


def test_legacy_format_jobs_cannot_change_type(client, monkeypatch):
    monkeypatch.setattr(templates, "ENABLED_TYPES", set())
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    r = api(client, job_id, "PUT", "/content-type", json={"contentType": "goods"})
    assert r.status_code == 409


# ---------- 실제 AI 흐름 (가짜 Claude) ----------
def test_ai_research_fills_template_fields_and_skips_design_ai(client, fake):
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    call = fake.calls[0]
    assert "제목: 16자 이하" not in call["system"] and "세모귀 말투" in call["system"]
    assert "card-03 (성격과 특징)" in call["prompt"] and "억지로 채우지 않는다" in call["prompt"]
    assert job["outline"]["cards"][2]["fields"]["traits"][0]["keyword"] == "확인 값"
    assert not any(i["errors"] for i in job["outline"]["issues"].values())
    api(client, job_id, "POST", "/outline/approve")
    wait(client, job_id, "waiting_preview")
    assert len(fake.calls) == 1
    r = api(client, job_id, "POST", "/preview/approve")
    assert r.status_code == 409 and "card-01 대표 캐릭터 이미지" in r.json()["detail"]
    asset = upload(client, job_id)
    api(client, job_id, "PUT", "/cards/card-01/slots/character_image", json={"assetId": asset, "variant": "original"})
    assert api(client, job_id, "POST", "/preview/approve").status_code == 200


def test_ai_overlong_field_gets_one_rewrite_but_missing_value_does_not(client, fake):
    fake.overrides = {"card-02": {"character_name": "가" * 20}}
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == 2 and job["outline"]["cards"][1]["fields"]["character_name"] == "확인된 내용"

    fake.calls.clear()
    fake.overrides = {"card-01": {"character_name": ""}}  # 확인하지 못한 이름: 다시 쓰게 하지 않고 사용자에게 입력을 요청합니다
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == 1
    assert any("꼭 필요한 항목" in e for e in job["outline"]["issues"]["card-01"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


def test_ai_goods_price_must_come_from_material(client, fake):
    # 자료에 없는 가격은 한 번 다시 쓰게 하고
    fake.overrides = {"card-03": {"featured_price": "9,900원"}}
    job_id = start(client, mode="ai", contentType="goods", topic="세모귀 키링")
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == 2 and job["outline"]["cards"][2]["fields"]["featured_price"] == "확인된 내용"
    # 그래도 남으면 승인을 막습니다
    fake.calls.clear()
    fake.rewrite_overrides = {"card-03": {"featured_price": "9,900원"}}
    job_id = start(client, mode="ai", contentType="goods", topic="세모귀 키링")
    job = wait(client, job_id, "waiting_outline")
    assert any("9,900" in e for e in job["outline"]["issues"]["card-03"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


def test_ai_listing_only_source_blocks_goods_and_warns_character(client, fake):
    fake.fetched = False
    job_id = start(client, mode="ai", contentType="goods", topic="세모귀 키링")
    job = wait(client, job_id, "waiting_outline")
    assert any("검색 목록에 주소만" in e for e in job["outline"]["issues"]["card-02"]["errors"])
    job_id = start(client, mode="ai")
    job = wait(client, job_id, "waiting_outline")
    issue = job["outline"]["issues"]["card-02"]
    assert not issue["errors"] and any("검색 목록에 주소만" in w for w in issue["warnings"])


def test_ai_material_marks_user_source_on_body_cards_only(client, fake):
    job_id = start(client, mode="ai", contentType="popup", topic="세모귀 팝업", url="https://chiikawamarket.jp/ko/products/1")
    material = {"name": "세모귀 팝업", "features": "기간과 장소", "seller": "공식 계정", "price": "", "sourceUrl": "", "pasted": ""}
    assert api(client, job_id, "POST", "/material", json=material).status_code == 200
    job = wait(client, job_id, "waiting_outline")
    cards = job["outline"]["cards"]
    assert cards[0]["source"] == "" and cards[1]["source"] == "출처: 공식 계정 (사용자 제공)"
    assert fake.calls[0]["tools"] == () and type_of_schema(fake.calls[0]["schema"]) == "popup"


def test_ai_card_rewrite_returns_fields(client, fake):
    job_id = start(client, mode="ai")
    wait(client, job_id, "waiting_outline")
    fake.rewrite_overrides = {"card-04": {"tmi_items": ["다시 쓴 사실"]}}
    assert api(client, job_id, "POST", "/outline/cards/card-04/regenerate").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert job["outline"]["cards"][3]["fields"]["tmi_items"] == ["다시 쓴 사실"] and job["outline"]["cards"][3]["regenCount"] == 1


# ---------- 호환 ----------
def test_previous_template_jobs_open_with_cover_and_body(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    raw["templateSet"] = None  # 예전 형식 3 작업: 표지 1종 + 본문 1종 반복
    cover = {"frame": "card-01", "template": "character-cover", "role": "표지", "fields": {"name": "치이카와", "tagline": "작은 친구"}, "source": "", "sourceIds": []}
    body = {"template": "character-body", "role": "친구", "fields": {"heading": "이 친구를 소개할게요", "profile": [{"label": "이름", "value": "하치와레"}], "tags": [], "tmi": ""},
            "source": "출처: 공식", "sourceIds": []}
    raw["outline"]["cards"] = [cover] + [{**body, "frame": f} for f in FRAMES[1:]]
    raw["outline"].pop("issues")
    raw["slotImages"] = {f: {"main": None} for f in FRAMES}
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    assert not any(i["errors"] for i in job["outline"]["issues"].values())
    job = approve_all(client, job_id)
    assert [c["spec"]["template"] for c in job["preview"]["cards"]] == ["character-cover"] + ["character-body"] * 4
    assert job["preview"]["cards"][1]["spec"]["no"] == "01"


def test_other_formats_still_open(client, monkeypatch):
    monkeypatch.setattr(templates, "ENABLED_TYPES", set())
    job_id = start(client, contentType="goods")
    job = wait(client, job_id, "waiting_outline")
    assert job["format"] == 1 and "title" in job["outline"]["cards"][0]
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    for key in ("format", "slotImages", "templateSet", "typeSource", "typeReason"):
        raw.pop(key)
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    loaded = get(client, job_id)
    assert loaded["format"] == 1 and loaded["templateSet"] is None and loaded["outline"]["cards"] == job["outline"]["cards"]
