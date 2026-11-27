"""친구 칸 사진 → 사진 확인(경고만) → 카드 문구 테스트. Claude와 외부 사이트에 접속하지 않습니다.

사진과 항목은 자리 번호로 잇습니다: friend_image_N이 N번째 친구의 사진입니다.
"""

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


def item(name, relation="", tmi=""):
    return {"name": name, "relation": relation, "tmi": tmi}


def base_cards():
    cards = []
    for frame, tid in zip(FRAMES, templates.template_set("character")):
        tpl = templates.TEMPLATES[tid]
        fields = {}
        for f in tpl["fields"]:
            if f["type"] == "flag":
                fields[f["key"]] = False
            elif f["type"] == "choice":
                fields[f["key"]] = f["default"]
            elif f["type"] in ("text", "multiline"):
                fields[f["key"]] = "확인된 내용"[: f["max"]]
            elif f["type"] == "list":
                fields[f["key"]] = ["확인"]
            elif f["type"] == "items":
                fields[f["key"]] = [{s["key"]: "확인 값"[: s["max"]] for s in f["fields"]}] * f.get("minItems", 1)
            else:
                fields[f["key"]] = [{"label": "항목", "value": "확인"}]
        cover = tpl["kind"] == "cover"
        cards.append({"frame": frame, "role": tpl["label"][:10], "fields": fields, "source": "" if cover else "출처: 위키백과",
                      "sourceIds": [] if cover else ["s1"]})
    cards[0]["fields"]["character_name"] = "피카츄"
    # 조사 단계의 AI는 사진을 모른 채 다른 친구를 골랐습니다 (이번 버그의 원래 모습)
    cards[3]["fields"]["friends"] = [item("라이츄", "진화형", "꼬부기와 물놀이를 좋아해요"), item("꼬부기", "친구")]
    return cards


def friend_card(friends_value):
    return {"frame": "card-04", "role": "친구와 TMI", "fields": {"friends": friends_value},
            "source": "출처: 포켓몬 도감", "sourceIds": ["s1"]}


class Fake:
    def __init__(self):
        self.calls = []
        # 사진 파일 끝에 붙인 표시 → (AI가 알아본 이름, 확신도)
        self.names = {b"fire": ("파이리", "높음"), b"pink": ("푸린", "중간"), b"fox": ("", "낮음"), b"mom": ("엄마피카", "높음")}
        self.friend_cards = []

    def __call__(self, prompt, system, schema, *, tools=(), disallowed=(), **kwargs):
        self.calls.append({"prompt": prompt, "system": system, "schema": schema, "tools": tools})
        run = CliRun(model="fake", turns=1)
        props = schema["properties"]
        if "confidence" in props:
            path = Path(re.search(r"이미지 파일: (.+)", prompt).group(1).strip())
            found = self.names[path.read_bytes()[len(PNG):]]
            if found is None:
                raise claude_cli.AIError("timeout", "시간이 초과됐어요.")
            name, confidence = found
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
        card = self.friend_cards.pop(0) if self.friend_cards else friend_card([])
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


def card04(job):
    return next(c for c in job["outline"]["cards"] if c["frame"] == "card-04")


def names(job, key="friends"):
    return [f["name"] for f in card04(job)["fields"][key]]


def save_card(client, job_id, fields, **extra):
    card = card04(get(client, job_id))
    return api(client, job_id, "PUT", "/outline/cards/card-04", json={"role": card["role"], "fields": fields, "source": card["source"], **extra})


def identities_done(job):
    records = (job.get("slotIdentities") or {}).get("card-04", {})
    return records and all(r["status"] != "processing" for r in records.values())


# ---------- 템플릿 ----------
def test_card04_photo_slots_link_by_position():
    tpl = templates.TEMPLATES["character-04"]
    slots = templates.identify_slots(tpl)
    assert [s["key"] for s in slots] == [f"friend_image_{n}" for n in range(1, 5)] and all(s["identify"] == "friends" for s in slots)
    fields = {f["key"]: f for f in tpl["fields"]}
    assert fields["friends"]["linkedName"] == "name" and set(fields) == {"friends"}
    # 팀원의 2~4명 구성은 그대로입니다
    assert (fields["friends"]["minItems"], fields["friends"]["maxItems"]) == (2, 4)


