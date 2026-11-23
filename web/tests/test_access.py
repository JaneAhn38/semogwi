"""외부 공유(Cloudflare Tunnel) 접속 제어."""

import os
import tempfile

os.environ.setdefault("SEMOGWI_DATA_DIR", tempfile.mkdtemp())
os.environ["SEMOGWI_DEMO_DELAY"] = "0"

import pytest
from fastapi.testclient import TestClient

from app import access, detail_images
from app.main import app

TUNNEL = "https://abc-def.trycloudflare.com"
CF = {"cf-ray": "1", "cf-connecting-ip": "203.0.113.5", "cf-visitor": '{"scheme":"https"}'}
CODE = "team-code-1234"


@pytest.fixture
def share(monkeypatch):
    settings = access.load_settings({"SEMOGWI_SHARE": "1", "SEMOGWI_ACCESS_CODE": CODE})
    monkeypatch.setattr(access, "SETTINGS", settings)
    return settings


def tunnel_client():
    return TestClient(app, base_url=TUNNEL, headers=CF, follow_redirects=False)


def login(c, code=CODE, next_path="/"):
    return c.post("/access", data={"code": code, "next": next_path}, headers={"Origin": TUNNEL})


def test_share_off_blocks_tunnel():
    assert not access.SETTINGS.enabled
    with tunnel_client() as c:
        r = c.get("/api/options")
        assert r.status_code == 403 and "로컬 주소로만" in r.json()["detail"]
        assert c.get("/access").status_code == 403


def test_local_unchanged_in_share_mode(share):
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        assert c.get("/api/options").status_code == 200
        assert c.post("/api/jobs/draft").status_code == 201


def test_tunnel_requires_code(share):
    with tunnel_client() as c:
        assert c.get("/api/options").status_code == 401
        assert c.post("/api/jobs/draft", headers={"Origin": TUNNEL}).status_code == 401
        page = c.get("/?job=1")
        assert page.status_code == 303 and page.headers["location"].startswith("/access?next=")
        form = c.get("/access")
        assert form.status_code == 200 and 'name="code"' in form.text and CODE not in form.text
        # no-referrer면 브라우저가 양식 POST의 Origin을 null로 보내 로그인이 막힙니다
        assert form.headers["referrer-policy"] == "same-origin"
        assert c.post("/access", data={"code": CODE}, headers={"Origin": "null"}).status_code == 403
        assert login(c, "wrong-code-0000").status_code == 401
        assert c.get("/api/options").status_code == 401


def test_tunnel_login_then_works(share):
    with tunnel_client() as c:
        r = login(c, next_path="/?job=abc")
        assert r.status_code == 303 and r.headers["location"] == "/?job=abc"
        cookie = r.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower() and CODE not in cookie
        c.cookies.set(access.COOKIE, r.cookies[access.COOKIE])  # Secure 쿠키를 테스트 클라이언트에 직접 넣습니다
        assert c.get("/api/options").status_code == 200
        assert c.post("/api/jobs/draft", headers={"Origin": TUNNEL}).status_code == 201
        assert c.get("/").status_code == 200
        assert c.get("/api/options").headers["cache-control"] == "private, no-store"
        # 다른 사이트에서 보낸 요청은 로그인해도 막습니다
        assert c.post("/api/jobs/draft", headers={"Origin": "https://evil.example"}).status_code == 403


def test_old_cookie_fails_after_code_change(share, monkeypatch):
    with tunnel_client() as c:
        token = login(c).cookies[access.COOKIE]
        monkeypatch.setattr(access, "SETTINGS", access.load_settings({"SEMOGWI_SHARE": "1", "SEMOGWI_ACCESS_CODE": "another-code-99"}))
        c.cookies.set(access.COOKIE, token)
        assert c.get("/api/options").status_code == 401


def test_other_hosts_still_blocked(share):
    for base in ("http://evil.example", "https://trycloudflare.com", "https://x.trycloudflare.com.evil.example"):
        with TestClient(app, base_url=base) as c:
            assert c.get("/api/options").status_code == 403, base


def test_tunnel_header_with_local_host_needs_code(share):
    with TestClient(app, base_url="http://127.0.0.1:8000", headers=CF) as c:
        assert c.get("/api/options").status_code == 401


def test_login_lockout(share):
    with tunnel_client() as c:
        for _ in range(access.MAX_FAILURES):
            login(c, "wrong-code-0000")
        assert login(c).status_code == 429


def test_safe_next_and_settings():
    assert access.safe_next("//evil.example") == "/" and access.safe_next("https://evil.example") == "/"
    assert access.safe_next("/?job=1") == "/?job=1" and access.safe_next("/access") == "/"
    assert not access.load_settings({}).enabled
    assert not access.load_settings({"SEMOGWI_SHARE": "1", "SEMOGWI_ACCESS_CODE": "short"}).enabled
    generated = access.load_settings({"SEMOGWI_SHARE": "1"})
    assert generated.enabled and generated.generated and len(generated.code) >= access.CODE_MIN
    custom = access.load_settings({"SEMOGWI_SHARE": "1", "SEMOGWI_SHARE_HOSTS": "semogwi.example.com", "SEMOGWI_ACCESS_CODE": CODE})
    assert custom.hosts == ("semogwi.example.com",)


def test_no_secrets_exposed(share):
    with tunnel_client() as c:
        c.cookies.set(access.COOKIE, login(c).cookies[access.COOKIE])
        for path in ("/docs", "/openapi.json", "/.env", "/../app/main.py", "/%2e%2e/app/main.py", "/app/main.py", "/data/jobs"):
            assert c.get(path).status_code == 404, path
        body = c.get("/api/options").text
        assert CODE not in body and "Users" not in body


def test_detail_fetch_blocks_names_pointing_inside(monkeypatch):
    monkeypatch.setattr(detail_images.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("192.168.0.10", 0))])
    assert not detail_images._public_host("http://intranet.example/a.png")
    monkeypatch.setattr(detail_images.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))])
    assert detail_images._public_host("http://shop.example/a.png")
    assert not detail_images._public_host("http://127.0.0.1/a.png")
