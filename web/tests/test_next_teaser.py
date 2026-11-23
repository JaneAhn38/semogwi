"""캐릭터 소개 card-05: 다음 캐릭터 예고 / 독자 참여 카드 전환과 'AI로 쓰기' 버튼. Claude와 외부 사이트에 접속하지 않습니다."""

import json

from app import jobs, templates
from tests.test_templates import (api, approve_all, client, clear_cooldowns, edit, fake, get, start, upload,  # noqa: F401
                                  wait)

USE_TEMPLATES = True
TPL = "character-05"
NAMED = {"next_name": "하치와레", "next_hint": "노래를 좋아하는 고양이", "next_date": "다음 주에 만나요", "next_episode": "7",
         "teaser": "세모귀의 단짝이 찾아와요"}
HINT_DEFAULT, REVEAL_DEFAULT = "어떤 친구일지 기대해 주세요", "다음 게시물에서 만나요!"


def ai_job(client):
    job_id = start(client, mode="ai")
    wait(client, job_id, "waiting_outline")
    return job_id


def card5(job):
    return job["outline"]["cards"][4]


# ---------- 템플릿: 두 가지 마무리 카드 ----------
def test_template_switches_between_teaser_and_open_call():
    tpl = templates.TEMPLATES[TPL]
    named = [e for e in tpl["elements"] if e.get("if") == "next_name"]
    open_call = [e for e in tpl["elements"] if e.get("if") == "!next_name"]
    assert {e.get("text") for e in open_call} >= {"다음엔 어떤 친구를 만나볼까요?", "보고 싶은 캐릭터를", "댓글로 알려주세요!", "같이 골라요"}
    assert {e.get("field") for e in named} >= {"next_name", "next_hint", "next_date", "next_episode", "teaser"}
    assert not any(e.get("field") for e in open_call)  # 참여 카드는 다음 편 칸을 그리지 않음 (회차도 숨김)
    # 예전 자리표시 문구는 어디에도 없음
    words = json.dumps(tpl["elements"], ensure_ascii=False)
    assert "???" not in words and "비밀" not in words and "곧 공개 예정" not in words
    # 디자인 요소(상자·원·마스코트·팔로우 문구)는 두 카드에 공통
    common = [e for e in tpl["elements"] if not e.get("if")]
    assert {e["type"] for e in common} >= {"header", "rect", "line", "circle", "asset", "footer"}
    assert "팔로우하면 다음 친구를 제일 먼저 만나요!" in {e.get("text") for e in common}
    assert templates.condition_met(tpl, {"next_name": ""}, "!next_name") and not templates.condition_met(tpl, {"next_name": "라이츄"}, "!next_name")
    # 다음 캐릭터 이미지: 이름이 있을 때만, 사용자만 넣는 자리
    slot = tpl["images"][0]
    assert slot == {"key": "next_image", "label": "다음 캐릭터 이미지", "required": False, "if": "next_name", "userOnly": True}
    assert templates.next_teaser(tpl) == {"name": "next_name", "hint": "next_hint", "reveal": "next_date",
                                          "hintDefault": HINT_DEFAULT, "revealDefault": REVEAL_DEFAULT}
    # 다른 템플릿은 이 기능을 쓰지 않음
    assert [t for t, v in templates.TEMPLATES.items() if v.get("nextTeaser")] == [TPL]
    assert not any("!" in json.dumps(e.get("if", "")) for t, v in templates.TEMPLATES.items() if t != TPL for e in v["elements"])


def test_negated_condition_rules():
    fields = {f["key"]: f for f in templates.TEMPLATES[TPL]["fields"]}
    assert templates._condition_ok("!next_name", fields)
    assert not templates._condition_ok("!nope", fields) and not templates._condition_ok("!next_name=x", fields)


