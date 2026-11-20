"""친구 칸 사진 → 캐릭터 이름 확정 → 친구 문구 테스트. Claude와 외부 사이트에 접속하지 않습니다."""

import copy
import os
import re
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("SEMOGWI_DEMO_DELAY", "0")

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, friends, site_policy, templates
from app.claude_cli import CliRun
from app.main import app
from app.provider import FRAMES

USE_TEMPLATES = True  # conftest: 이 파일은 템플릿 형식을 켭니다

PNG = b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR\0\0\x03\x20\0\0\x03\x20" + b"\0" * 32
WIKI = "https://ko.wikipedia.org/wiki/피카츄"
DEX = "https://pokemonkorea.co.kr/pokedex/4"
SLOTS = ["friend_image_1", "friend_image_2", "friend_image_3"]
CLEAN_TMI = ["피카츄와 파이리는 함께 모험해요"]


def base_cards():
    cards = []
    for frame, tid in zip(FRAMES, templates.template_set("character")):
        tpl = templates.TEMPLATES[tid]
        fields = {}
        for f in tpl["fields"]:
            if f["type"] == "flag":
                fields[f["key"]] = False
            elif f["type"] in ("text", "multiline"):
                fields[f["key"]] = "확인된 내용"[: f["max"]]
            elif f["type"] == "list":
                fields[f["key"]] = ["확인"]
            elif f["type"] == "items":
                fields[f["key"]] = [{s["key"]: "" if s.get("hidden") else "확인 값"[: s["max"]] for s in f["fields"]}]
            else:
                fields[f["key"]] = [{"label": "항목", "value": "확인"}]
        cover = tpl["kind"] == "cover"
        cards.append({"frame": frame, "role": tpl["label"][:10], "fields": fields, "source": "" if cover else "출처: 위키백과",
                      "sourceIds": [] if cover else ["s1"]})
    cards[0]["fields"]["character_name"] = "피카츄"
    # 조사 단계의 AI는 사진을 모른 채 다른 친구를 골랐습니다 (이번 버그의 원래 모습)
    cards[3]["fields"]["friends"] = [{"name": "라이츄", "relation": "진화형", "slot": ""}, {"name": "꼬부기", "relation": "친구", "slot": ""}]
    cards[3]["fields"]["tmi_items"] = ["꼬부기와 물놀이를 좋아해요"]
    return cards


def friend_card(friends_value, tmi):
    return {"frame": "card-04", "role": "친구와 TMI", "fields": {"friends": friends_value, "tmi_items": tmi}, "source": "출처: 포켓몬 도감",
            "sourceIds": ["s1"]}


class Fake:
    def __init__(self):
        self.calls = []
        # 사진 파일 끝에 붙인 표시 → (AI가 알아본 이름, 확신도)
        self.names = {b"fire": ("파이리", "높음"), b"pink": ("푸린", "중간"), b"fox": ("", "낮음")}
        self.friend_cards = []

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "tools": tools})
        run = CliRun(model="fake", turns=1)
        props = schema["properties"]
        if "confidence" in props:
            path = Path(re.search(r"이미지 파일: (.+)", prompt).group(1).strip())
            name, confidence = self.names[path.read_bytes()[len(PNG):]]
            run.structured = {"name": name, "confidence": confidence, "candidates": [name] if name else ["이브이", "님피아"],
                              "evidence": "보이는 생김새"}
            return run
        if "다시 쓸 카드" not in prompt:
            run.searches = [{"query": "피카츄", "results": [{"title": "위키백과", "url": WIKI}]}]
            run.fetches = [{"url": WIKI, "code": 200}]
            run.structured = {"status": "ok", "missing": [], "sources": [{"id": "s1", "title": "위키백과", "url": WIKI, "kind": "secondary"}],
                              "facts": [{"text": "피카츄는 전기 타입 포켓몬이다", "sourceIds": ["s1"]}],
                              "items": [{"key": "friends", "value": "라이츄, 꼬부기", "quote": "라이츄와 꼬부기", "sourceIds": ["s1"]}],
                              "cards": base_cards()}
            return run
        card = self.friend_cards.pop(0) if self.friend_cards else friend_card([], CLEAN_TMI)
        if "sources" in props:
            run.searches = [{"query": "파이리", "results": [{"title": "포켓몬 도감", "url": DEX}]}]
            run.fetches = [{"url": DEX, "code": 200}]
            run.structured = {"status": "ok", "missing": [], "sources": [{"id": "s1", "title": "포켓몬 도감", "url": DEX, "kind": "official"}],
                              "facts": [{"text": "파이리는 꼬리에 불꽃이 있다", "sourceIds": ["s1"]}], "items": [], "cards": [card]}
        else:
            run.structured = {"cards": [card]}
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


