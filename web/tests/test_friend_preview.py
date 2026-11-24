"""크루 고르기 미리보기 (2026-11-24). 실제 사이트에 접속하지 않고 가짜 응답(httpx.MockTransport)으로 검사합니다."""

import httpx
import pytest

from app import detail_images, friend_preview, site_policy

PREVIEW_NETWORK = True  # conftest: 이 파일은 friend_preview.find_image를 막지 않습니다

OWN = "https://pokemonkorea.co.kr/pokedex/7"
LIST = "https://pokemonkorea.co.kr/pokedex"
WIKI = "https://namu.wiki/w/꼬부기"
SOURCES = [
    {"id": "s1", "title": "꼬부기 | 포켓몬 도감", "url": OWN, "kind": "official", "verification": "fetched"},
    {"id": "s2", "title": "포켓몬 도감 목록", "url": LIST, "kind": "official", "verification": "fetched"},
    {"id": "s3", "title": "꼬부기 - 나무위키", "url": WIKI, "kind": "secondary", "verification": "fetched"},
    {"id": "s4", "title": "꼬부기", "url": "https://namu.moe/w/꼬부기", "kind": "secondary", "verification": "mirror"},
    {"id": "s5", "title": "꼬부기 굿즈", "url": "https://chiikawamarket.jp/products/꼬부기", "kind": "official", "verification": "restricted"},
    {"id": "s6", "title": "꼬부기", "url": "https://pokemonkorea.co.kr/guess/꼬부기", "kind": "official", "verification": "search_result"},
]
PAGE = """<html><head><title>꼬부기 | 포켓몬 도감</title>
<meta property="og:image" content="/img/logo.png"><meta property="og:image" content="/img/0007.png"></head>
<body><h1>꼬부기</h1><img src="/img/0001.png" alt="이상해씨"></body></html>"""


@pytest.fixture(autouse=True)
def public(monkeypatch, tmp_path):
    # 가짜 도메인의 DNS 조회를 하지 않습니다
    monkeypatch.setattr(detail_images, "_public_host", lambda url: True)
    monkeypatch.setattr(friend_preview, "_public_host", lambda url: True)
    monkeypatch.setattr(detail_images, "REQUEST_GAP", 0)
    site_policy.COOLDOWN_FILE.unlink(missing_ok=True)


def candidate(name="꼬부기", ids=("s1", "s2", "s3")):
    return {"name": name, "relation": "", "reason": "", "sourceIds": list(ids)}


def mock_client(routes: dict, log: list):
    def handler(request):
        url = str(request.url)
        log.append(url)
        for key, (code, body) in routes.items():
            if url.endswith(key):
                return httpx.Response(code, text=body, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="")
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_link_prefers_official_then_read_secondary():
    assert friend_preview.link_for(candidate(), SOURCES) == {"url": OWN, "site": "pokemonkorea.co.kr", "official": True}
    assert friend_preview.link_for(candidate(ids=("s4", "s3")), SOURCES) == {"url": WIKI, "site": "나무위키", "official": False}  # 미러 제외
    # 자동 접근 금지 사이트도 사람이 여는 링크로는 걸 수 있습니다 (이미지는 쓰지 않음)
    assert friend_preview.link_for(candidate(ids=("s5",)), SOURCES)["url"].startswith("https://chiikawamarket.jp")
    assert friend_preview.link_for(candidate(ids=("s4",)), SOURCES) is None
    assert friend_preview.link_for(candidate(ids=()), SOURCES) is None  # 직접 입력한 후보


def test_page_must_be_official_read_and_own():
    assert friend_preview.page_for(candidate(), SOURCES)["url"] == OWN
    assert friend_preview.page_for(candidate(ids=("s2",)), SOURCES) is None  # 목록 페이지 (제목·주소에 이름 없음)
    assert friend_preview.page_for(candidate(ids=("s3",)), SOURCES) is None  # 2차 자료의 이미지는 쓰지 않음
    assert friend_preview.page_for(candidate(ids=("s5",)), SOURCES) is None  # 금지 사이트
    assert friend_preview.page_for(candidate(ids=("s6",)), SOURCES) is None  # 읽지 않은 페이지
    profile = {"url": "https://pokemonkorea.co.kr/p/7", "title": "꼬부기", "kind": "official", "verification": "fetched"}
    assert friend_preview.page_for({**candidate(ids=()), "profileSource": profile}, SOURCES) == profile  # AI가 찾은 프로필 페이지


