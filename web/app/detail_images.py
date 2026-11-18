"""상세페이지 이미지 자료 (자료 조사용).

쇼핑몰 상세페이지는 상품 설명이 HTML 글자가 아니라 이미지인 경우가 많습니다. WebFetch는 HTML을 글자로 바꿔 읽으므로
이미지 속 상품명·가격·크기·소재·구성품 등을 읽지 못합니다. 이 모듈은 상세 이미지를 자료로 받아 AI 비전으로 읽게 합니다.

이미지를 받는 길은 두 가지입니다.
1. 사용자가 상세페이지 스크린샷이나 이미지 파일을 직접 올립니다. (어느 사이트든 사용자가 직접 본 화면)
2. 사용자가 버튼을 눌렀을 때만, 참고 URL 페이지 한 곳에서 상세 이미지를 찾아 내려받습니다. 이때
   - 자동 접근 금지 사이트(site_policy.json)와 대기 중인 사이트는 요청하지 않습니다.
   - robots.txt가 막은 주소는 페이지든 이미지든 요청하지 않습니다 (이미지가 다른 호스트에 있으면 그 호스트의 robots.txt도 봅니다).
   - 요청을 막은 응답(403, 429 등)을 받으면 사이트 단위 대기에 기록하고 멈춥니다.
   - 요청 사이에 간격을 두고, 한 번에 받는 장수와 크기를 제한합니다.
   자바스크립트로 그리는 상세 영역은 찾지 못할 수 있습니다. 그때는 스크린샷 업로드를 안내합니다.

AI가 읽은 값은 출처 이미지(근거 id img1, img2 …)와 연결합니다. 흐리거나 잘려 읽기 어려운 값은 추측하지 않고 '확인 필요'로 남깁니다.
"""

import ipaddress
import json
import os
import re
import socket
import subprocess
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from . import research as research_items, site_policy
from .imageinfo import image_size
from .outline import unsupported_numbers

TILES_SCRIPT = Path(__file__).resolve().parent / "image_tiles.py"
PYTHON = os.environ.get("SEMOGWI_CUTOUT_PYTHON", "py")  # 배경 제거와 같은 시스템 Python
USER_AGENT = "SemogwiResearch/1.0 (local card-news tool; user-initiated, respects robots.txt)"

MAX_DETAIL_IMAGES = 10  # 작업당 상세 이미지 장수
MAX_TILES_PER_IMAGE = 12
MAX_TILES_TOTAL = 24  # AI 한 번에 보내는 조각 수 (한도 절약)
SMALL_SIDE = 2000  # Pillow가 없을 때 나누지 않고 그대로 보낼 수 있는 크기
PAGE_MAX_BYTES = 3 * 1024 * 1024
IMAGE_MAX_BYTES = 10 * 1024 * 1024
MAX_CANDIDATES = 25
MIN_DETAIL_SIDE = 600  # 이보다 작은 이미지는 아이콘·썸네일로 보고 받지 않습니다
REQUEST_GAP = 0.4  # 같은 사이트 요청 사이 간격(초)
TIMEOUT = 15
SKIP_WORDS = ("icon", "logo", "sprite", "btn", "button", "badge", "blank", "spacer", "loading", "arrow", "banner_top")


class DetailError(Exception):
    """화면에 그대로 보여 줄 수 있는 이유."""