# ---------- 이미지: 이번 캐릭터 사진이 자동으로 들어가지 않음 ----------
def test_current_character_images_are_not_suggested_for_next_character(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    assert edit(client, job_id, "card-05", NAMED, role="마무리", source="").status_code == 200
    for _ in range(12):
        upload(client, job_id)
    job = get(client, job_id)
    assert "card-05" not in job["slotSuggestions"]
    job = api(client, job_id, "POST", "/slot-suggestions/apply", json={}).json()
    assert not (job["slotImages"].get("card-05") or {}).get("next_image")
    # 사용자가 직접 넣고 바꿀 수 있음
    asset = job["assets"][0]["id"]
    r = api(client, job_id, "PUT", "/cards/card-05/slots/next_image", json={"assetId": asset, "variant": "original"})
    assert r.status_code == 200 and r.json()["slotImages"]["card-05"]["next_image"]["assetId"] == asset


# ---------- 다시 쓰기: 사용자 입력 보존 ----------
def test_rewriting_card_keeps_user_values_and_image(client, fake):
    job_id = ai_job(client)
    asset = upload(client, job_id)
    assert edit(client, job_id, "card-05", NAMED, role="마무리", source="").status_code == 200
    api(client, job_id, "PUT", "/cards/card-05/slots/next_image", json={"assetId": asset, "variant": "original"})
    teaser_calls = len([c for c in fake.calls if "reveal" in c["schema"]["properties"]])
    for path in ("/outline/cards/card-05/regenerate", "/outline/regenerate"):
        assert api(client, job_id, "POST", path).status_code == 200
        job = wait(client, job_id, "waiting_outline")
        assert card5(job)["fields"] == NAMED
        assert job["slotImages"]["card-05"]["next_image"]["assetId"] == asset
    assert len([c for c in fake.calls if "reveal" in c["schema"]["properties"]]) == teaser_calls  # 다시 쓰기는 예고 문구 AI를 부르지 않음


def test_demo_regenerate_keeps_user_values(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    edit(client, job_id, "card-05", NAMED, role="마무리", source="")
    job = api(client, job_id, "POST", "/outline/cards/card-05/regenerate").json()
    assert card5(job)["fields"] == NAMED
    api(client, job_id, "POST", "/outline/regenerate")
    assert card5(wait(client, job_id, "waiting_outline"))["fields"] == NAMED


# ---------- 'AI로 쓰기' 버튼 ----------
def test_button_needs_a_saved_name_and_only_works_on_teaser_card(client, fake):
    job_id = ai_job(client)
    before = len(fake.calls)
    r = api(client, job_id, "POST", "/outline/cards/card-05/next-teaser")
    assert r.status_code == 409 and "이름" in r.json()["detail"]
    assert api(client, job_id, "POST", "/outline/cards/card-02/next-teaser").status_code == 409
    assert len(fake.calls) == before  # 이름 입력·저장만으로는 AI를 부르지 않음
    edit(client, job_id, "card-05", {"next_name": "라이츄"}, role="마무리", source="")
    assert len(fake.calls) == before


def test_button_calls_ai_once_without_search_and_updates_only_hint_and_reveal(client, fake):
    job_id = ai_job(client)
    edit(client, job_id, "card-05", {**NAMED, "next_hint": "", "next_date": ""}, role="마무리", source="")
    fake.teaser = {"hint": "노래를 좋아해요", "hintSourceIds": ["s1"], "reveal": "12월 1일 공개!"}  # 근거 자료에 이름이 없고, 날짜를 지어냄
    before = len(fake.calls)
    assert api(client, job_id, "POST", "/outline/cards/card-05/next-teaser").status_code == 200
    job = wait(client, job_id, "waiting_outline")
    assert len(fake.calls) == before + 1 and fake.calls[-1]["tools"] == ()
    assert "<next_name>하치와레</next_name>" in fake.calls[-1]["prompt"]
    fields = card5(job)["fields"]
    assert fields["next_hint"] == HINT_DEFAULT and fields["next_date"] == REVEAL_DEFAULT
    assert {k: fields[k] for k in ("next_name", "next_episode", "teaser")} == {k: NAMED[k] for k in ("next_name", "next_episode", "teaser")}
    assert card5(job)["edited"] and job["aiCalls"][-1]["kind"] == "teaser"


def test_demo_button_fills_default_texts_without_ai(client, fake):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    edit(client, job_id, "card-05", {"next_name": "라이츄"}, role="마무리", source="")
    before = len(fake.calls)
    fields = card5(api(client, job_id, "POST", "/outline/cards/card-05/next-teaser").json())["fields"]
    assert fields["next_hint"] == HINT_DEFAULT and fields["next_date"] == REVEAL_DEFAULT and len(fake.calls) == before


def teaser_job(**research):
    base = {"sources": [{"id": "s1", "kind": "official", "verification": "fetched"},
                        {"id": "n1", "kind": "secondary", "verification": "fetched", "auxiliary": {"site": "namu"}},
                        {"id": "u1", "kind": "user", "verification": "user_provided"}],
            "facts": [], "items": []}
    return {"research": {**base, **research}, "notes": "", "userMaterial": None}


CARD = {"template": TPL, "fields": {"next_name": "라이츄"}}


def test_hint_is_kept_only_with_official_or_user_evidence_naming_the_character():
    job = teaser_job(facts=[{"text": "피카츄는 천둥의 돌로 라이츄로 진화한다", "sourceIds": ["s1"]},
                            {"text": "라이츄는 꼬리가 길다", "sourceIds": ["n1"]}])
    ok = jobs.teaser_fields(job, CARD, {"hint": "피카츄가 진화한 모습", "hintSourceIds": ["s1"], "reveal": "다음 게시물에서 만나요!"})
    assert ok == {"next_hint": "피카츄가 진화한 모습", "next_date": REVEAL_DEFAULT}
    # 나무위키(보조 출처)만 근거 → 기본 문구
    assert jobs.teaser_fields(job, CARD, {"hint": "꼬리가 길어요", "hintSourceIds": ["n1"], "reveal": ""})["next_hint"] == HINT_DEFAULT
    # 근거 없음, 없는 출처, 너무 김 → 기본 문구
    for result in ({"hint": "전기를 모아요", "hintSourceIds": []}, {"hint": "전기를 모아요", "hintSourceIds": ["zz"]},
                   {"hint": "가" * 19, "hintSourceIds": ["s1"]}):
        assert jobs.teaser_fields(job, CARD, result)["next_hint"] == HINT_DEFAULT
    # 사용자가 붙여 넣은 자료에 이름이 있으면 사용
    user = {**teaser_job(), "notes": "라이츄: 피카츄보다 크고 볼이 노란색"}
    assert jobs.teaser_fields(user, CARD, {"hint": "볼이 노란 친구", "hintSourceIds": ["u1"]})["next_hint"] == "볼이 노란 친구"


def test_reveal_never_keeps_dates_or_times():
    job = teaser_job()
    for reveal in ("12월 1일 공개!", "내일 만나요!", "토요일에 만나요", "다음 주에 만나요", "[MM월 DD일]"):
        assert jobs.teaser_fields(job, CARD, {"hint": "", "reveal": reveal})["next_date"] == REVEAL_DEFAULT
    assert jobs.teaser_fields(job, CARD, {"hint": "", "reveal": "곧 다시 만나요!"})["next_date"] == "곧 다시 만나요!"


# ---------- 예전 작업 ----------
def test_saved_done_jobs_open_with_new_design(client):
    job_id = start(client)
    wait(client, job_id, "waiting_outline")
    edit(client, job_id, "card-05", {"next_name": "하치와레", "next_hint": "다음 캐릭터는 아직 비밀이에요"}, role="마무리", source="")
    approve_all(client, job_id)
    raw = json.loads(jobs._path(job_id).read_text(encoding="utf-8"))
    raw["slotImages"]["card-05"] = {}  # 이미지 자리가 생기기 전에 저장된 작업
    jobs._path(job_id).write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    job = get(client, job_id)
    assert job["state"] == "done" and card5(job)["template"] == TPL and card5(job)["fields"]["next_name"] == "하치와레"
    assert not job["outline"]["issues"]["card-05"]["errors"]
    assert job["preview"]["cards"][4]["spec"]["images"] == {"next_image": None}


def test_episode_shows_only_when_entered():
    tpl = templates.TEMPLATES[TPL]
    episode = next(e for e in tpl["elements"] if e.get("field") == "next_episode")
    assert "fallback" not in episode and episode["prefix"] == "No. " and episode["if"] == "next_name"
    field = next(f for f in tpl["fields"] if f["key"] == "next_episode")
    assert "placeholder" not in field  # 구성안 요약도 '비어 있음 · 카드에서 숨겨요'
    assert "다음 회차" not in json.dumps(tpl, ensure_ascii=False)
