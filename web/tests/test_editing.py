"""초안, 누끼, 구성안 수정, 승인 상태, 카드별 이미지 테스트."""

import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import jobs, outline
from app.main import app
from app.provider import THEMES, DemoProvider

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
STATS = {"format": "PNG", "mode": "RGBA", "width": 10, "height": 10, "transparent": 0.5, "opaque": 0.5}
INPUT = {"topic": "초안 주제", "contentType": "goods", "url": ""}
CARD = {"role": "소개", "title": "직접 쓴 제목", "body": "직접 쓴 본문이에요.", "source": "출처: 공식 사이트"}


@pytest.fixture
def client():
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def api(client, job_id, method, path, **kwargs):
    return client.request(method, f"/api/jobs/{job_id}{path}", **kwargs)


def get(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()


def wait(client, job_id, state):
    for _ in range(300):
        job = get(client, job_id)
        if job["state"] == state:
            return job
        time.sleep(0.01)
    raise AssertionError(f"{state} 상태가 되지 않음: {job['state']}")


def draft(client, images=0, rights="허가됨"):
    job_id = client.post("/api/jobs/draft").json()["id"]
    ids = []
    for i in range(images):
        data = {"rights": rights, "source": "직접 촬영"}
        job = api(client, job_id, "POST", "/assets", data=data, files={"image": (f"p{i}.png", PNG + bytes([i]), "image/png")}).json()
        ids.append(job["assets"][-1]["id"])
    return job_id, ids


def to_outline(client, images=0):
    job_id, ids = draft(client, images)
    assert api(client, job_id, "POST", "/start", json=INPUT).status_code == 200
    wait(client, job_id, "waiting_outline")
    return job_id, ids


def to_preview(client, images=0):
    job_id, ids = to_outline(client, images)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    wait(client, job_id, "waiting_preview")
    return job_id, ids


def to_done(client, images=0):
    job_id, ids = to_preview(client, images)
    assert api(client, job_id, "POST", "/preview/approve").status_code == 200
    wait(client, job_id, "done")
    return job_id, ids


def spec_text(card, role):
    return next((e["text"] for e in card["spec"]["elements"] if e.get("role") == role), None)


def images_of(card):
    return [e for e in card["spec"]["elements"] if e["type"] == "image"]


def fake_cutout(monkeypatch):
    def run(source, target, model):
        target.write_bytes(PNG + b"cutout")
        return STATS

    monkeypatch.setattr(jobs.cutout, "run_cutout", run)
    monkeypatch.setattr(jobs.cutout, "status", lambda: {"available": True, "models": [{"id": "isnet-anime", "label": "x"}, {"id": "u2net", "label": "y"}], "reason": ""})


def wait_cutout(client, job_id, asset_id):
    for _ in range(300):
        asset = next(a for a in get(client, job_id)["assets"] if a["id"] == asset_id)
        if asset["cutout"]["status"] != "processing":
            return asset
        time.sleep(0.01)
    raise AssertionError("누끼가 끝나지 않음")


def test_draft_keeps_input_and_needs_topic(client):
    job_id, _ = draft(client)
    assert api(client, job_id, "PATCH", "/input", json={"topic": "", "contentType": "goods", "url": ""}).status_code == 200
    assert api(client, job_id, "POST", "/start", json={"topic": " ", "contentType": "goods"}).status_code == 400
    api(client, job_id, "PATCH", "/input", json={"topic": "저장된 주제", "contentType": "popup", "url": "https://a.example"})
    job = get(client, job_id)
    assert (job["state"], job["topic"], job["contentType"], job["url"]) == ("draft", "저장된 주제", "popup", "https://a.example")
    assert job["designTheme"]["source"] == "default" and job["style"] in THEMES


def test_cutout_keeps_original_and_can_be_selected(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id, [asset_id] = draft(client, 1)
    original = jobs.uploads_dir(job_id) / f"{asset_id}.png"
    before = original.read_bytes()

    assert api(client, job_id, "POST", f"/assets/{asset_id}/cutout", json={"model": "isnet-anime"}).status_code == 202
    asset = wait_cutout(client, job_id, asset_id)
    assert asset["cutout"]["status"] == "done" and asset["useVariant"] == "cutout"  # 누끼가 끝나면 배경 제거 ON
    assert original.read_bytes() == before
    assert api(client, job_id, "GET", f"/assets/{asset_id}").content == before
    assert api(client, job_id, "GET", f"/assets/{asset_id}?variant=cutout").content == PNG + b"cutout"

    # 다시 처리해도 이전 결과를 덮어쓰지 않음
    api(client, job_id, "POST", f"/assets/{asset_id}/cutout", json={"model": "u2net"})
    assert wait_cutout(client, job_id, asset_id)["cutout"]["version"] == 2
    assert (jobs.uploads_dir(job_id) / f"{asset_id}-cutout-1.png").exists()
    assert (jobs.uploads_dir(job_id) / f"{asset_id}-cutout-2.png").exists()

    # 선택한 이미지가 제작 과정에 전달됨
    assert api(client, job_id, "PATCH", f"/assets/{asset_id}", json={"useVariant": "cutout"}).status_code == 200
    api(client, job_id, "POST", "/start", json=INPUT)
    wait(client, job_id, "waiting_outline")
    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview")
    assert job["cardImages"]["card-01"] == {"assetId": asset_id, "variant": "cutout"}


def test_cutout_failure_keeps_original_usable(client, monkeypatch):
    fake_cutout(monkeypatch)

    def fail(source, target, model):
        raise jobs.cutout.CutoutError("배경이 제대로 지워지지 않았어요.")

    monkeypatch.setattr(jobs.cutout, "run_cutout", fail)
    job_id, [asset_id] = draft(client, 1)
    api(client, job_id, "POST", f"/assets/{asset_id}/cutout", json={"model": "isnet-anime"})
    asset = wait_cutout(client, job_id, asset_id)
    assert asset["cutout"]["status"] == "failed" and "지워지지" in asset["cutout"]["error"]
    assert api(client, job_id, "PATCH", f"/assets/{asset_id}", json={"useVariant": "cutout"}).status_code == 409
    assert api(client, job_id, "GET", f"/assets/{asset_id}").status_code == 200
    api(client, job_id, "POST", "/start", json=INPUT)
    wait(client, job_id, "waiting_outline")
    api(client, job_id, "POST", "/outline/approve")
    assert wait(client, job_id, "waiting_preview")["cardImages"]["card-01"]["variant"] == "original"


def test_start_waits_for_running_cutout(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id, [asset_id] = draft(client, 1)
    job = get(client, job_id)
    job["assets"][0]["cutout"] = {"status": "processing", "file": None, "version": 0, "stats": None, "error": None, "pendingModel": "u2net"}
    jobs.save(job)
    jobs._cutout_tasks[jobs._cutout_key(job_id, asset_id)] = object()
    try:
        assert api(client, job_id, "POST", "/start", json=INPUT).status_code == 409
    finally:
        jobs._cutout_tasks.pop(jobs._cutout_key(job_id, asset_id))


def test_cutout_refuses_missing_model_without_running(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs.cutout, "model_installed", lambda model: False)
    called = []
    monkeypatch.setattr(jobs.cutout, "_run", lambda *a: called.append(a))
    for model in ("isnet-anime", "birefnet-general"):
        with pytest.raises(jobs.cutout.CutoutError):
            jobs.cutout.run_cutout(tmp_path / "a.png", tmp_path / "b.png", model)
    assert called == []


def test_api_refuses_model_that_is_not_installed(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id, [asset_id] = draft(client, 1)
    assert api(client, job_id, "POST", f"/assets/{asset_id}/cutout", json={"model": "bria-rmbg"}).status_code == 409
    assert get(client, job_id)["assets"][0]["cutout"] is None


def test_cutout_rejects_result_without_transparency(monkeypatch, tmp_path):
    class Done:
        stdout = json.dumps({**STATS, "transparent": 0.0})

    out = tmp_path / "b.png"
    out.write_bytes(PNG)
    monkeypatch.setattr(jobs.cutout, "_run", lambda *a: Done())
    with pytest.raises(jobs.cutout.CutoutError):
        jobs.cutout._check_result(out)
    assert not out.exists()


def test_cutout_rejects_translucent_subject(monkeypatch, tmp_path):
    # 털 인형 실측값: isnet-general-use가 몸통을 반투명(0.616)으로 남김. 카드 배경색이 비쳐 보입니다
    class Done:
        stdout = json.dumps({**STATS, "translucent": 0.616})

    out = tmp_path / "b.png"
    out.write_bytes(PNG)
    monkeypatch.setattr(jobs.cutout, "_run", lambda *a: Done())
    with pytest.raises(jobs.cutout.CutoutError, match="반투명"):
        jobs.cutout._check_result(out)
    assert not out.exists()


def test_auto_cutout_moves_on_after_translucent_result(monkeypatch, tmp_path):
    tried = []

    def once(source, target, model):
        tried.append(model)
        if model == "u2net":
            return {**STATS, "translucent": 0.026}
        raise jobs.cutout.CutoutError("피사체가 반투명하게 남아 배경이 비쳐 보여요.")

    monkeypatch.setattr(jobs.cutout, "model_installed", lambda model: True)
    monkeypatch.setattr(jobs.cutout, "_cutout_once", once)
    stats = jobs.cutout.run_cutout(tmp_path / "a.png", tmp_path / "b.png", "auto")
    assert tried == ["isnet-general-use", "isnet-anime", "u2net"] and stats["model"] == "u2net"
    assert [t["model"] for t in stats["tried"]] == ["isnet-general-use", "isnet-anime"]


def test_outline_edit_is_saved_and_reaches_cards(client):
    job_id, _ = to_outline(client)
    assert api(client, job_id, "PUT", "/outline/cards/card-02", json=CARD).status_code == 200
    saved = get(client, job_id)["outline"]["cards"][1]
    assert saved["title"] == CARD["title"] and saved["edited"] is True and saved["role"] == CARD["role"]

    api(client, job_id, "POST", "/outline/approve")
    card = wait(client, job_id, "waiting_preview")["preview"]["cards"][1]
    assert spec_text(card, "title") == CARD["title"]
    assert spec_text(card, "body") == CARD["body"]
    assert spec_text(card, "source") == CARD["source"]

    # 재배치해도 승인된 문구는 그대로
    after = api(client, job_id, "POST", "/preview/cards/card-02/regenerate").json()["preview"]["cards"][1]
    assert spec_text(after, "title") == CARD["title"] and spec_text(after, "body") == CARD["body"]


@pytest.mark.parametrize("change", [
    {"title": "가" * 21}, {"title": ""}, {"title": "두\n줄"}, {"body": "가" * 81}, {"body": ""},
    {"source": "공식 사이트"}, {"source": "출처: " + "가" * 30}, {"role": ""}, {"role": "가" * 11},
])
def test_outline_edit_rules(client, change):
    job_id, _ = to_outline(client)
    before = get(client, job_id)["outline"]["cards"][1]
    assert api(client, job_id, "PUT", "/outline/cards/card-02", json={**CARD, **change}).status_code == 409
    assert get(client, job_id)["outline"]["cards"][1] == before


def test_outline_rules_match_existing_slides_spec():
    path = Path(__file__).resolve().parents[2] / "scripts" / "fill_figma.py"
    spec = importlib.util.spec_from_file_location("existing_fill_figma", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (outline.TITLE_MAX, outline.TITLE_SAFE, outline.BODY_MAX, outline.BODY_MAX_LINES, outline.SOURCE_MAX, outline.SOURCE_PREFIX) == (
        module.TITLE_MAX, module.TITLE_ONE_LINE_SAFE, module.BODY_MAX, module.BODY_MAX_LINES, module.SOURCE_MAX, module.SOURCE_PREFIX)


def test_empty_source_leaves_out_source_text(client):
    job_id, _ = to_outline(client)
    api(client, job_id, "PUT", "/outline/cards/card-05", json={**CARD, "source": ""})
    api(client, job_id, "POST", "/outline/approve")
    assert spec_text(wait(client, job_id, "waiting_preview")["preview"]["cards"][4], "source") is None


def test_long_topic_blocks_approval_until_edited(client):
    job_id, _ = draft(client)
    api(client, job_id, "POST", "/start", json={"topic": "가" * 25, "contentType": "goods"})
    job = wait(client, job_id, "waiting_outline")
    assert job["outline"]["issues"]["card-01"]["errors"]
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409
    api(client, job_id, "PUT", "/outline/cards/card-01", json={**CARD, "title": "짧은 제목"})
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_selected_card_regenerate_leaves_others(client):
    job_id, _ = to_outline(client)
    api(client, job_id, "PUT", "/outline/cards/card-02", json=CARD)
    before = get(client, job_id)["outline"]["cards"]
    after = api(client, job_id, "POST", "/outline/cards/card-03/regenerate").json()["outline"]["cards"]
    assert after[2]["body"] != before[2]["body"]
    assert after[0] == before[0] and after[1] == before[1] and after[3] == before[3]


def test_outline_change_revokes_approvals_and_keeps_design_choices(client):
    job_id, _ = to_done(client, 2)
    done = get(client, job_id)
    assert done["preview"]["approved"] and done["preview"]["approvalHash"]

    # 같은 내용 저장은 승인을 해제하지 않음
    same = {k: done["outline"]["cards"][1][k] for k in ("role", "title", "body", "source")}
    assert api(client, job_id, "PUT", "/outline/cards/card-02", json=same).json()["state"] == "done"

    job = api(client, job_id, "PUT", "/outline/cards/card-02", json=CARD).json()
    assert job["state"] == "waiting_outline" and not job["outline"]["approved"] and not job["preview"]["approved"]
    assert job["preview"]["approvalHash"] is None
    assert api(client, job_id, "POST", "/preview/approve").status_code == 409

    api(client, job_id, "POST", "/outline/approve")
    job = wait(client, job_id, "waiting_preview")
    assert [c["layoutName"] for c in job["preview"]["cards"]] == [c["layoutName"] for c in done["preview"]["cards"]]
    assert job["cardImages"] == done["cardImages"]
    assert spec_text(job["preview"]["cards"][1], "title") == CARD["title"]
    assert not job["preview"]["approved"]


def test_design_change_after_done_needs_reapproval(client):
    job_id, _ = to_done(client)
    job = api(client, job_id, "POST", "/preview/cards/card-03/regenerate").json()
    assert job["state"] == "waiting_preview" and not job["preview"]["approved"] and job["outline"]["approved"]
    assert next(s for s in job["steps"] if s["key"] == "export")["status"] == "pending"
    api(client, job_id, "POST", "/preview/approve")
    assert wait(client, job_id, "done")["preview"]["approved"]


def test_download_stage_keeps_approved_specs(client):
    job_id, _ = to_preview(client)
    approved = get(client, job_id)["preview"]["cards"]
    api(client, job_id, "POST", "/preview/approve")
    assert wait(client, job_id, "done")["preview"]["cards"] == approved
    assert get(client, job_id)["preview"]["cards"] == approved


def test_card_image_selection_is_per_card(client, monkeypatch):
    fake_cutout(monkeypatch)
    job_id, [a1, a2] = to_preview(client, 2)
    job = get(client, job_id)
    assert job["cardImages"]["card-01"]["assetId"] == a1 and job["cardImages"]["card-02"]["assetId"] == a2
    assert all(job["cardImages"][f] is None for f in ("card-03", "card-04", "card-05"))
    before = job["preview"]["cards"]

    after = api(client, job_id, "PUT", "/preview/cards/card-04/image", json={"assetId": a1, "variant": "original"}).json()
    assert images_of(after["preview"]["cards"][3])[0]["assetId"] == a1
    for i in (0, 1, 2, 4):
        assert after["preview"]["cards"][i] == before[i]

    # 이미지 사용 안 함: 이미지 자리 없이 글 중심 레이아웃
    off = api(client, job_id, "PUT", "/preview/cards/card-02/image", json={"assetId": None}).json()
    assert off["cardImages"]["card-02"] is None and not images_of(off["preview"]["cards"][1])

    # 표지도 이미지를 뺄 수 있고 레이아웃은 그대로
    cover = api(client, job_id, "PUT", "/preview/cards/card-01/image", json={"assetId": None}).json()["preview"]["cards"][0]
    assert cover["layoutName"] == "cover" and not images_of(cover)

    # 아직 누끼가 없으면 고를 수 없음
    assert api(client, job_id, "PUT", "/preview/cards/card-03/image", json={"assetId": a2, "variant": "cutout"}).status_code == 409
    api(client, job_id, "POST", f"/assets/{a2}/cutout", json={"model": "isnet-anime"})
    wait_cutout(client, job_id, a2)
    picked = api(client, job_id, "PUT", "/preview/cards/card-03/image", json={"assetId": a2, "variant": "cutout"}).json()
    assert images_of(picked["preview"]["cards"][2])[0]["variant"] == "cutout"


def test_unpermitted_image_cannot_be_selected_and_is_dropped(client):
    job_id, [asset] = to_preview(client, 1)
    other = api(client, job_id, "POST", "/assets", data={"rights": "확인 필요"}, files={"image": ("x.png", PNG, "image/png")}).json()["assets"][-1]["id"]
    assert api(client, job_id, "PUT", "/preview/cards/card-02/image", json={"assetId": other}).status_code == 409

    api(client, job_id, "POST", "/preview/approve")
    wait(client, job_id, "done")
    job = api(client, job_id, "PATCH", f"/assets/{asset}", json={"rights": "허가 안 됨"}).json()
    assert job["cardImages"]["card-01"] is None and job["state"] == "waiting_preview" and not job["preview"]["approved"]
    assert not images_of(job["preview"]["cards"][0])


def test_removed_asset_keeps_files(client):
    job_id, [asset] = to_preview(client, 1)
    job = api(client, job_id, "DELETE", f"/assets/{asset}").json()
    assert job["cardImages"]["card-01"] is None
    assert (jobs.uploads_dir(job_id) / f"{asset}.png").exists()
    assert api(client, job_id, "PATCH", f"/assets/{asset}", json={"rights": "허가됨"}).status_code == 404


def test_design_request_is_saved_without_changing_card(client):
    job_id, _ = to_done(client)
    before = get(client, job_id)
    r = api(client, job_id, "POST", "/preview/cards/card-02/design-requests", json={"text": "이미지를 더 크게 배치해 줘."})
    assert r.status_code == 201
    job = r.json()
    assert job["designRequests"]["card-02"][0]["text"] == "이미지를 더 크게 배치해 줘."
    assert job["preview"] == before["preview"] and job["state"] == "done"
    assert api(client, job_id, "POST", "/preview/cards/card-02/design-requests", json={"text": " "}).status_code == 422
    assert api(client, job_id, "POST", "/preview/cards/card-02/design-requests", json={"text": "가" * 201}).status_code == 422
    # 카드를 다시 배치해도 요청은 남아 있음
    job = api(client, job_id, "POST", "/preview/cards/card-02/regenerate").json()
    assert len(job["designRequests"]["card-02"]) == 1


def test_restore_swaps_before_and_after(client):
    job_id, _ = to_preview(client)
    before = get(client, job_id)["preview"]["cards"]
    assert api(client, job_id, "POST", "/preview/cards/card-03/restore").status_code == 409
    changed = api(client, job_id, "POST", "/preview/cards/card-03/regenerate").json()["preview"]["cards"]
    assert changed[2]["previous"]["layoutName"] == before[2]["layoutName"]
    restored = api(client, job_id, "POST", "/preview/cards/card-03/restore").json()["preview"]["cards"]
    assert restored[2]["spec"] == before[2]["spec"]
    assert restored[2]["previous"]["spec"] == changed[2]["spec"]
    assert restored[1] == before[1] and restored[3] == before[3]


def test_provider_cannot_change_approved_text(client, monkeypatch):
    job_id, _ = to_preview(client)
    real = DemoProvider.create_layout

    def tampered(self, job, frame, card, layout, seed, image=None):
        return real(self, job, frame, {**card, "title": "AI가 바꾼 제목"}, layout, seed, image)

    monkeypatch.setattr(DemoProvider, "create_layout", tampered)
    before = get(client, job_id)["preview"]["cards"]
    assert api(client, job_id, "POST", "/preview/cards/card-03/regenerate").status_code == 409
    assert get(client, job_id)["preview"]["cards"] == before


def test_old_format_job_still_opens(client):
    job_id, _ = to_done(client, 1)
    path = jobs.job_dir(job_id) / "job.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    for key in ("designTheme", "designRequests", "cardImages"):
        del old[key]
    for asset in old["assets"]:
        for key in ("sha256", "useVariant", "cutout", "removed"):
            del asset[key]
    del old["outline"]["issues"], old["preview"]["approvalHash"]
    for card in old["outline"]["cards"]:
        del card["edited"], card["regenCount"]
    for card in old["preview"]["cards"]:
        del card["previous"]
    path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")

    job = get(client, job_id)
    assert job["state"] == "done" and job["designTheme"]["themeId"] == job["style"]
    assert job["cardImages"]["card-01"]["assetId"] == job["assets"][0]["id"]
    assert job["cardImages"]["card-02"] is None
    assert api(client, job_id, "PUT", "/outline/cards/card-02", json=CARD).status_code == 200