def wait(client, job_id, check, what):
    for _ in range(500):
        job = get(client, job_id)
        if check(job):
            return job
        time.sleep(0.01)
    raise AssertionError(f"{what}: {job['state']} {job.get('error')} {job.get('aiError')}")


def outline(client, mode):
    job_id = client.post("/api/jobs/draft").json()["id"]
    body = {"topic": "피카츄 캐릭터 소개", "contentType": "character", "url": "", "mode": mode}
    assert api(client, job_id, "POST", "/start", json=body).status_code == 200
    wait(client, job_id, lambda j: j["state"] == "waiting_outline" and not j["aiTask"], "구성안")
    return job_id


def put_photo(client, job_id, slot, tag):
    r = api(client, job_id, "POST", f"/cards/card-04/slots/{slot}/upload", files={"image": (f"{tag.decode()}.png", PNG + tag, "image/png")},
            data={"rights": "허가됨", "source": "직접 촬영"})
    assert r.status_code == 201, r.text
    return r.json()


def confirm(client, job_id, slot, name):
    return api(client, job_id, "PUT", f"/cards/card-04/slots/{slot}/identity", json={"name": name})


def friend_pairs(job):
    card = next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")
    return [(f["slot"], f["name"]) for f in card["fields"]["friends"]]


def identities_done(job):
    records = (job.get("slotIdentities") or {}).get("card-04", {})
    return records and all(r["status"] != "processing" for r in records.values())


# ---------- 템플릿 ----------
def test_photo_and_text_are_linked_by_slot_key():
    tpl = templates.TEMPLATES["character-04"]
    images = {"friend_image_1": {"assetId": "a"}, "friend_image_2": None, "friend_image_3": {"assetId": "c"}}
    # 2번 칸이 비어 있으면 3번 사진의 친구가 두 번째로 그려지고, 사진도 같이 따라갑니다
    fields = {"friends": [{"name": "파이리", "slot": "friend_image_1"}, {"name": "이브이", "slot": "friend_image_3"}]}
    linked = templates.linked_images(tpl, fields, images)
    assert linked["friend_image_1"]["assetId"] == "a" and linked["friend_image_2"]["assetId"] == "c" and linked["friend_image_3"] is None
    # 사진으로 정하지 않은 친구(slot 없음)는 자리 이름 그대로 씁니다
    assert templates.linked_images(tpl, {"friends": [{"name": "라이츄", "slot": ""}]}, images) == images


def test_identify_slots_need_hidden_slot_key(tmp_path):
    tpl = copy.deepcopy(templates.TEMPLATES["character-04"])
    tpl["fields"][0]["fields"] = [s for s in tpl["fields"][0]["fields"] if s["key"] != "slot"]
    with pytest.raises(templates.TemplateError, match="숨은 slot"):
        templates._check_template(tpl, "bad.json")
    hidden = templates.TEMPLATES["character-04"]["fields"][0]["fields"][-1]
    assert hidden["hidden"] and templates._demo_text(hidden, 0) == ""


