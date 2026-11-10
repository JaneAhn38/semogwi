import copy
import json
import os
import tempfile
import time

os.environ["SEMOGWI_DATA_DIR"] = tempfile.mkdtemp()
os.environ["SEMOGWI_DEMO_DELAY"] = "0"

import pytest
from fastapi.testclient import TestClient

from app import jobs
from app.layout import LayoutError, validate_layout
from app.main import app
from app.provider import THEMES, DemoProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
FORM = {"topic": "테스트 주제", "contentType": "goods", "style": "mint-soda"}


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def wait(client, job_id, state):
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] == state:
            return job
        time.sleep(0.01)
    raise AssertionError(f"{state} 상태가 되지 않음: {job['state']}")


def start(client, **extra):
    r = client.post("/api/jobs", data={**FORM, **extra})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_full_flow(client):
    job_id = start(client)
    job = wait(client, job_id, "waiting_outline")
    assert job["demo"] is True
    assert len(job["outline"]["cards"]) == 5
    assert job["outline"]["cards"][0]["title"] == "테스트 주제"

    assert client.post(f"/api/jobs/{job_id}/outline/regenerate").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert job["outline"]["version"] == 2

    assert client.post(f"/api/jobs/{job_id}/outline/approve").status_code == 200
    job = wait(client, job_id, "waiting_preview")
    cards = job["preview"]["cards"]
    assert [c["frame"] for c in cards] == jobs.FRAMES
    assert cards[0]["layoutName"] == "cover"
    assert len({c["layoutName"] for c in cards[1:]}) > 1

    assert client.post(f"/api/jobs/{job_id}/preview/approve").status_code == 200
    job = wait(client, job_id, "done")
    assert all(s["status"] == "done" for s in job["steps"])


