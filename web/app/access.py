"""외부 공유(Cloudflare Tunnel) 접속 제어.

기본은 로컬 전용입니다. share.bat(또는 SEMOGWI_SHARE=1)으로 켰을 때만, 허용한 공개 주소로 들어온 요청을
접속 코드를 확인한 뒤 받습니다.

- SEMOGWI_SHARE=1             공유 모드를 켭니다.
- SEMOGWI_SHARE_HOSTS         허용할 공개 주소 (쉼표로 구분, *.도메인 가능). 기본: *.trycloudflare.com
- SEMOGWI_ACCESS_CODE         접속 코드 (8자 이상). 비우면 서버를 켤 때마다 새로 만들어 창에 보여 줍니다.
"""

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from html import escape
from urllib.parse import parse_qs, urlparse

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
# Cloudflare를 거친 요청에는 이 헤더가 붙습니다. 브라우저가 로컬 주소로 직접 보낸 요청에는 없습니다
TUNNEL_HEADERS = ("cf-connecting-ip", "cf-ray", "cf-visitor")
DEFAULT_SHARE_HOSTS = "*.trycloudflare.com"
COOKIE = "semogwi_access"
COOKIE_MAX_AGE = 12 * 60 * 60
CODE_MIN = 8
LOGIN_PATH = "/access"
MAX_FAILURES = 10
FAILURE_WINDOW = 10 * 60


@dataclass
class Settings:
    enabled: bool = False
    hosts: tuple[str, ...] = ()
    code: str = ""
    generated: bool = False
    failures: dict[str, list[float]] = field(default_factory=dict)


def load_settings(env=os.environ) -> Settings:
    if env.get("SEMOGWI_SHARE", "").strip() not in ("1", "true", "yes"):
        return Settings()
    hosts = tuple(h.strip().lower() for h in (env.get("SEMOGWI_SHARE_HOSTS") or DEFAULT_SHARE_HOSTS).split(",") if h.strip())
    code = env.get("SEMOGWI_ACCESS_CODE", "").strip()
    if code and len(code) < CODE_MIN:
        print(f"  [share] SEMOGWI_ACCESS_CODE must be at least {CODE_MIN} characters. Sharing is OFF.", flush=True)
        return Settings()
    generated = not code
    return Settings(True, hosts, code or secrets.token_urlsafe(9), generated)


SETTINGS = load_settings()


def announce() -> None:
    if not SETTINGS.enabled:
        return
    print(f"  [share] Sharing ON for: {', '.join(SETTINGS.hosts)}", flush=True)
    if SETTINGS.generated:
        print(f"  [share] Access code (new each start): {SETTINGS.code}", flush=True)
    else:
        print("  [share] Access code: SEMOGWI_ACCESS_CODE", flush=True)


def hostname(host_header: str) -> str:
    return (urlparse(f"//{host_header}").hostname or "").lower()


def via_tunnel(headers) -> bool:
    return any(name in headers for name in TUNNEL_HEADERS)


def is_local(host: str, headers) -> bool:
    return host in LOCAL_HOSTS and not via_tunnel(headers)


def share_host(host: str) -> bool:
    """공유 모드에서 허용한 공개 주소인지 봅니다. *.example.com은 하위 주소만 허용합니다."""
    if not SETTINGS.enabled or not host:
        return False
    for pattern in SETTINGS.hosts:
        if pattern.startswith("*."):
            if host.endswith(pattern[1:]) and host != pattern[2:]:
                return True
        elif host == pattern:
            return True
    return False


def _token() -> str:
    return hmac.new(SETTINGS.code.encode(), b"semogwi-access-v1", hashlib.sha256).hexdigest()


def authorized(cookies) -> bool:
    value = cookies.get(COOKIE, "")
    return bool(SETTINGS.code) and hmac.compare_digest(value, _token())


def client_key(request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def locked(key: str) -> bool:
    now = time.monotonic()
    recent = [t for t in SETTINGS.failures.get(key, []) if now - t < FAILURE_WINDOW]
    SETTINGS.failures[key] = recent
    return len(recent) >= MAX_FAILURES


def record_failure(key: str) -> None:
    SETTINGS.failures.setdefault(key, []).append(time.monotonic())


def read_form(body: bytes) -> tuple[str, str]:
    """로그인 양식에서 (코드, 돌아갈 주소)를 꺼냅니다."""
    form = parse_qs(body[:4096].decode("utf-8", errors="replace"))
    return form.get("code", [""])[0].strip(), safe_next(form.get("next", ["/"])[0])


def check_code(submitted: str) -> bool:
    return bool(SETTINGS.code) and hmac.compare_digest(submitted.encode(), SETTINGS.code.encode())


def safe_next(value: str) -> str:
    """로그인 뒤 돌아갈 주소. 이 사이트 안의 경로만 받습니다."""
    if not value.startswith("/") or value.startswith("//") or "\\" in value or value.startswith(LOGIN_PATH):
        return "/"
    return value


LOGIN_CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"


def login_page(next_path: str, message: str = "") -> str:
    note = f'<p class="err">{escape(message)}</p>' if message else ""
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>세모귀 웹 접속</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f6f7f9;color:#222;display:grid;place-items:center;min-height:100vh;margin:0;padding:16px}}
form{{background:#fff;padding:28px;border-radius:14px;box-shadow:0 2px 12px #0001;width:100%;max-width:340px}}
h1{{font-size:20px;margin:0 0 6px}} p{{font-size:14px;color:#555;margin:0 0 16px}} .err{{color:#c0392b}}
input{{width:100%;box-sizing:border-box;padding:10px;font-size:16px;border:1px solid #ccc;border-radius:8px;margin-bottom:12px}}
button{{width:100%;padding:10px;font-size:16px;border:0;border-radius:8px;background:#2f7d6d;color:#fff;cursor:pointer}}
</style></head><body>
<form method="post" action="{LOGIN_PATH}"><input type="hidden" name="next" value="{escape(next_path, quote=True)}">
<h1>세모귀 웹</h1><p>공유받은 접속 코드를 입력해 주세요.</p>{note}
<input name="code" type="password" autocomplete="current-password" required autofocus aria-label="접속 코드">
<button type="submit">접속</button></form></body></html>"""