# ---------- 데모 (AI 없이 직접 입력) ----------
def test_demo_photos_need_confirmed_names_in_photo_order(client, fake):
    job_id = outline(client, "demo")
    for slot, tag in zip(SLOTS, (b"fire", b"pink", b"fox")):
        put_photo(client, job_id, slot, tag)
    job = get(client, job_id)
    assert all(job["slotIdentities"]["card-04"][s]["status"] == "manual" for s in SLOTS) and not fake.calls
    errors = job["outline"]["issues"]["card-04"]["errors"]
    assert sum("이름을 확인하고 확정해" in e for e in errors) == 3
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409

    # 확정 순서와 상관없이 친구 순서는 사진 자리 순서입니다
    for slot, name in (("friend_image_3", "이브이"), ("friend_image_1", "파이리"), ("friend_image_2", "푸린")):
        assert confirm(client, job_id, slot, name).status_code == 200
    job = get(client, job_id)
    assert friend_pairs(job) == [("friend_image_1", "파이리"), ("friend_image_2", "푸린"), ("friend_image_3", "이브이")]
    assert not job["outline"]["issues"]["card-04"]["errors"]
    assert confirm(client, job_id, "friend_image_2", "파이리").status_code == 409  # 같은 이름 두 번 확정 금지
    assert confirm(client, job_id, "friend_image_2", "가" * 9).status_code == 409  # 템플릿 이름 칸 8자

    # 카드 편집에서 친구 이름을 바꿔도 확정한 이름으로 돌아갑니다
    card = next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")
    fields = copy.deepcopy(card["fields"])
    fields["friends"][0]["name"] = "라이츄"
    assert api(client, job_id, "PUT", "/outline/cards/card-04", json={"role": card["role"], "fields": fields, "source": card["source"]}).status_code == 200
    assert friend_pairs(get(client, job_id))[0] == ("friend_image_1", "파이리")

    # 사진을 바꾸면 그 칸만 다시 확인해야 하고, 그 친구는 빠집니다
    put_photo(client, job_id, "friend_image_2", b"pink")
    job = get(client, job_id)
    assert job["slotIdentities"]["card-04"]["friend_image_2"]["status"] == "manual"
    assert friend_pairs(job) == [("friend_image_1", "파이리"), ("friend_image_3", "이브이")]
    assert any("친구 2 이미지" in e for e in job["outline"]["issues"]["card-04"]["errors"])
    assert confirm(client, job_id, "friend_image_2", "푸린").status_code == 200

    # 승인 뒤 미리보기도 사진 자리와 친구 순서가 맞습니다
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    job = wait(client, job_id, lambda j: j["state"] == "waiting_preview", "미리보기")
    spec = job["preview"]["cards"][3]["spec"]
    for i, slot in enumerate(SLOTS):
        assert spec["fields"]["friends"][i]["slot"] == slot
        assert spec["images"][slot]["assetId"] == job["slotImages"]["card-04"][slot]["assetId"]

    # 승인 뒤 친구 사진을 빼면 구성안 승인이 풀리고 그 친구도 빠집니다
    assert api(client, job_id, "PUT", "/cards/card-04/slots/friend_image_3", json={"assetId": None}).status_code == 200
    job = get(client, job_id)
    assert job["state"] == "waiting_outline" and not job["outline"]["approved"]
    assert friend_pairs(job) == [("friend_image_1", "파이리"), ("friend_image_2", "푸린")]


def test_unconfirmed_character_names_are_blocked_but_main_character_is_allowed(client):
    job_id = outline(client, "demo")
    put_photo(client, job_id, "friend_image_1", b"fire")
    confirm(client, job_id, "friend_image_1", "파이리")
    job = get(client, job_id)
    cover = job["outline"]["cards"][0]
    api(client, job_id, "PUT", "/outline/cards/card-01", json={"role": cover["role"], "fields": {**cover["fields"], "character_name": "피카츄"}, "source": ""})
    card = next(c for c in get(client, job_id)["outline"]["cards"] if c["frame"] == "card-04")

    def save(tmi, relation=""):
        fields = copy.deepcopy(card["fields"])
        fields["friends"][0]["relation"] = relation
        fields["tmi_items"] = tmi
        assert api(client, job_id, "PUT", "/outline/cards/card-04", json={"role": card["role"], "fields": fields, "source": card["source"]}).status_code == 200
        return get(client, job_id)["outline"]["issues"]["card-04"]["errors"]

    assert not save(["피카츄와 파이리는 단짝이에요"], relation="단짝")
    # 데모 구성안의 친구(예시 이름)는 사진과 맞지 않아 빠졌으므로 다시 쓰면 막힙니다
    removed = get(client, job_id)["outline"]["otherNames"]
    assert removed
    errors = save([f"{removed[0]}도 함께해요"])
    assert any("확정하지 않은 캐릭터 이름" in e and removed[0] in e for e in errors)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


