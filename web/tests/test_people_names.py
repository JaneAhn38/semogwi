"""친구 이름 나누기와 한국 이름 통일 (2026-11-24 짱구 재현).

짱구 조사에서 친구 항목이 '훈이(마사오, 유치원 친구), 맹구(보오), 유리(네네), 철수(토오루)'로 나왔는데,
괄호 안 쉼표에서 잘려 '훈이(마사오' / '유치원 친구)'가 이름이 되고, 4명 자르기에 철수가 빠지고,
일본판 이름(보오·네네)이 관계 칸에 들어가 크루 후보가 2명만 나왔습니다.
"""

from app import ai_rules, research
from app.ai_provider import AIProvider
from app.claude_cli import CliRun

SHIN = "훈이(마사오, 유치원 친구), 맹구(보오), 유리(네네), 철수(토오루)"


def item(value, key="friends", ids=("s3",), state="secondary"):
    return {"key": key, "value": value, "quote": "", "sourceIds": list(ids), "state": state}


def test_commas_inside_parentheses_are_not_split():
    people = research._split_people(SHIN)
    assert [p["name"] for p in people] == ["훈이", "맹구", "유리", "철수"]  # 깨진 이름 없이 철수까지 4명
    assert people[0] == {"name": "훈이", "relation": "유치원 친구", "aliases": ["마사오"]}
    # 괄호 속 원어 이름은 관계가 아니라 다른 이름입니다 (관계 칸에 '보오'가 나오지 않게)
    assert people[1] == {"name": "맹구", "relation": "", "aliases": ["보오"]}
    assert people[3]["aliases"] == ["토오루"]
    assert all("(" not in p["name"] and ")" not in p["name"] for p in people)


def test_split_keeps_old_formats():
    assert research._split_people("라이츄(진화형), 꼬부기(친구)") == [
        {"name": "라이츄", "relation": "진화형", "aliases": []}, {"name": "꼬부기", "relation": "친구", "aliases": []}]
    assert [p["name"] for p in research._split_people("철수 및 유리、맹구，훈이")] == ["철수", "유리", "맹구", "훈이"]
    assert [p["name"] for p in research._split_people("엄마, 짱아(동생)")] == ["짱아"]  # 관계만 적힌 '엄마'는 캐릭터가 아님
    assert research._split_people("훈이(마사오, 유치원 친구")[0] == {"name": "훈이", "relation": "유치원 친구", "aliases": ["마사오"]}  # 닫히지 않은 괄호
    assert research._split_people("유리（네네）")[0]["aliases"] == ["네네"]  # 전각 괄호


def test_people_of_counts_four_and_finds_tmi_by_alias():
    tmi = item("마사오: 액션가면을 자주 봐요 / 철수: 사실은 액션가면을 좋아해요", key="tmi")
    people = research.people_of([item(SHIN), tmi])["friends"]
    assert [p["name"] for p in people] == ["훈이", "맹구", "유리", "철수"]
    assert people[0]["tmi"] == "액션가면을 자주 봐요"  # 일본판 이름으로 적힌 TMI도 한국 이름에 붙습니다
    assert people[3]["tmi"] == "사실은 액션가면을 좋아해요"
    many = research.people_of([item(SHIN + ", 흰둥이(반려견), 수지(친구), 치타(친구)")])["friends"]
    assert len(many) == 4  # 조사는 지금처럼 최대 4명


def test_resolve_name_maps_aliases_to_korean_names():
    people = research._split_people(SHIN)
    assert research.resolve_name("마사오", people) == "훈이"
    assert research.resolve_name("보오", people) == "맹구"
    assert research.resolve_name("훈이", people) == "훈이"
    assert research.resolve_name("マサオ", people) == "マサオ"  # 모르는 이름은 그대로 (가타카나 자동 변환은 하지 않음)


def test_people_round_maps_japanese_answer_to_korean_name():
    # 캐릭터별 조사(AI)가 일본판 이름·괄호 붙은 이름으로 답해도 조사 목록의 한국 이름으로 받습니다
    research_data = {"sources": [], "items": [item(SHIN)], "facts": []}
    targets = [("friends", p) for p in research.people_of(research_data["items"])["friends"]]
    wanted = {p["name"]: ("friends", p) for _, p in targets}
    acc = {"accepted": [], "rejected": [], "seen": set(), "known": set(), "discovered": {}, "queries": [], "pages": [],
           "error": None, "group": "", "group_words": (), "room": {}}
    run = CliRun(model="fake", turns=1)
    run.fetches = [{"url": "https://ja.wikipedia.org/wiki/x", "code": 200}]
    run.structured = {"sources": [{"id": "p1", "title": "登場人物", "url": "https://ja.wikipedia.org/wiki/x", "kind": "secondary"}],
                      "people": [{"name": "마사오", "category": "friends", "relation": "", "tmi": "늘 울보지만 친구를 잘 챙겨요", "quote": "q", "sourceIds": ["p1"]},
                                 {"name": "철수(토오루)", "category": "friends", "relation": "", "tmi": "학원을 여러 곳 다녀요", "quote": "q", "sourceIds": ["p1"]}]}
    AIProvider._merge_people_round(research_data, run, acc, wanted, targets, allow_new=True)
    assert [p["name"] for p in acc["accepted"]] == ["훈이", "철수"]
    assert acc["accepted"][0]["relation"] == "유치원 친구"


def test_ai_rules_use_korean_names():
    rule = ai_rules.KOREAN_NAME_RULE
    assert "마사오" in rule and "훈이" in rule and "원래 이름을 그대로" in rule
    for prompt in (ai_rules.PEOPLE_SYSTEM, ai_rules.FRIEND_PICK_SYSTEM, ai_rules.PROFILE_SYSTEM, ai_rules.TEMPLATE_TYPE_RULES["character"]):
        assert rule in prompt
    friends_hint = next(s for s in research.SPECS["character"] if s["key"] == "friends")["hint"]
    assert "한국에서 쓰는 이름" in friends_hint and "최대 4명" in friends_hint
