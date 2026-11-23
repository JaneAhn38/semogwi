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


# ---------- 보조 출처 (auxiliary) ----------
# 공식 출처가 아니고 이용 조건도 확인 중인 사이트(나무위키). 정해진 유형·항목에만 2차 자료로 쓰고 공식 근거로는 쓰지 않습니다.
# 미러 사이트(mirrors)는 원본이 아니므로 근거로 인정하지 않고 자동으로 읽지도 않습니다.
def auxiliary_sites() -> list[dict]:
    return list(_policy.get("auxiliary", []))


def auxiliary_site(url: str) -> dict | None:
    host = host_of(url)
    return next((s for s in auxiliary_sites() if _matches(host, s["domain"])), None)


def mirror_site(url: str) -> dict | None:
    """보조 출처의 미러 사이트면 원본 사이트 정책을 돌려줍니다."""
    host = host_of(url)
    return next((s for s in auxiliary_sites() if any(_matches(host, m) for m in s.get("mirrors", []))), None)


def auxiliary_tag(url: str, content_type: str | None) -> dict | None:
    """출처에 붙일 보조 출처 표시. items: 이 유형에서 근거로 쓸 수 있는 조사 항목 (없으면 어느 항목의 근거도 아님)."""
    site = auxiliary_site(url) or mirror_site(url)
    if site is None:
        return None
    return {"site": site["domain"], "name": site["name"], "label": site["label"], "items": list(site.get("items", {}).get(content_type or "", []))}


def _ai_blocked_domains(content_type: str | None) -> list[str]:
    """AI가 읽지 않을 보조 출처 도메인: 미러 사이트, 그리고 이 유형에서 쓰지 않는 보조 출처 (요청을 줄이는 쪽으로만 씁니다)."""
    domains = []
    for site in auxiliary_sites():
        domains += site.get("mirrors", [])
        if content_type and not site.get("items", {}).get(content_type):
            domains.append(site["domain"])
    return domains


def ai_blocked_labels(content_type: str | None) -> list[str]:
    """프롬프트에 '읽지 않을 사이트'로 알릴 이름."""
    labels = []
    for site in auxiliary_sites():
        labels += [f"{site['name']} 미러 {m}" for m in site.get("mirrors", [])]
        if content_type and not site.get("items", {}).get(content_type):
            labels.append(f"{site['name']} {site['domain']}")
    return labels


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


def blocked_by_rule(url: str, error_text: str = "") -> str:
    """우리 규칙으로 AI 호출에서 막는 사이트인지. "restricted"(금지 사이트), "cooldown"(대기 중),
    "auxiliary"(보조 출처의 미러, 또는 유형에 따라 막는 보조 출처), 아니면 "".

    보조 출처는 유형에 따라 허용될 때도 있어(캐릭터 조사의 나무위키 등), 도구가 차단 규칙 형식
    ("denied access to domain:")으로 거절했을 때만 우리 규칙으로 봅니다.
    """
    if restricted_site(url):
        return "restricted"
    host = host_of(url)
    if any(_matches(host, h) for h in cooling_hosts()):
        return "cooldown"
    auxiliary = [d for site in auxiliary_sites() for d in [site["domain"], *site.get("mirrors", [])]]
    if "denied access to domain:" in error_text.lower() and any(_matches(host, d) for d in auxiliary):
        return "auxiliary"
    return ""


def deny_rules(content_type: str | None = None) -> list[str]:
    """AI 호출에서 차단할 WebFetch 규칙. 금지 사이트, 대기 중인 사이트, 보조 출처의 미러 사이트,
    그리고 content_type이 주어지면 그 유형에서 쓰지 않는 보조 출처(예: 굿즈 조사의 나무위키)입니다.

    `*.도메인`은 모든 깊이의 하위 도메인을 막지만 도메인 자체는 막지 않아 두 규칙을 함께 넣습니다.
    와일드카드는 Claude Code v2.1.172 이상에서 동작합니다.
    """
    domains = [s["domain"] for s in restricted_sites()] + cooling_hosts() + _ai_blocked_domains(content_type)
    rules = []
    for domain in dict.fromkeys(domains):
        rules += [f"WebFetch(domain:{domain})", f"WebFetch(domain:*.{domain})"]
    return rules
