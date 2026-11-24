"""크루 고르기 화면의 후보 미리보기 (2026-11-24).

캐릭터를 모르는 사용자도 후보를 보고 고를 수 있게, 후보마다 작은 사진을 붙입니다.

- 사진(preview): 공식 출처 중 AI가 실제로 읽었고 **그 후보 전용인** 페이지(제목이나 주소에 후보 이름이 있음)에서만 찾습니다.
  서버는 그 페이지 HTML만 한 번 받아(사이트 규칙·robots.txt·대기 시간은 detail_images._Fetcher 그대로)
  페이지가 정한 대표 이미지(og:image·twitter:image), 없으면 alt가 후보 이름인 이미지의 **주소만** 고릅니다.
  이미지 파일은 받지도 저장하지도 않습니다. 브라우저가 원래 주소로 띄우고(referrer 없음), 카드·PNG·사진 칸에는 넣지 않습니다.
  목록 페이지나 중심 캐릭터 페이지의 대표 이미지는 후보가 아닐 수 있어 쓰지 않습니다 (틀린 사진보다 사진 없음이 낫습니다).
- 사진이 없거나 불러오지 못하면 화면(app.js)이 '사진 보기' 버튼을 보여 줍니다: "후보 이름 + 작품명" 네이버 이미지 검색 주소를
  새 탭으로 엽니다. 서버는 그 주소를 만들지도 요청하지도 않습니다 (예전 후보에도 버튼이 나오게 화면에서 만듦).
- 나무위키 등 2차 자료의 이미지는 쓰지 않습니다. 데모와 직접 입력한 후보는 출처가 없어 요청하지 않습니다.
- 조사 자료에 전용 페이지가 없는 후보는, 후보 추천 뒤 AI가 공식 프로필 페이지를 한 번 더 찾습니다(add_profiles, 실제 AI만).
  도구 기록으로 AI가 실제로 읽은 공식 페이지만 받고, 서버가 받은 HTML에도 후보 이름이 있어야 사진을 씁니다.

후보에 붙는 값 (주소 문자열만):
    preview: {imageUrl, pageUrl, site} | None   # None = 찾아봤지만 없음. 키가 없으면 아직 찾지 않음
    profileSource: 출처 기록 | None              # AI가 찾은 공식 프로필 페이지 (None = 찾아봤지만 없음)
"""

import re
import time
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

from . import site_policy
from .detail_images import PAGE_MAX_BYTES, SKIP_WORDS, USER_AGENT, _Fetcher, _public_host

FIND_BUDGET = 20  # 한 번에 미리보기를 찾는 시간(초). 넘으면 남은 후보는 '사진 보기' 버튼만 보여 줍니다
MAX_PAGES = 4  # 한 번에 받는 페이지 수 (후보 최대 4명)
_READ = ("fetched",)


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _http(url: str) -> bool:
    return urlparse(str(url or "")).scheme in ("http", "https")


def site_name(source: dict) -> str:
    aux = site_policy.auxiliary_site(source.get("url", ""))
    return aux["name"] if aux else site_policy.host_of(source.get("url", ""))


def _cited(candidate: dict, sources: list[dict]) -> list[dict]:
    by_id = {s.get("id"): s for s in sources or []}
    found = [by_id[i] for i in candidate.get("sourceIds") or [] if i in by_id]
    if isinstance(candidate.get("profileSource"), dict):
        found.insert(0, candidate["profileSource"])  # 후보 추천 뒤 AI가 찾아 읽은 공식 프로필 페이지 (add_profiles)
    return [s for s in found if _http(s.get("url")) and not site_policy.mirror_site(s["url"]) and s.get("verification") != "mirror"]


def is_own_page(name: str, source: dict) -> bool:
    """그 후보 전용 페이지인지: 페이지 제목이나 주소에 후보 이름이 있어야 합니다."""
    key = _norm(name)
    if len(key) < 2:
        return False
    return key in _norm(source.get("title")) or key in _norm(unquote(urlparse(source.get("url", "")).path))


def page_for(candidate: dict, sources: list[dict]) -> dict | None:
    """사진을 찾을 페이지: 공식 출처이고, AI가 읽었고, 자동 접근이 허용되고, 그 후보 전용인 페이지."""
    for source in _cited(candidate, sources):
        if (source.get("kind") == "official" and source.get("verification") in _READ
                and not site_policy.restricted_site(source["url"]) and is_own_page(candidate.get("name", ""), source)):
            return source
    return None


class _ImageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: list[str] = []
        self.alts: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src") and values.get("content"):
                self.meta.append(values["content"])
        elif tag == "img":
            src = values.get("data-src") or values.get("src") or ""
            if src and not src.startswith("data:"):
                self.alts.append((values.get("alt", ""), src))


def _usable_image(url: str) -> bool:
    parts = urlparse(url)
    path = parts.path.lower()
    if parts.scheme not in ("http", "https") or path.endswith((".svg", ".ico")):
        return False
    if any(word in path for word in SKIP_WORDS):  # 로고·아이콘·배너
        return False
    return not site_policy.restricted_site(url) and _public_host(url)