# ---------- 조각 나누기 ----------
def _run_py(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([PYTHON, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, stdin=subprocess.DEVNULL)


def tiles_of(path: Path, out_dir: Path, limit: int) -> dict:
    """{"width", "height", "tiles": [{"path", "top", "bottom"}], "truncated"}. 실패하면 DetailError."""
    try:
        done = _run_py(["-I", str(TILES_SCRIPT), str(path), str(out_dir), str(max(1, limit))], 120)
        info = json.loads(done.stdout) if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        info = None
    if info:
        info["tiles"] = [{**t, "path": out_dir / t["file"]} for t in info["tiles"]]
        return info
    # Pillow를 쓸 수 없으면 작은 이미지만 그대로 보냅니다. 긴 이미지는 줄어들어 글자를 읽지 못하므로 보내지 않습니다
    size = image_size(path)
    if size and max(size) <= SMALL_SIDE:
        return {"width": size[0], "height": size[1], "tiles": [{"path": path, "top": 0, "bottom": size[1]}], "truncated": False}
    raise DetailError("긴 상세 이미지를 나누지 못했어요. 시스템 Python에 Pillow를 설치하거나, 화면을 여러 장으로 나눠 캡처해 올려 주세요.")


# ---------- 이미지 형식 ----------
def detect(head: bytes) -> tuple[str, str] | None:
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png", "image/png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg", "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return None


# ---------- 상세페이지에서 이미지 찾기 (사용자가 요청했을 때만) ----------
class _ImgParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "img":
            return
        values = dict(attrs)
        for key in ("data-src", "data-original", "data-lazy-src", "data-lazy", "src"):
            if values.get(key) and not values[key].startswith("data:"):
                self.found.append(values[key])
                return
        srcset = values.get("srcset") or values.get("data-srcset")
        if srcset:
            last = srcset.split(",")[-1].strip().split(" ")[0]  # 가장 큰 후보
            if last:
                self.found.append(last)


def image_candidates(html: str, page_url: str) -> list[str]:
    parser = _ImgParser()
    try:
        parser.feed(html)
    except Exception:
        pass
    result = []
    for raw in parser.found:
        url = urljoin(page_url, raw.strip())
        parts = urlparse(url)
        path = parts.path.lower()
        if parts.scheme not in ("http", "https") or path.endswith((".svg", ".gif", ".ico")):
            continue
        if any(word in path for word in SKIP_WORDS):
            continue
        if url not in result:
            result.append(url)
    return result[:MAX_CANDIDATES]


def _public_host(url: str) -> bool:
    """로컬·사설망 주소로 요청하지 않습니다."""
    host = (urlparse(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".local"):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    # 도메인 이름이 내부 주소를 가리키는 경우도 막습니다 (외부 공유 시 내부망 요청 방지). 조회 실패는 요청도 실패하므로 그대로 둡니다
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return True
    return all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos)


class _Fetcher:
    """사이트 정책·robots.txt·대기 시간을 지키며 요청합니다. 실패 기록은 failures에 모읍니다."""

    def __init__(self, client):
        self.client = client
        self.robots: dict[str, RobotFileParser | None] = {}
        self.last: dict[str, float] = {}
        self.failures: list[dict] = []
        self.skipped: list[str] = []

    def blocked_reason(self, url: str) -> str | None:
        if not _public_host(url):
            return "로컬·사설망 주소는 요청하지 않아요"
        site = site_policy.restricted_site(url)
        if site:
            return f"{site['name']}은 이용규약상 자동 수집이 금지되어 있어 요청하지 않아요"
        if site_policy.cooldown_seconds(url):
            return "이 사이트가 요청을 막아 잠시 기다리는 중이에요"
        if not self._robots_allow(url):
            return "robots.txt가 자동 수집을 허용하지 않는 주소예요"
        return None

    def _robots_allow(self, url: str) -> bool:
        parts = urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self.robots:
            parser = RobotFileParser()
            try:
                self._wait(origin)
                response = self.client.get(f"{origin}/robots.txt", timeout=TIMEOUT)
                if response.status_code in (401, 403):
                    parser.disallow_all = True
                elif response.status_code >= 400:
                    parser.allow_all = True
                else:
                    parser.parse(response.text.splitlines())
            except Exception:
                parser.allow_all = True  # robots.txt를 받을 수 없으면 일반 규칙대로 허용으로 봅니다 (RFC 9309)
            self.robots[origin] = parser
        return self.robots[origin].can_fetch(USER_AGENT, url)

    def _wait(self, origin: str) -> None:
        gap = REQUEST_GAP - (time.monotonic() - self.last.get(origin, 0))
        if gap > 0:
            time.sleep(gap)
        self.last[origin] = time.monotonic()

    def get(self, url: str, limit: int):
        parts = urlparse(url)
        self._wait(f"{parts.scheme}://{parts.netloc}")
        with self.client.stream("GET", url, timeout=TIMEOUT) as response:
            if response.status_code != 200:
                retry = response.headers.get("retry-after")
                info = site_policy.classify_failure(response.status_code, int(retry) if retry and retry.isdigit() else None)
                self.failures.append({"host": site_policy.host_of(url), "url": url, "code": response.status_code, "attempts": 1, **info})
                return None, response
            final = str(response.url)
            if final != url and self.blocked_reason(final):
                self.skipped.append(f"{final}: 이동한 주소가 허용되지 않아요")
                return None, response
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > limit:
                    return None, response
            return bytes(body), response


def find_page_images(page_url: str, client=None) -> dict:
    """참고 URL 페이지에서 상세 이미지로 보이는 것을 내려받습니다.

    결과: {"images": [{"data", "ext", "mime", "imageUrl", "width", "height"}], "skipped": [...], "failures": [...]}
    정책상 요청할 수 없으면 DetailError를 냅니다 (아무 요청도 하지 않음).
    """
    import httpx

    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, max_redirects=5)
    try:
        fetcher = _Fetcher(client)
        reason = fetcher.blocked_reason(page_url)
        if reason:
            raise DetailError(f"{reason}. 상세페이지를 직접 캡처해 올려 주세요.")
        try:
            body, response = fetcher.get(page_url, PAGE_MAX_BYTES)
        except Exception:
            raise DetailError("페이지에 접속하지 못했어요. 상세페이지를 직접 캡처해 올려 주세요.") from None
        if body is None:
            failure = fetcher.failures[-1] if fetcher.failures else None
            raise DetailError((f"{failure['label']} (HTTP {failure['code']})" if failure else "페이지를 읽지 못했어요") + ". 상세페이지를 직접 캡처해 올려 주세요.")
        html = body.decode(response.encoding or "utf-8", errors="replace")
        images = []
        for url in image_candidates(html, str(response.url)):
            if len(images) >= MAX_DETAIL_IMAGES:
                break
            reason = fetcher.blocked_reason(url)
            if reason:
                fetcher.skipped.append(f"{url}: {reason}")
                continue
            try:
                data, _ = fetcher.get(url, IMAGE_MAX_BYTES)
            except Exception:
                fetcher.skipped.append(f"{url}: 내려받지 못했어요")
                continue
            if data is None:
                if any(f["blocked"] for f in fetcher.failures):
                    break  # 사이트가 막으면 더 요청하지 않습니다
                continue
            kind = detect(data[:16])
            if kind is None:
                continue
            path_size = _size_of(data, kind[0])
            if not path_size or max(path_size) < MIN_DETAIL_SIDE:
                continue
            images.append({"data": data, "ext": kind[0], "mime": kind[1], "imageUrl": url, "width": path_size[0], "height": path_size[1]})
        return {"images": images, "skipped": fetcher.skipped[:20], "failures": fetcher.failures}
    finally:
        if own:
            client.close()


def _size_of(data: bytes, ext: str) -> tuple[int, int] | None:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / f"probe{ext}"
        path.write_bytes(data[:64 * 1024])
        return image_size(path)


# ---------- AI가 읽은 결과 정리 ----------
def refs_of(images: list[dict]) -> dict[str, str]:
    """근거 id(img1 …) → 상세 이미지 id. 올린 순서대로 번호를 붙입니다."""
    return {f"img{n}": image["id"] for n, image in enumerate(images, 1)}


def clean_extraction(content_type: str, raw_items: list, refs: dict[str, str]) -> list[dict]:
    """AI가 이미지에서 읽은 항목을 검사합니다.

    - 없는 항목 이름, 없는 이미지 근거는 버립니다.
    - 'unclear'로 답한 값과, 값의 숫자가 이미지 문장(quote)에 없는 값은 확인 필요로 바꿉니다 (숫자를 지어내지 않게).
    """
    labels = {key: label for key, label, _ in research_items.ITEMS.get(content_type, [])}
    keys = set(labels)
    result = []
    for raw in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(raw, dict) or raw.get("key") not in keys:
            continue
        # 모델이 "img1 · 조각 2"처럼 조각 번호까지 붙여 적어도 이미지 id만 씁니다 (실제 판독에서 확인된 형태)
        found = re.search(r"img\d+", str(raw.get("imageRef") or ""))
        ref = found.group(0) if found else ""
        if ref not in refs:
            continue
        raw = {**raw, "imageRef": ref}
        value = " ".join(str(raw.get("value") or "").split())[:200]
        quote = " ".join(str(raw.get("quote") or "").split())[:160]
        unclear = raw.get("clarity") != "clear" or not value or not quote or bool(unsupported_numbers(value, quote))
        # 읽기 어려운 값은 AI가 짐작한 글자를 저장하지도 보여 주지도 않습니다. 어느 이미지·조각인지만 남겨 사용자가 직접 확인하게 합니다
        # (실제 판독에서 사람이 읽을 수 없게 흐린 날짜를 AI가 "읽기 어려움"으로 표시하면서도 날짜를 적은 적이 있습니다)
        result.append({"key": raw["key"], "label": labels[raw["key"]], "value": "" if unclear else value, "quote": "" if unclear else quote,
                       "imageRef": raw["imageRef"], "imageId": refs[raw["imageRef"]], "tile": _tile_number(raw.get("tile")), "unclear": unclear})
    return result[:80]


def _tile_number(value) -> int:
    found = re.search(r"\d+", str(value or ""))
    return int(found.group(0)) if found else 0


def dropped_count(raw_items: list, cleaned: list) -> int:
    return max(0, len(raw_items if isinstance(raw_items, list) else []) - len(cleaned))


def image_sources(job: dict) -> list[dict]:
    """조사 결과의 sources에 넣을 상세 이미지 출처. verification='image'는 AI가 이미지를 직접 읽었다는 뜻입니다."""
    extraction = job.get("detailExtraction") or {}
    by_id = {i["id"]: i for i in job.get("detailImages") or []}
    sources = []
    for ref, image_id in (extraction.get("refs") or {}).items():
        image = by_id.get(image_id)
        if not image:
            continue
        origin = "페이지에서 받은 상세 이미지" if image["origin"] == "page" else "사용자가 올린 상세 이미지"
        sources.append({"id": ref, "title": f"{origin}: {image['name']}"[:200], "url": image.get("imageUrl") or "",
                        "pageUrl": image.get("pageUrl") or "", "kind": "image", "verification": "image", "origin": "image",
                        "imageId": image_id, "officialBasis": None})
    return sources


def raw_items(extraction: dict | None) -> list[dict]:
    """verify_items에 넣을 형식. 읽기 어려운 값은 unclear로 표시해 값으로 쓰지 않습니다.

    같은 이미지에서 같은 항목을 여러 줄 읽은 것(특징 문구 여러 개 등)은 한 값으로 합칩니다. 출처끼리 값이 다른 경우가 아니라
    한 출처의 여러 부분이기 때문입니다. 다른 이미지나 페이지와 값이 다르면 verify_items가 출처 충돌로 표시합니다.
    """
    merged: dict[tuple, dict] = {}
    result = []
    for i in (extraction or {}).get("items", []):
        if i["unclear"]:
            result.append({"key": i["key"], "value": "", "quote": i["quote"], "sourceIds": [i["imageRef"]], "unclear": True})
            continue
        entry = merged.get((i["key"], i["imageRef"]))
        if entry is None:
            entry = merged[(i["key"], i["imageRef"])] = {"key": i["key"], "value": i["value"], "quote": i["quote"], "sourceIds": [i["imageRef"]], "unclear": False}
            result.append(entry)
        elif i["value"] not in entry["value"].split(" / "):
            entry["value"] = f"{entry['value']} / {i['value']}"[:200]
    return result


def facts_text(extraction: dict | None) -> str:
    """AI 프롬프트에 넣는 '상세 이미지에서 읽은 정보'. 확인된 값만 넣습니다."""
    lines = [f"- [{i['imageRef']}] {i['key']}: {i['value']} (이미지 문장: {i['quote']})" for i in (extraction or {}).get("items", []) if not i["unclear"]]
    return "\n".join(lines)


def is_stale(job: dict) -> bool:
    """상세 이미지가 바뀌어 다시 읽어야 하는지."""
    current = [i["id"] for i in job.get("detailImages") or []]
    extraction = job.get("detailExtraction")
    return bool(current) and (not extraction or extraction.get("status") != "done" or extraction.get("imageIds") != current)