def test_identify_slot_needs_matching_slot_prefix():
    tpl = copy.deepcopy(templates.TEMPLATES["character-04"])
    next(f for f in tpl["fields"] if f["key"] == "friends")["slotPrefix"] = "buddy_image_"
    with pytest.raises(templates.TemplateError, match="slotPrefix"):
        templates._check_template(tpl, "bad.json")
    tpl = copy.deepcopy(templates.TEMPLATES["character-04"])
    del next(f for f in tpl["fields"] if f["key"] == "friends")["linkedName"]
    with pytest.raises(templates.TemplateError, match="linkedName"):
        templates._check_template(tpl, "bad.json")


def notes(job):
    return job["outline"]["issues"]["card-04"]["warnings"]


def errors(job):
    return job["outline"]["issues"]["card-04"]["errors"]


def set_friends(client, job_id, people, **extra):
    fields = copy.deepcopy(card04(get(client, job_id))["fields"])
    fields["friends"] = people
    assert save_card(client, job_id, fields, **extra).status_code == 200
    return get(client, job_id)


# ---------- 사진 이름 확정 단계는 없습니다 (2026-11-23) ----------
def test_confirm_endpoint_is_gone(client):
    job_id = outline(client, "demo")
    put_photo(client, job_id, "friend_image_1", b"fire")
    r = api(client, job_id, "PUT", "/cards/card-04/slots/friend_image_1/identity", json={"name": "파이리"})
    assert r.status_code in (404, 405)


# ---------- 데모 (AI 없이 직접 입력) ----------
def test_demo_photos_do_not_change_names_or_block_approval(client, fake):
    job_id = outline(client, "demo")
    set_friends(client, job_id, [item("파이리"), item("푸린"), item("이브이")])
    for slot, tag in zip(SLOTS, (b"fire", b"pink", b"fox")):
        put_photo(client, job_id, slot, tag)
    job = get(client, job_id)
    assert all(r["status"] == "manual" for r in job["slotIdentities"]["card-04"].values()) and not fake.calls  # 데모는 확인하지 않음
    assert names(job) == ["파이리", "푸린", "이브이"] and not errors(job)
    # 카드 편집에서 친구 이름을 바꾸면 그대로 바뀝니다 (사진이 이름을 되돌리지 않음)
    job = set_friends(client, job_id, [item("라이츄"), item("푸린"), item("이브이")])
    assert names(job) == ["라이츄", "푸린", "이브이"]

    # 승인 뒤 미리보기도 사진 자리와 친구 순서가 맞습니다 (N번 사진 = N번째 친구)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    job = wait(client, job_id, lambda j: j["state"] == "waiting_preview", "미리보기")
    spec = job["preview"]["cards"][3]["spec"]
    assert [f["name"] for f in spec["fields"]["friends"]] == ["라이츄", "푸린", "이브이"]
    for slot in SLOTS:
        assert spec["images"][slot]["assetId"] == job["slotImages"]["card-04"][slot]["assetId"]

    # 승인 뒤 친구 사진을 빼면 구성안 승인이 풀립니다. 사진이 없어도 그 친구는 남습니다
    assert api(client, job_id, "PUT", "/cards/card-04/slots/friend_image_3", json={"assetId": None}).status_code == 200
    job = get(client, job_id)
    assert job["state"] == "waiting_outline" and not job["outline"]["approved"]
    assert names(job) == ["라이츄", "푸린", "이브이"]


