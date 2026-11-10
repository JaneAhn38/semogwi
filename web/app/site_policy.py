"""사이트별 자동 접근 정책과 접속 실패 처리.

- restricted: 이용 조건이 자동 수집을 금지한다고 확인된 사이트. 자동으로 접근하지 않습니다.
- official: 사람이 공식 사이트로 확인해 등록한 사이트. 등록되지 않은 사이트의 공식 여부는 AI 판단으로만 표시합니다.
- 접속을 막은 사이트는 작업과 상관없이 사이트 단위로 일정 시간 다시 요청하지 않습니다.

목록은 site_policy.json에서 관리합니다. 기준과 갱신 방법: docs/site-access-policy.md
"""

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

POLICY_FILE = Path(__file__).resolve().parent / "site_policy.json"
DATA_ROOT = Path(os.environ.get("SEMOGWI_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
COOLDOWN_FILE = DATA_ROOT / "site-cooldowns.json"

_policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))

MIN_RATE_LIMIT_WAIT = 300  # Retry-After가 짧아도 이만큼은 기다립니다 (60초 뒤 다시 429가 난 기록이 있음)
DEFAULT_RATE_LIMIT_WAIT = 600
ACCESS_DENIED_WAIT = 3600
SERVER_ERROR_WAIT = 300


def host_of(url: str) -> str:
    try:
        return (urlparse(url.strip()).hostname or "").lower().rstrip(".").removeprefix("www.")
    except ValueError:
        return ""


def _matches(host: str, domain: str) -> bool:
    return bool(host) and (host == domain or host.endswith(f".{domain}"))


def _find(url: str, group: str) -> dict | None:
    host = host_of(url)
    return next((s for s in _policy[group] if _matches(host, s["domain"])), None)


def restricted_site(url: str) -> dict | None:
    return _find(url, "restricted")


def restricted_sites() -> list[dict]:
    return list(_policy["restricted"])


def is_registered_official(url: str) -> bool:
    return _find(url, "official") is not None


def classify_failure(code: int, retry_after: int | None = None) -> dict:
    """접속 실패의 뜻과, 그 사이트에 다시 요청하지 않을 시간을 정합니다."""
    if code == 429:
        wait = max(retry_after or DEFAULT_RATE_LIMIT_WAIT, MIN_RATE_LIMIT_WAIT)
        return {"label": "요청이 너무 많다고 막았어요", "blocked": True, "cooldown": wait}
    if code == 503:
        wait = max(retry_after or DEFAULT_RATE_LIMIT_WAIT, MIN_RATE_LIMIT_WAIT)
        return {"label": "사이트가 일시적으로 응답하지 않아요", "blocked": True, "cooldown": wait}
    if code in (401, 402, 403, 451):
        return {"label": "자동 접근을 허용하지 않아요", "blocked": True, "cooldown": ACCESS_DENIED_WAIT}
    if code in (404, 410):
        return {"label": "페이지가 없어요", "blocked": False, "cooldown": 0}
    if code >= 500:
        return {"label": "사이트에 오류가 났어요", "blocked": False, "cooldown": SERVER_ERROR_WAIT}
    return {"label": "접속하지 못했어요", "blocked": False, "cooldown": SERVER_ERROR_WAIT}


def _read_cooldowns() -> dict:
    try:
        return json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record_failures(failures: list[dict]) -> None:
    """이벤트 루프에서만 호출합니다."""
    entries = {h: e for h, e in _read_cooldowns().items() if e.get("until", 0) > time.time()}
    now = int(time.time())
    for failure in failures:
        if failure.get("cooldown") and failure.get("host"):
            until = now + int(failure["cooldown"])
            if until > entries.get(failure["host"], {}).get("until", 0):
                entries[failure["host"]] = {"until": until, "code": failure.get("code", 0)}
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = COOLDOWN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(COOLDOWN_FILE)


def cooling_hosts() -> list[str]:
    now = time.time()
    return [host for host, entry in _read_cooldowns().items() if entry.get("until", 0) > now]


def cooldown_until(url: str) -> int:
    entry = _read_cooldowns().get(host_of(url)) or {}
    return int(entry.get("until", 0))


def cooldown_seconds(url: str) -> int:
    return max(0, cooldown_until(url) - int(time.time()))


def deny_rules() -> list[str]:
    """AI 호출에서 차단할 WebFetch 규칙. 금지 사이트와 대기 중인 사이트입니다.

    `*.도메인`은 모든 깊이의 하위 도메인을 막지만 도메인 자체는 막지 않아 두 규칙을 함께 넣습니다.
    와일드카드는 Claude Code v2.1.172 이상에서 동작합니다.
    """
    domains = [s["domain"] for s in restricted_sites()] + cooling_hosts()
    rules = []
    for domain in dict.fromkeys(domains):
        rules += [f"WebFetch(domain:{domain})", f"WebFetch(domain:*.{domain})"]
    return rules