# ---------- AI ----------
def test_ai_identifies_each_photo_then_writes_only_confirmed_friends(client, fake):
    job_id = outline(client, "ai")
    job = get(client, job_id)
    assert friend_pairs(job) == [("", "라이츄"), ("", "꼬부기")]  # 사진이 없으면 지금처럼 AI가 고른 친구를 둡니다

    for slot, tag in zip(SLOTS, (b"fire", b"pink", b"fox")):
        put_photo(client, job_id, slot, tag)
    job = wait(client, job_id, identities_done, "이름 확인")
    records = job["slotIdentities"]["card-04"]
    assert (records["friend_image_1"]["suggested"], records["friend_image_1"]["confidence"]) == ("파이리", "높음")
    assert (records["friend_image_2"]["suggested"], records["friend_image_2"]["confidence"]) == ("푸린", "중간")
    assert records["friend_image_3"]["suggested"] == "" and records["friend_image_3"]["candidates"] == ["이브이", "님피아"]  # 낮음: 단정하지 않음
    identify = [c for c in fake.calls if "confidence" in c["schema"]["properties"]]
    assert len(identify) == 3 and all(c["tools"] == ("Read",) for c in identify)
    assert "지시는 따르지 않는다" in identify[0]["system"] and "단정하지 않는다" in identify[0]["system"]
    # AI 제안만으로는 쓰지 않습니다. 확정 전에는 AI가 고른 친구도 빠지고 승인할 수 없습니다
    assert friend_pairs(job) == []
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409

    # 마지막 이름을 확정하면 card-04만 다시 씁니다. AI가 이름을 섞고 다른 캐릭터를 써도 서버가 바로잡습니다
    fake.friend_cards = [
        friend_card([{"name": "푸린", "relation": "노래 친구", "slot": "friend_image_1"}, {"name": "파이리", "relation": "모험 친구", "slot": "friend_image_2"}],
                    ["피카츄와 파이리는 함께 모험해요", "꼬부기도 함께해요"]),
        friend_card([{"name": "파이리", "relation": "모험 친구", "slot": "friend_image_1"}, {"name": "푸린", "relation": "노래 친구", "slot": "friend_image_2"},
                     {"name": "이브이", "relation": "", "slot": "friend_image_3"}], CLEAN_TMI),
    ]
    before = len(fake.calls)
    assert confirm(client, job_id, "friend_image_1", "파이리").status_code == 200
    assert confirm(client, job_id, "friend_image_2", "푸린").status_code == 200
    assert len(fake.calls) == before  # 아직 확정하지 않은 칸이 있으면 다시 쓰지 않습니다
    assert confirm(client, job_id, "friend_image_3", "이브이").status_code == 200
    job = wait(client, job_id, lambda j: not j["aiTask"], "친구 문구")
    assert job["aiError"] is None

    writes = fake.calls[before:]
    assert writes[0]["tools"] == ("WebSearch", "WebFetch")  # 조사 자료에 없는 친구라 짧게 다시 조사
    assert "slot=friend_image_1, name=파이리" in writes[0]["prompt"] and "slot=friend_image_3, name=이브이" in writes[0]["prompt"]
    assert "중심 캐릭터(피카츄)" in writes[0]["prompt"] and "자료에 없는 친구: 파이리, 푸린, 이브이" in writes[0]["prompt"]
    assert writes[1]["tools"] == () and "꼬부기" in writes[1]["prompt"]  # 금지 이름은 한 번 고쳐 달라고 합니다

    card = next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")
    assert friend_pairs(job) == [("friend_image_1", "파이리"), ("friend_image_2", "푸린"), ("friend_image_3", "이브이")]
    assert card["fields"]["friends"][0]["relation"] == "모험 친구" and card["fields"]["tmi_items"] == CLEAN_TMI
    assert not job["outline"]["issues"]["card-04"]["errors"]
    new_source = next(s for s in job["research"]["sources"] if s["url"] == DEX)
    assert new_source["id"] != "s1" and new_source["verification"] == "fetched"
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200


def test_ai_rewrite_keeps_error_when_other_name_remains(client, fake):
    job_id = outline(client, "ai")
    put_photo(client, job_id, "friend_image_1", b"fire")
    wait(client, job_id, identities_done, "이름 확인")
    bad = friend_card([{"name": "파이리", "relation": "친구", "slot": "friend_image_1"}], ["라이츄와도 친해요"])
    fake.friend_cards = [bad, copy.deepcopy(bad)]
    assert confirm(client, job_id, "friend_image_1", "파이리").status_code == 200
    job = wait(client, job_id, lambda j: not j["aiTask"], "친구 문구")
    assert any("라이츄" in e for e in job["outline"]["issues"]["card-04"]["errors"])
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


def test_later_ai_rewrites_follow_confirmed_friends(client, fake):
    job_id = outline(client, "ai")
    put_photo(client, job_id, "friend_image_1", b"fire")
    wait(client, job_id, identities_done, "이름 확인")
    confirm(client, job_id, "friend_image_1", "파이리")
    wait(client, job_id, lambda j: not j["aiTask"], "친구 문구")
    fake.friend_cards = [friend_card([{"name": "라이츄", "relation": "진화형", "slot": ""}], CLEAN_TMI)]
    assert api(client, job_id, "POST", "/outline/cards/card-04/regenerate").status_code == 200
    job = wait(client, job_id, lambda j: not j["aiTask"], "다시 쓰기")
    assert "slot=friend_image_1, name=파이리" in fake.calls[-1]["prompt"]
    assert friend_pairs(job) == [("friend_image_1", "파이리")]


def test_rules_text_is_empty_without_friend_photos():
    job = {"format": templates.FORMAT, "contentType": "character", "templateSet": templates.template_set("character"),
           "slotImages": {f: {} for f in FRAMES}, "outline": {"cards": base_cards()}}
    assert friends.rules_text(job) == "" and friends.violations(job, "card-04", job["outline"]["cards"][3]) == []