def test_image_from_page_skips_logo_and_restricted():
    assert friend_preview.image_in(PAGE, OWN, "꼬부기") == "https://pokemonkorea.co.kr/img/0007.png"
    alt_only = '<html><body><img src="/a.png" alt="이상해씨"><img src="/b.png" alt="꼬부기"></body></html>'
    assert friend_preview.image_in(alt_only, OWN, "꼬부기") == "https://pokemonkorea.co.kr/b.png"
    banned = '<meta property="og:image" content="https://chiikawamarket.jp/x.png">'
    assert friend_preview.image_in(banned, OWN, "꼬부기") is None
    assert friend_preview.image_in('<img src="/c.png" alt="이상해씨">', OWN, "꼬부기") is None


def test_attach_finds_preview_and_keeps_only_urls():
    log = []
    client = mock_client({"/robots.txt": (200, "User-agent: *\nAllow: /"), "/pokedex/7": (200, PAGE)}, log)
    found, failures = friend_preview.attach([candidate(), candidate("라이츄", ("s2",))], {"sources": SOURCES}, client=client)
    assert found[0]["preview"] == {"imageUrl": "https://pokemonkorea.co.kr/img/0007.png", "pageUrl": OWN, "site": "pokemonkorea.co.kr"}
    assert found[1]["preview"] is None and found[1]["link"]["url"] == LIST
    assert failures == [] and not any(u.endswith(".png") for u in log)  # 이미지 파일은 받지 않습니다
    # 이미 찾아본 후보는 다시 요청하지 않습니다
    log.clear()
    again, _ = friend_preview.attach(found, {"sources": SOURCES}, client=client)
    assert log == [] and again[0]["preview"] == found[0]["preview"]


def test_attach_respects_robots_and_blocks():
    log = []
    client = mock_client({"/robots.txt": (200, "User-agent: *\nDisallow: /pokedex/")}, log)
    found, _ = friend_preview.attach([candidate()], {"sources": SOURCES}, client=client)
    assert found[0]["preview"] is None and not any("/pokedex/7" in u for u in log)

    log = []
    client = mock_client({"/robots.txt": (200, ""), "/pokedex/7": (403, "")}, log)
    found, failures = friend_preview.attach([candidate()], {"sources": SOURCES}, client=client)
    assert found[0]["preview"] is None and failures[0]["blocked"] and failures[0]["code"] == 403


def test_page_without_the_name_is_not_used():
    log = []
    other = PAGE.replace("꼬부기", "이상해씨")
    client = mock_client({"/robots.txt": (200, ""), "/pokedex/7": (200, other)}, log)
    found, _ = friend_preview.attach([candidate()], {"sources": SOURCES}, client=client)
    assert found[0]["preview"] is None


def test_no_requests_without_lookup_or_pages():
    log = []
    client = mock_client({}, log)
    found, _ = friend_preview.attach([candidate()], {"sources": SOURCES}, look=False, client=client)  # 데모
    assert log == [] and found[0]["preview"] is None and found[0]["link"]["official"]
    found, _ = friend_preview.attach([candidate(ids=("s3",))], {"sources": SOURCES}, client=client)  # 사진을 찾을 페이지 없음
    assert log == [] and found[0]["preview"] is None


def test_add_profiles_only_for_candidates_without_own_page():
    asked = []

    def find(names):
        asked.append(names)
        return {"profiles": {"라이츄": {"url": "https://pokemonkorea.co.kr/p/26", "title": "라이츄", "kind": "official", "verification": "fetched"}},
                "calls": [{"kind": "profiles"}]}

    found, calls = friend_preview.add_profiles([candidate(), candidate("라이츄", ("s2",)), candidate("파이리", ("s2",))], {"sources": SOURCES}, find)
    assert asked == [["라이츄", "파이리"]] and calls == [{"kind": "profiles"}]
    assert "profileSource" not in found[0] and found[1]["profileSource"]["url"].endswith("/p/26") and found[2]["profileSource"] is None
    # 한 번 찾아본 후보는 다시 묻지 않고, 실패해도 후보는 그대로입니다
    assert friend_preview.add_profiles(found, {"sources": SOURCES}, find)[1] == [] and len(asked) == 1
    boom = lambda names: (_ for _ in ()).throw(RuntimeError("x"))
    assert friend_preview.add_profiles([candidate("라이츄", ("s2",))], {"sources": SOURCES}, boom) == ([candidate("라이츄", ("s2",))], [])