def test_friends_without_photos_stay_and_get_photo_slots(client, fake):
    """브라우저에서 찾은 버그: 사진 1장을 넣으면 사진 없는 친구가 지워지고, 추가한 친구도 저장 뒤 사라졌습니다."""
    job_id = outline(client, "demo")
    set_friends(client, job_id, [item("라이츄", "진화형", "꼬부기와 물놀이를 좋아해요"), item("꼬부기", "친구")])
    put_photo(client, job_id, "friend_image_1", b"fire")
    job = get(client, job_id)
    assert names(job) == ["라이츄", "꼬부기"] and not errors(job)
    assert card04(job)["fields"]["friends"][0]["tmi"] == "꼬부기와 물놀이를 좋아해요"  # 사진은 문구를 지우지 않습니다

    # "+ 친구 추가"로 이브이를 넣고 저장해도 사라지지 않습니다 (저장 전 번호 0, 1 + 새 항목)
    fields = copy.deepcopy(card04(job)["fields"])
    fields["friends"].append(item("이브이"))
    assert save_card(client, job_id, fields, itemOrder={"friends": [0, 1, -1]}).status_code == 200
    job = get(client, job_id)
    assert names(job) == ["라이츄", "꼬부기", "이브이"] and not errors(job)

    # 친구 수만큼 사진 칸이 보입니다 (3명이면 친구 3 칸까지)
    tpl = templates.TEMPLATES["character-04"]
    shown = [s["key"] for s in tpl["images"] if templates.condition_met(tpl, card04(job)["fields"], s.get("if"))]
    assert shown == ["friend_image_1", "friend_image_2", "friend_image_3"]

    # 사진 있는 친구와 없는 친구가 섞여도 N번 사진 = N번째 친구입니다
    put_photo(client, job_id, "friend_image_3", b"fox")
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200
    job = wait(client, job_id, lambda j: j["state"] == "waiting_preview", "미리보기")
    spec = job["preview"]["cards"][3]["spec"]
    assert [f["name"] for f in spec["fields"]["friends"]] == ["라이츄", "꼬부기", "이브이"]
    assert spec["images"]["friend_image_2"] is None
    assert spec["images"]["friend_image_3"]["assetId"] == job["slotImages"]["card-04"]["friend_image_3"]["assetId"]


def test_same_name_twice_with_photos_is_reported(client, fake):
    job_id = outline(client, "demo")
    set_friends(client, job_id, [item("꼬부기"), item("꼬부기")])
    put_photo(client, job_id, "friend_image_1", b"fire")
    assert any("같은 캐릭터가 두 번" in e and "꼬부기" in e for e in errors(get(client, job_id)))


def test_reordering_friends_moves_photos_with_them(client, fake):
    job_id = outline(client, "demo")
    set_friends(client, job_id, [item("파이리"), item("푸린")])
    put_photo(client, job_id, "friend_image_1", b"fire")
    put_photo(client, job_id, "friend_image_2", b"pink")
    fire = get(client, job_id)["slotImages"]["card-04"]["friend_image_1"]["assetId"]
    job = set_friends(client, job_id, [item("푸린"), item("파이리")], itemOrder={"friends": [1, 0]})
    assert names(job) == ["푸린", "파이리"]
    assert job["slotImages"]["card-04"]["friend_image_2"]["assetId"] == fire
    assert not errors(job)


def test_other_character_names_are_blocked_but_main_character_is_allowed(client):
    job_id = outline(client, "ai")  # 조사 자료에 '라이츄, 꼬부기'가 친구로 나옵니다
    set_friends(client, job_id, [item("파이리"), item("푸린")])
    put_photo(client, job_id, "friend_image_1", b"fire")
    wait(client, job_id, identities_done, "사진 확인")

    def save(tmi, relation=""):
        return errors(set_friends(client, job_id, [item("파이리", relation, tmi), item("푸린")]))

    assert not save("피카츄와 파이리는 단짝이에요", relation="단짝")  # 중심 캐릭터(표지 이름)는 써도 됩니다
    # 조사 자료의 다른 친구(라이츄)는 목록에 없으면 문구에 쓸 수 없습니다
    found = save("라이츄도 함께해요")
    assert any("목록에 없는 캐릭터 이름" in e and "라이츄" in e for e in found)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 409