def image_in(html: str, page_url: str, name: str) -> str | None:
    """페이지가 정한 대표 이미지, 없으면 alt가 후보 이름인 이미지의 주소."""
    parser = _ImageParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    key = _norm(name)
    choices = parser.meta + [src for alt, src in parser.alts if key and _norm(alt) == key]
    for raw in choices:
        url = urljoin(page_url, raw.strip())
        if _usable_image(url):
            return url
    return None


def make_client():
    import httpx

    return httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, max_redirects=5)


def find_image(fetcher: _Fetcher, page: dict, name: str) -> str | None:
    """페이지 한 곳을 읽어 미리보기 주소를 찾습니다. 막혔거나 못 찾으면 None."""
    url = page["url"]
    if fetcher.blocked_reason(url):
        return None
    try:
        body, response = fetcher.get(url, PAGE_MAX_BYTES)
    except Exception:
        return None
    if body is None:
        return None
    html = body.decode(response.encoding or "utf-8", errors="replace")
    if _norm(name) not in _norm(html):
        return None  # 받은 페이지에 후보 이름이 없으면 그 후보의 페이지로 보지 않습니다
    return image_in(html, str(response.url), name)


def add_profiles(candidates: list[dict], research: dict | None, find) -> tuple[list[dict], list[dict]]:
    """사진을 찾을 전용 페이지가 없는 후보만 AI에게 공식 프로필 페이지를 찾게 합니다 (find(names) → {profiles, calls}).

    실패해도 후보는 그대로 둡니다. 결과: (후보 목록, AI 호출 기록)
    """
    sources = (research or {}).get("sources") or []
    result = [dict(c) for c in candidates or []]
    names = [c["name"] for c in result if "preview" not in c and "profileSource" not in c and c.get("name") and not page_for(c, sources)]
    if not names:
        return result, []
    try:
        found = find(names)
    except Exception:
        return result, []
    for c in result:
        if c.get("name") in names:
            c["profileSource"] = found["profiles"].get(c["name"])  # None = 찾아봤지만 없음
    return result, found.get("calls", [])


def attach(candidates: list[dict], research: dict | None, look: bool = True, client=None) -> tuple[list[dict], list[dict]]:
    """후보마다 preview를 붙입니다. look=False면(데모) 요청하지 않습니다.

    이미 찾아본 후보(preview 키가 있음)는 다시 요청하지 않습니다. 결과: (후보 목록, 사이트 접속 실패 기록)
    실패 기록은 이벤트 루프에서 site_policy.record_failures로 남깁니다.
    """
    sources = (research or {}).get("sources") or []
    result = [dict(c) for c in candidates or []]
    for c in result:
        c.pop("link", None)  # 예전 '공식 페이지에서 보기' 링크 (2026-11-24에 '사진 보기' 검색 버튼으로 바꿈)
    pending = [c for c in result if "preview" not in c]
    pages = {id(c): page_for(c, sources) for c in pending} if look else {}
    if not look or not any(pages.values()):
        for c in pending:
            c["preview"] = None
        return result, []
    own = client is None
    client = client or make_client()
    fetcher = _Fetcher(client)
    deadline = time.monotonic() + FIND_BUDGET
    seen: dict[str, str | None] = {}
    blocked_hosts: set[str] = set()
    try:
        for c in pending:
            page = pages.get(id(c))
            c["preview"] = None
            if not page or len(seen) >= MAX_PAGES or time.monotonic() > deadline:
                continue
            host = site_policy.host_of(page["url"])
            if host in blocked_hosts:
                continue
            if page["url"] not in seen:
                seen[page["url"]] = find_image(fetcher, page, c["name"])
                blocked_hosts |= {f["host"] for f in fetcher.failures if f.get("blocked")}  # 막은 사이트에는 더 요청하지 않습니다
            if seen[page["url"]]:
                c["preview"] = {"imageUrl": seen[page["url"]], "pageUrl": page["url"], "site": site_name(page)}
    finally:
        if own:
            client.close()
    return result, fetcher.failures


def merge(job: dict, found: list[dict]) -> None:
    """나중에 찾은 미리보기를 지금 작업의 같은 이름 후보에 붙입니다 (그사이 사용자가 고른 내용은 그대로)."""
    by_name = {c.get("name"): c for c in found}
    pick = job.get("friendPick") or {}
    lists = [pick.get("candidates") or []]
    if isinstance((job.get("research") or {}).get("friendCandidates"), list):
        lists.append(job["research"]["friendCandidates"])
    for items in lists:
        for c in items:
            if c.get("name") in by_name:
                c.pop("link", None)
                for key in ("preview", "profileSource"):
                    if key in by_name[c["name"]]:
                        c[key] = by_name[c["name"]][key]
    pick["previewPending"] = False