def test_card_regenerate_rules(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    client.post(f"/api/jobs/{job_id}/outline/approve")
    before = wait(client, job_id, "waiting_preview")["preview"]["cards"]

    assert client.post(f"/api/jobs/{job_id}/preview/cards/card-01/regenerate").status_code == 409
    assert client.post(f"/api/jobs/{job_id}/preview/cards/card-99/regenerate").status_code == 409
    after = client.post(f"/api/jobs/{job_id}/preview/cards/card-03/regenerate").json()["preview"]["cards"]
    assert after[2]["layoutName"] != before[2]["layoutName"]
    assert after[1] == before[1] and after[3] == before[3]


def test_wrong_state_is_conflict(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    assert client.post(f"/api/jobs/{job_id}/preview/approve").status_code == 409


@pytest.mark.parametrize("data", [
    {"topic": "   "},
    {"topic": "가" * 31},
    {"contentType": "other"},
    {"style": "other"},
    {"url": "javascript:alert(1)"},
    {"url": "ftp://example.com/a"},
])
def test_invalid_input(client, data):
    assert client.post("/api/jobs", data={**FORM, **data}).status_code == 400


def test_image_validation(client):
    def post(content, meta):
        return client.post("/api/jobs", data={**FORM, "imageMeta": json.dumps(meta)}, files=[("images", ("a.png", content, "image/png"))])

    assert post(b"not image", [{"rights": "확인 필요"}]).status_code == 400
    assert post(PNG, [{"rights": "허가됨", "source": ""}]).status_code == 400  # 출처 없는 허가
    assert post(PNG, [{"rights": "이상한 값"}]).status_code == 400
    assert post(PNG, []).status_code == 400
    assert post(b"\x89PNG\r\n\x1a\n" + b"\0" * (10 * 1024 * 1024), [{"rights": "확인 필요"}]).status_code == 400
    assert post(PNG, [{"rights": "확인 필요"}]).status_code == 201


def test_only_permitted_images_reach_cards(client):
    files = [("images", ("ok.png", PNG, "image/png")), ("images", ("../../no.png", PNG, "image/png"))]
    meta = [{"rights": "허가됨", "source": "직접 촬영"}, {"rights": "확인 필요"}]
    r = client.post("/api/jobs", data={**FORM, "imageMeta": json.dumps(meta)}, files=files)
    job = r.json()
    allowed, blocked = job["assets"]
    wait(client, job["id"], "waiting_outline")
    client.post(f"/api/jobs/{job['id']}/outline/approve")
    job = wait(client, job["id"], "waiting_preview")
    used = [e["assetId"] for c in job["preview"]["cards"] for e in c["spec"]["elements"] if e["type"] == "image"]
    # 허가된 이미지는 앞 카드부터 한 장씩만 쓰고, 나머지 카드에 반복하지 않음
    assert used == [allowed["id"]]

    # 서버가 정한 이름으로만 저장되고, 올린 파일은 그대로 내려받을 수 있음
    saved = sorted(p.name for p in jobs.job_dir(job["id"]).joinpath("uploads").iterdir())
    assert saved == sorted([allowed["id"] + ".png", blocked["id"] + ".png"])
    res = client.get(f"/api/jobs/{job['id']}/assets/{allowed['id']}")
    assert res.status_code == 200 and res.content == PNG
    assert client.get(f"/api/jobs/{job['id']}/assets/nope").status_code == 404


def test_bad_job_id(client):
    assert client.get("/api/jobs/..%2F..%2Fetc").status_code == 404
    assert client.get("/api/jobs/" + "0" * 32).status_code == 404


def test_local_only_guards():
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/options").status_code == 403
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        r = c.post("/api/jobs", data=FORM, headers={"Origin": "http://evil.example"})
        assert r.status_code == 403
        home = c.get("/")
        assert home.status_code == 200 and "script-src 'self'" in home.headers["content-security-policy"]


def demo_spec():
    job = {"id": "x", "topic": "주제", "contentType": "goods", "style": "mint-soda", "assets": [], "outline": None}
    card = DemoProvider().create_outline(job)[1]
    return DemoProvider().create_layout(job, "card-02", card, "image-top", 0)


@pytest.mark.parametrize("name", ["cover", "image-top", "image-left", "text-top", "text-focus", "text-note"])
@pytest.mark.parametrize("style", list(THEMES))
def test_all_demo_layouts_are_valid(name, style):
    job = {"id": "x", "topic": "가" * 30, "contentType": "collab", "style": style, "assets": [], "outline": None}
    for frame_index, frame in enumerate(jobs.FRAMES):
        card = DemoProvider().create_outline(job)[frame_index]
        validate_layout(DemoProvider().create_layout(job, frame, card, name, 3), set(THEMES), set())


def mutate(fn):
    spec = copy.deepcopy(demo_spec())
    fn(spec)
    return spec


def by_role(spec, role):
    return next(e for e in spec["elements"] if e.get("role") == role)


@pytest.mark.parametrize("fn", [
    lambda s: by_role(s, "title").update(box={"x": 80, "y": 500, "w": 920, "h": 200}),      # 이미지와 겹침
    lambda s: by_role(s, "body").update(box={"x": 0, "y": 985, "w": 1080, "h": 240}),       # 안전 여백 밖
    lambda s: by_role(s, "title").update(color="#ff0000"),                                  # 토큰이 아닌 색
    lambda s: by_role(s, "title").update(font="Comic Sans"),                                # 허용되지 않은 폰트
    lambda s: s["elements"].remove(by_role(s, "body")),                                     # 본문 없음
    lambda s: s.update(themeId="unknown"),                                                  # 없는 테마
    lambda s: next(e for e in s["elements"] if e["type"] == "image").update(fit="cover"),   # 이미지 자르기
    lambda s: next(e for e in s["elements"] if e["type"] == "image").update(assetId="zz"),  # 작업에 없는 이미지
    lambda s: s["elements"].append({"type": "script", "src": "x"}),                         # 없는 요소
])
def test_validator_rejects_bad_ai_output(fn):
    with pytest.raises(ValueError):
        validate_layout(mutate(fn), set(THEMES), set())