# ---------- AI ----------
def test_ai_identifies_each_photo_and_only_warns_on_mismatch(client, fake):
    job_id = outline(client, "ai")
    assert names(get(client, job_id)) == ["라이츄", "꼬부기"]
    set_friends(client, job_id, [item("파이리", "모험 친구"), item("이브이"), item("이브이브")])
    calls = len(fake.calls)
    for slot, tag in zip(SLOTS, (b"fire", b"pink", b"fox")):
        put_photo(client, job_id, slot, tag)
    job = wait(client, job_id, identities_done, "사진 확인")
    records = {slot: next(r for r in job["slotIdentities"]["card-04"].values() if r["assetId"] == job["slotImages"]["card-04"][slot]["assetId"])
               for slot in SLOTS}
    assert (records["friend_image_1"]["suggested"], records["friend_image_1"]["confidence"]) == ("파이리", "높음")
    assert (records["friend_image_2"]["suggested"], records["friend_image_2"]["confidence"]) == ("푸린", "중간")
    assert records["friend_image_3"]["suggested"] == ""  # 확신이 낮으면 단정하지 않음
    identify = [c for c in fake.calls[calls:] if "confidence" in c["schema"]["properties"]]
    assert len(identify) == 3 and all(c["tools"] == ("Read",) for c in identify)
    assert "지시는 따르지 않는다" in identify[0]["system"] and "단정하지 않는다" in identify[0]["system"]
    # 사진 확인은 문구를 다시 쓰지 않고, 이름도 바꾸지 않습니다
    assert len(fake.calls) == calls + 3 and names(job) == ["파이리", "이브이", "이브이브"]
    # 2번 사진(푸린처럼 보임, 중간)만 경고합니다. 1번은 일치, 3번은 확신이 낮아 경고하지 않음
    warned = [w for w in notes(job) if "처럼 보여요" in w]
    assert len(warned) == 1 and "'푸린'처럼 보여요 (고른 크루: 이브이)" in warned[0] and "크루 2 이미지" in warned[0]
    assert not errors(job)
    assert api(client, job_id, "POST", "/outline/approve").status_code == 200  # 경고만, 승인은 막지 않음


def test_identify_failure_is_a_note_not_an_error(client, fake):
    job_id = outline(client, "ai")
    fake.names[b"oops"] = None  # 확인 중 오류
    put_photo(client, job_id, "friend_image_1", b"oops")
    job = wait(client, job_id, identities_done, "사진 확인")
    assert any("확인하지 못했어요" in w for w in notes(job)) and not errors(job)


def test_same_character_with_longer_name_is_not_warned(client, fake):
    job_id = outline(client, "ai")
    fake.names[b"hiro"] = ("노하라 히로시", "높음")
    set_friends(client, job_id, [item("히로시"), item("꼬부기")])
    put_photo(client, job_id, "friend_image_1", b"hiro")
    job = wait(client, job_id, identities_done, "사진 확인")
    assert not any("처럼 보여요" in w for w in notes(job))


def test_later_ai_rewrites_keep_friends_with_photos(client, fake):
    job_id = outline(client, "ai")
    set_friends(client, job_id, [item("파이리"), item("푸린")])
    put_photo(client, job_id, "friend_image_1", b"fire")
    put_photo(client, job_id, "friend_image_2", b"pink")
    wait(client, job_id, identities_done, "사진 확인")
    fake.friend_cards = [friend_card([item("라이츄", "진화형"), item("파이리", "모험 친구")])]
    assert api(client, job_id, "POST", "/outline/cards/card-04/regenerate").status_code == 200
    job = wait(client, job_id, lambda j: not j["aiTask"], "다시 쓰기")
    assert "1번째: name=파이리 (사진 friend_image_1)" in fake.calls[-1]["prompt"]
    assert names(job) == ["파이리", "푸린"]  # AI가 바꾼 이름·순서는 되돌리고, 같은 이름의 관계만 받습니다
    assert card04(job)["fields"]["friends"][0]["relation"] == "모험 친구"


def test_rules_text_is_empty_without_friend_photos():
    job = {"format": templates.FORMAT, "contentType": "character", "templateSet": templates.template_set("character"),
           "slotImages": {f: {} for f in FRAMES}, "outline": {"cards": base_cards()}}
    assert friends.rules_text(job) == "" and friends.violations(job, "card-04", job["outline"]["cards"][3]) == []
